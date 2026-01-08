from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import HTTPException
from starlette.requests import Request

_FULL_SUB_RE = re.compile(r"^projects\/[^\/]+\/subscriptions\/[^\/]+$")
_FULL_TOPIC_RE = re.compile(r"^projects\/[^\/]+\/topics\/[^\/]+$")


def _clean_header(v: Any) -> str:
    s = "" if v is None else str(v)
    # Prevent log injection / header smuggling artifacts from surfacing.
    if "\n" in s or "\r" in s:
        raise HTTPException(status_code=400, detail="invalid_header_value")
    return s.strip()


def _sub_match(body_subscription: str, header_subscription: str) -> bool:
    """
    Accept:
    - exact match
    - header provides short name (suffix after /subscriptions/)
    """
    b = body_subscription.strip()
    h = header_subscription.strip()
    if not b or not h:
        return False
    if b == h:
        return True
    b_short = b.split("/subscriptions/")[-1]
    h_short = h.split("/subscriptions/")[-1]
    return b_short == h_short


def validate_pubsub_push_headers(
    req: Request, *, subscription_from_body: Optional[str] = None
) -> dict[str, Optional[str]]:
    """
    Validate headers for a Pub/Sub HTTP push request.

    - Require JSON content type.
    - If Pub/Sub-specific headers are present, validate they are well-formed.
    - If subscription is provided in body, require it to match header subscription (when header exists).

    No authentication decisions are made here.
    """
    ct = _clean_header(req.headers.get("content-type"))
    if "application/json" not in ct.lower():
        raise HTTPException(status_code=415, detail="unsupported_media_type")

    header_subscription = _clean_header(
        req.headers.get("x-goog-subscription") or req.headers.get("x-goog-subscription-name")
    )
    if header_subscription:
        # Allow either full resource name or short subscription id.
        if ("/subscriptions/" not in header_subscription) and (not _FULL_SUB_RE.match(f"projects/x/subscriptions/{header_subscription}")):
            raise HTTPException(status_code=400, detail="invalid_x_goog_subscription")

    header_topic = _clean_header(req.headers.get("x-goog-topic"))
    if header_topic:
        if not _FULL_TOPIC_RE.match(header_topic):
            raise HTTPException(status_code=400, detail="invalid_x_goog_topic")

    if subscription_from_body and header_subscription:
        if not _sub_match(subscription_from_body, header_subscription):
            raise HTTPException(status_code=400, detail="subscription_header_mismatch")

    return {
        "content_type": ct or None,
        "header_subscription": header_subscription or None,
        "header_topic": header_topic or None,
    }

