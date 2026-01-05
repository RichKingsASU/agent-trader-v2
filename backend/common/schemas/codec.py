from __future__ import annotations

from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def encode_message(msg: BaseModel) -> bytes:
    """
    Encode a Pydantic model as UTF-8 JSON bytes for NATS.
    """

    # Pydantic v2
    if hasattr(msg, "model_dump_json"):
        return msg.model_dump_json().encode("utf-8")  # type: ignore[attr-defined]
    # Pydantic v1 fallback
    return msg.json().encode("utf-8")  # pragma: no cover


def decode_message(model: Type[T], raw: bytes | str) -> T:
    """
    Decode and validate JSON into the given schema model.
    """

    if isinstance(raw, bytes):
        raw_in: Any = raw
    else:
        raw_in = raw.encode("utf-8")

    # Pydantic v2
    if hasattr(model, "model_validate_json"):
        return model.model_validate_json(raw_in)  # type: ignore[attr-defined]

    # Pydantic v1 fallback
    return model.parse_raw(raw_in)  # pragma: no cover

