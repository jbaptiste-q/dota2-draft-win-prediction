"""Milestone 9 Phase 2, Step 2: LLM semantic labeling of hero changes.

This is the only module in Phase 2 that issues network calls (to the
Anthropic Messages API). Like patch_notes_client.py and hero_mapping.py
in Phase 1, it stays out of tests/ -- tests/conftest.py unconditionally
blocks outbound sockets for every collected test, and tests here mock
the LLMClient protocol instead of hitting the real API.

Uses httpx (already a project dependency) directly against the Messages
API rather than adding the anthropic SDK as a new dependency.

The model identifier is always a caller-supplied parameter -- never
hardcoded -- and every result is cached on disk keyed by
(change_uid, model_id, prompt_version) so re-running issues zero new
calls and reproduces byte-identical output.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import httpx

from src.patch_alignment.change_flattening import FlattenedChange

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 60.0
# Some model generations (e.g. claude-sonnet-5, claude-fable-5) default to
# adaptive extended thinking that cannot be disabled (no
# thinking.type=disabled option) and is billed out of the same max_tokens
# budget as the answer. When the budget is tight, thinking can consume it
# entirely and the call never reaches the JSON answer -- observed thinking
# usage up to the full 64-token budget in practice. 1024 leaves comfortable
# headroom; the on-disk label cache means this cost is paid once per
# change_uid/model_id/prompt_version regardless.
DEFAULT_MAX_TOKENS = 2048
LABELING_TEMPERATURE = 0.0

# Bump manually whenever SYSTEM_PROMPT or USER_PROMPT_TEMPLATE changes.
# Cache keys and committed labels both carry this string, so a bump
# naturally invalidates old cache entries without deleting anything.
PROMPT_VERSION = "m9-phase2-v1"

DIRECTIONS = ("buff", "nerf", "neutral", "rework", "unclear")
MAGNITUDES = ("minor", "moderate", "major", "unclear")
CHANGE_TYPES = (
    "stat", "ability", "talent", "facet", "cost", "cooldown", "scaling", "other",
)
CONFIDENCES = ("low", "medium", "high")

SYSTEM_PROMPT = """You are labeling a single Dota 2 patch-note change with a strict, \
enumerated taxonomy. You will be given one change's text and minimal hero and \
scope context. You do not know pick rates, win rates, or any statistics beyond \
what is in the text.

Output ONLY a single JSON object with exactly these four keys:

{"direction": "buff|nerf|neutral|rework|unclear", \
"magnitude": "minor|moderate|major|unclear", \
"change_type": "stat|ability|talent|facet|cost|cooldown|scaling|other", \
"confidence": "low|medium|high"}

Rules:
- Choose values only from the enumerated options above, spelled exactly as shown.
- "unclear" is a valid and often correct answer for direction and magnitude. \
Prefer "unclear" over guessing when the text does not clearly indicate the answer.
- Do not include any explanation, rationale, or additional keys. Output only \
the JSON object, nothing else."""

USER_PROMPT_TEMPLATE = """Change text: "{raw_text}"

Context: hero={hero_context}, scope={scope}"""


class LabelParseError(RuntimeError):
    """Raised when a model response cannot be parsed into the label schema."""


class LLMClientError(RuntimeError):
    """Raised when the underlying API call itself fails (auth, network, HTTP)."""


@dataclass(frozen=True, slots=True)
class RawLLMResponse:
    """The unparsed result of one model call."""

    text: str
    model_id_returned: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LabelResult:
    """One change's parsed, validated label."""

    direction: str
    magnitude: str
    change_type: str
    confidence: str
    model_id_requested: str
    model_id_returned: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    """Minimal interface the labeling pipeline depends on.

    The real implementation (AnthropicMessagesClient) calls the network;
    tests inject a fake implementing this same protocol so the offline
    suite never touches the network.
    """

    def complete(self, *, model_id: str, system: str, user: str) -> RawLLMResponse: ...


