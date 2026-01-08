from __future__ import annotations

import os
import random
import time
from typing import Any, Mapping, Optional

from backend.messaging.envelope import EventEnvelope
from backend.messaging.pubsub_attributes import (
    EVENT_ENVELOPE_SCHEMA_VERSION,
    build_standard_attributes,
    resolve_environment,
)
from backend.observability.ops_json_logger import log as log_json


class PubSubPublisher:
    """
    Google Pub/Sub publisher for agent events.

    Lazy-imports `google.cloud.pubsub_v1` so the codebase can still import/compile
    in environments where Pub/Sub dependencies are not installed yet.
    """

    def __init__(
        self,
        *,
        project_id: str,
        topic_id: str,
        agent_name: str,
        git_sha: Optional[str] = None,
        publisher_client: Any = None,
        validate_credentials: bool = True,
    ) -> None:
        self.project_id = str(project_id)
        self.topic_id = str(topic_id)
        self.agent_name = str(agent_name)
        self.git_sha = git_sha

        if publisher_client is None:
            try:
                from google.cloud import pubsub_v1  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError(
                    "google-cloud-pubsub is required to use PubSubPublisher. "
                    "Install with: pip install google-cloud-pubsub"
                ) from e
            publisher_client = pubsub_v1.PublisherClient()
            if validate_credentials:
                # Fail fast on invalid Application Default Credentials (ADC) /
                # workload identity / service account configuration.
                self._validate_credentials_or_raise()

        self._client = publisher_client
        self._topic_path = self._client.topic_path(self.project_id, self.topic_id)

    @property
    def topic_path(self) -> str:
        return self._topic_path

    def close(self) -> None:
        """
        Best-effort shutdown for publisher background resources.

        Note: google-cloud-pubsub may maintain background threads for batching.
        """
        try:
            # Preferred: GAPIC transport close.
            transport = getattr(self._client, "transport", None)
            if transport is not None and hasattr(transport, "close"):
                transport.close()
                return
            # Fallback: direct close if exposed.
            if hasattr(self._client, "close"):
                self._client.close()  # type: ignore[no-untyped-call]
        except Exception:
            # Never raise during shutdown.
            return

    def _validate_credentials_or_raise(self) -> None:
        """
        Validate ADC can mint an access token for Pub/Sub.

        This does not require any Pub/Sub permissions (beyond token minting),
        and avoids emitting a real message.
        """
        try:
            import google.auth  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/pubsub"]
            )
            creds.refresh(Request())
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Pub/Sub credentials are invalid or unavailable. "
                "Ensure Application Default Credentials are configured."
            ) from e

    def _publish_retry_config(self) -> dict[str, float | int]:
        # Environment overrides allow safe tuning without infra edits.
        def _env_int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)).strip())
            except Exception:
                return default

        def _env_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)).strip())
            except Exception:
                return default

        return {
            "max_attempts": max(1, _env_int("PUBSUB_PUBLISH_MAX_ATTEMPTS", 5)),
            "initial_backoff_s": max(0.0, _env_float("PUBSUB_PUBLISH_INITIAL_BACKOFF_S", 0.25)),
            "max_backoff_s": max(0.0, _env_float("PUBSUB_PUBLISH_MAX_BACKOFF_S", 5.0)),
            "deadline_s": max(0.1, _env_float("PUBSUB_PUBLISH_DEADLINE_S", 15.0)),
        }

    def _default_environment(self) -> str:
        # Keep consistent with ops logger conventions, but avoid importing internals.
        return (
            (os.getenv("ENVIRONMENT") or "").strip()
            or (os.getenv("ENV") or "").strip()
            or (os.getenv("APP_ENV") or "").strip()
            or (os.getenv("DEPLOY_ENV") or "").strip()
            or "unknown"
        )

    def _schema_version(self) -> str:
        # Publish-time schema identifier for message consumers / filtering.
        # This does NOT change the JSON payload/envelope shape.
        return (os.getenv("PUBSUB_SCHEMA_VERSION") or "").strip() or "1"

    def _exc_code(self, exc: BaseException) -> str:
        """
        Best-effort extraction of a stable error code string.
        """
        try:
            code = getattr(exc, "code", None)
            if callable(code):
                code = code()
            if code is None:
                return ""
            return str(code)
        except Exception:
            return ""

    def _is_retryable_publish_error(self, exc: BaseException) -> bool:
        # Never retry programming/validation errors.
        if isinstance(exc, (ValueError, TypeError, AttributeError)):
            return False

        # Prefer explicit Google API codes when available.
        code = self._exc_code(exc).upper()
        retryable_codes = {
            "UNAVAILABLE",
            "DEADLINE_EXCEEDED",
            "ABORTED",
            "INTERNAL",
            "RESOURCE_EXHAUSTED",
            "UNKNOWN",
        }
        non_retryable_codes = {
            "INVALID_ARGUMENT",
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "FAILED_PRECONDITION",
            "NOT_FOUND",
            "ALREADY_EXISTS",
        }
        if code in retryable_codes:
            return True
        if code in non_retryable_codes:
            return False

        # Fallback by exception type name (avoid importing optional deps).
        name = exc.__class__.__name__
        if name in {
            "ServiceUnavailable",
            "DeadlineExceeded",
            "InternalServerError",
            "Aborted",
            "ResourceExhausted",
            "Unknown",
        }:
            return True
        if name in {"Unauthenticated", "PermissionDenied", "InvalidArgument"}:
            return False

        # Default: be conservative and retry once for unknown transient-ish failures.
        return True

    def _sleep_backoff(self, *, attempt: int, initial_backoff_s: float, max_backoff_s: float) -> float:
        base = initial_backoff_s * (2 ** max(0, attempt - 1))
        backoff = min(max_backoff_s, base)
        # Full jitter (avoid thundering herd).
        sleep_s = backoff * random.uniform(0.5, 1.5)
        time.sleep(max(0.0, sleep_s))
        return sleep_s

    def publish_envelope(self, envelope: EventEnvelope) -> str:
        """
        Publish a fully-formed envelope.

        Returns a Pub/Sub message id (string).
        """

        cfg = self._publish_retry_config()
        max_attempts = int(cfg["max_attempts"])
        deadline_s = float(cfg["deadline_s"])

        started = time.monotonic()
        last_exc: Optional[BaseException] = None

        std_attrs = build_standard_attributes(
            event_type=envelope.event_type,
            schema_version=EVENT_ENVELOPE_SCHEMA_VERSION,
            producer=envelope.agent_name,
            environment=resolve_environment(),
        )
        # Keep existing non-standard attributes for filtering/debugging.
        publish_attrs: dict[str, str] = {
            **std_attrs,
            "agent_name": envelope.agent_name,
            "trace_id": envelope.trace_id,
            "git_sha": envelope.git_sha,
            "ts": envelope.ts,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                remaining = max(0.0, deadline_s - (time.monotonic() - started))
                timeout_s = max(0.1, remaining)

                schema_version = self._schema_version()
                producer = str(envelope.agent_name)
                environment = self._default_environment()

                future = self._client.publish(
                    self._topic_path,
                    envelope.to_bytes(),
                    # Attributes only (payload bodies MUST NOT be mutated).
                    **publish_attrs,
                )
                message_id = str(future.result(timeout=timeout_s))

                log_json(
                    None,
                    "pubsub_publish_success",
                    severity="INFO",
                    metric="pubsub_publish_success",
                    topic=self._topic_path,
                    message_id=message_id,
                    event_type=std_attrs["event_type"],
                    schema_version=std_attrs["schema_version"],
                    producer=std_attrs["producer"],
                    environment=std_attrs["environment"],
                    agent_name=envelope.agent_name,  # legacy
                    trace_id=envelope.trace_id,
                    attempt=attempt,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
                return message_id
            except Exception as e:
                last_exc = e
                retryable = self._is_retryable_publish_error(e)
                code = self._exc_code(e)

                log_json(
                    None,
                    "pubsub_publish_failure",
                    severity="ERROR" if (not retryable or attempt == max_attempts) else "WARNING",
                    metric="pubsub_publish_failure",
                    topic=self._topic_path,
                    event_type=std_attrs["event_type"],
                    schema_version=std_attrs["schema_version"],
                    producer=std_attrs["producer"],
                    environment=std_attrs["environment"],
                    agent_name=envelope.agent_name,  # legacy
                    trace_id=envelope.trace_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    retryable=bool(retryable),
                    error_type=e.__class__.__name__,
                    error_code=code,
                    error=str(e),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )

                if (not retryable) or attempt >= max_attempts:
                    raise

                self._sleep_backoff(
                    attempt=attempt,
                    initial_backoff_s=float(cfg["initial_backoff_s"]),
                    max_backoff_s=float(cfg["max_backoff_s"]),
                )

        # Defensive: should be unreachable due to raise/return in loop.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Pub/Sub publish failed without exception")

    def publish_event(
        self,
        *,
        event_type: str,
        payload: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        envelope = EventEnvelope.new(
            event_type=event_type,
            agent_name=self.agent_name,
            git_sha=self.git_sha,
            payload=payload,
            trace_id=trace_id,
        )
        return self.publish_envelope(envelope)

    def close(self) -> None:
        """
        Best-effort shutdown for the underlying Pub/Sub client.

        Rationale: PublisherClient can own background threads/batching and gRPC channels.
        This method is intentionally defensive across google-cloud-pubsub versions.
        """
        client = getattr(self, "_client", None)
        if client is None:
            return

        # Stop background batching threads (older versions).
        try:
            stop = getattr(client, "stop", None)
            if callable(stop):
                stop()
        except Exception:
            pass

        # Close transport / channels (newer versions).
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

        try:
            transport = getattr(client, "transport", None)
            transport_close = getattr(transport, "close", None)
            if callable(transport_close):
                transport_close()
        except Exception:
            pass

    def __enter__(self) -> "PubSubPublisher":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

