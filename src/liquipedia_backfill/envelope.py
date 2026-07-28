"""Pure validation for successful Liquipedia API response envelopes."""

from __future__ import annotations

import json


class ResponseEnvelopeError(ValueError):
    """Raised when HTTP 200 bytes do not satisfy the API response envelope."""


def response_record_count(body: bytes) -> int:
    """Validate the API envelope and return its result-array length."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResponseEnvelopeError("Response is not valid UTF-8 JSON.") from error
    if not isinstance(payload, dict):
        raise ResponseEnvelopeError("Response root must be an object.")
    if payload.get("error"):
        raise ResponseEnvelopeError(
            f"Response contains API errors: {payload['error']!r}"
        )
    result = payload.get("result")
    if not isinstance(result, list):
        raise ResponseEnvelopeError("Response result must be an array.")
    if any(not isinstance(record, dict) for record in result):
        raise ResponseEnvelopeError("Every response record must be an object.")
    return len(result)
