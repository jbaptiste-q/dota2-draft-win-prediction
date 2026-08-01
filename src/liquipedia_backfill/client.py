"""Narrow official LiquipediaDB HTTP client used by the backfill runner."""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contract import USER_AGENT
from .planner import RequestSpec


class ApiRequestError(RuntimeError):
    """A redacted official API request failure."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Decompressed response bytes and safe HTTP metadata."""

    body: bytes
    status: int
    content_type: str
    content_encoding: str


def request_page(
    request_spec: RequestSpec,
    *,
    api_key: str,
    timeout_seconds: float = 30.0,
    user_agent: str = USER_AGENT,
) -> HttpResponse:
    """Make one GET request without exposing credentials in its URL."""
    key = api_key.strip()
    if not key or any(character.isspace() for character in key):
        raise ValueError("A non-empty API key without whitespace is required.")
    request = Request(
        request_spec.url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Authorization": f"Apikey {key}",
            "User-Agent": user_agent,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            headers = {
                name.casefold(): value
                for name, value in response.headers.items()
            }
            content_encoding = headers.get("content-encoding", "")
            if content_encoding.casefold() == "gzip":
                body = gzip.decompress(body)
            return HttpResponse(
                body=body,
                status=int(response.status),
                content_type=headers.get("content-type", ""),
                content_encoding=content_encoding,
            )
    except HTTPError as error:
        try:
            body = error.read()
        except TimeoutError as timeout_error:
            raise ApiRequestError(
                "Liquipedia API request failed: response read timed out",
                status=error.code,
            ) from timeout_error
        if error.headers.get("Content-Encoding", "").casefold() == "gzip":
            body = gzip.decompress(body)
        message = body.decode("utf-8", errors="replace")[:500]
        message = message.replace(key, "<redacted-api-key>")
        retry_after = error.headers.get("Retry-After")
        raise ApiRequestError(
            f"Liquipedia API returned HTTP {error.code}: {message}",
            status=error.code,
            retry_after=retry_after,
        ) from error
    except TimeoutError as error:
        raise ApiRequestError(
            "Liquipedia API request failed: response read timed out"
        ) from error
    except URLError as error:
        raise ApiRequestError(
            f"Liquipedia API request failed: {error.reason}"
        ) from error