@dataclass(frozen=True, slots=True)
class AnthropicMessagesClient:
    """Calls the Anthropic Messages API directly over HTTP via httpx."""

    api_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, env_var: str = DEFAULT_API_KEY_ENV_VAR) -> "AnthropicMessagesClient":
        api_key = os.environ.get(env_var)
        if not api_key:
            raise LLMClientError(
                f"{env_var} is not set. Refusing to construct a client with no "
                "credentials rather than fail on the first call."
            )
        return cls(api_key=api_key)

    def complete(self, *, model_id: str, system: str, user: str) -> RawLLMResponse:
        body = {
            "model": model_id,
            "max_tokens": self.max_tokens,
            "temperature": LABELING_TEMPERATURE,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        payload = self._post(body, model_id=model_id)
        return self._parse_response(payload, model_id=model_id)

    def _post(self, body: dict, *, model_id: str) -> dict:
        try:
            response = httpx.post(
                ANTHROPIC_MESSAGES_URL,
                timeout=self.timeout_seconds,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            # Some model generations (e.g. claude-sonnet-5, claude-fable-5)
            # reject `temperature` outright rather than accepting and
            # ignoring it. Retry once without it rather than hardcoding a
            # per-model allowlist that would go stale. Determinism is still
            # guaranteed at the pipeline level by the on-disk label cache
            # (each change_uid/model_id/prompt_version is only ever called
            # once, live output is never re-requested), independent of
            # whether the API honors temperature=0 for a given model.
            if (
                error.response.status_code == 400
                and "temperature" in body
                and "temperature" in error.response.text
                and "deprecated" in error.response.text
            ):
                retry_body = {key: value for key, value in body.items() if key != "temperature"}
                return self._post(retry_body, model_id=model_id)
            raise LLMClientError(f"Anthropic API call failed for {model_id}: {error}") from error
        except httpx.HTTPError as error:
            raise LLMClientError(f"Anthropic API call failed for {model_id}: {error}") from error
        return response.json()

    def _parse_response(self, payload: dict, *, model_id: str) -> RawLLMResponse:
        content_blocks = payload.get("content") or []
        text = "".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
        usage = payload.get("usage") or {}
        model_id_returned = payload.get("model")
        if not text or not model_id_returned:
            raise LLMClientError(
                f"Anthropic API response for {model_id} is missing text or model: {payload!r}"
            )
        return RawLLMResponse(
            text=text,
            model_id_returned=model_id_returned,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )


def build_prompt(change: FlattenedChange) -> tuple[str, str]:
    """Return (system, user) prompt strings for one change. No stats leak in."""

    hero_context = change.hero_key if change.hero_key else f"unmapped (hero_id={change.hero_id})"
    user = USER_PROMPT_TEMPLATE.format(
        raw_text=change.raw_text, hero_context=hero_context, scope=change.scope
    )
    return SYSTEM_PROMPT, user


# Flat, non-nested JSON objects only -- matches our schema, and lets this
# find every top-level {...} candidate in a response even when the model
# self-corrects (writes a malformed attempt, notices, and writes a second,
# valid one after some prose) rather than requiring the whole response to
# be exactly one JSON document.
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

_REQUIRED_FIELDS = {
    "direction": DIRECTIONS,
    "magnitude": MAGNITUDES,
    "change_type": CHANGE_TYPES,
    "confidence": CONFIDENCES,
}


def _validate_label_fields(parsed: object) -> dict[str, str]:
    if not isinstance(parsed, dict):
        raise LabelParseError(f"Response JSON is not an object: {parsed!r}")
    result: dict[str, str] = {}
    for key, allowed in _REQUIRED_FIELDS.items():
        value = parsed.get(key)
        if value not in allowed:
            raise LabelParseError(f"Field {key!r} is {value!r}, expected one of {allowed}")
        result[key] = value
    return result


def parse_label_text(text: str) -> dict[str, str]:
    """Parse and validate a model's raw text into the four-field label schema.

    Tries every {...} candidate found in the text, last to first: a model
    that self-corrects (writes an invalid attempt, then "Wait, let me
    reconsider" and a corrected block) puts its intended answer last, and
    this recovers it instead of failing on the discarded first attempt.
    """

    candidates = _JSON_OBJECT_RE.findall(text)
    if not candidates:
        raise LabelParseError(f"No JSON object found in response: {text!r}")

    last_error: Exception | None = None
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error
            continue
        try:
            return _validate_label_fields(parsed)
        except LabelParseError as error:
            last_error = error
            continue

    raise LabelParseError(
        f"No candidate JSON object validated (tried {len(candidates)}): {text!r}"
    ) from last_error


class LabelCache:
    """A flat JSON-file cache keyed by (change_uid, model_id, prompt_version).

    Never stores raw_text -- only the enumerated label fields and call
    bookkeeping (returned model id, token counts). Safe to keep local and
    regenerate; nothing in it is Valve's content.
    """

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._data: dict[str, dict] = {}
        if cache_path.exists():
            self._data = json.loads(cache_path.read_text(encoding="utf-8"))

    @staticmethod
    def key(*, change_uid: str, model_id: str, prompt_version: str) -> str:
        return f"{change_uid}|{model_id}|{prompt_version}"

    def get(self, *, change_uid: str, model_id: str, prompt_version: str) -> dict | None:
        return self._data.get(self.key(
            change_uid=change_uid, model_id=model_id, prompt_version=prompt_version
        ))

    def put(self, *, change_uid: str, model_id: str, prompt_version: str, entry: dict) -> None:
        self._data[self.key(
            change_uid=change_uid, model_id=model_id, prompt_version=prompt_version
        )] = entry

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def label_change(
    change: FlattenedChange,
    *,
    model_id: str,
    client: LLMClient,
    cache: LabelCache,
    prompt_version: str = PROMPT_VERSION,
) -> LabelResult:
    """Label one change, hitting the cache before ever calling the client."""

    cached = cache.get(change_uid=change.change_uid, model_id=model_id, prompt_version=prompt_version)
    if cached is not None:
        if cached.get("status") == "ok":
            return LabelResult(**cached["result"])
        if cached.get("status") == "parse_error":
            # Cached failure: replay it without a new call, so a re-run stays
            # zero-new-calls even for changes that never parsed cleanly.
            raise LabelParseError(cached.get("error", "cached parse failure"))

    system, user = build_prompt(change)
    response = client.complete(model_id=model_id, system=system, user=user)
    try:
        label_fields = parse_label_text(response.text)
    except LabelParseError as error:
        cache.put(
            change_uid=change.change_uid, model_id=model_id, prompt_version=prompt_version,
            entry={"status": "parse_error", "error": str(error)},
        )
        raise

    result = LabelResult(
        **label_fields,
        model_id_requested=model_id,
        model_id_returned=response.model_id_returned,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    cache.put(
        change_uid=change.change_uid, model_id=model_id, prompt_version=prompt_version,
        entry={"status": "ok", "result": asdict(result)},
    )
    return result


__all__ = [
    "ANTHROPIC_MESSAGES_URL",
    "CHANGE_TYPES",
    "CONFIDENCES",
    "DEFAULT_API_KEY_ENV_VAR",
    "DIRECTIONS",
    "LABELING_TEMPERATURE",
    "MAGNITUDES",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "AnthropicMessagesClient",
    "LLMClient",
    "LLMClientError",
    "LabelCache",
    "LabelParseError",
    "LabelResult",
    "RawLLMResponse",
    "build_prompt",
    "label_change",
    "parse_label_text",
]
