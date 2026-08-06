"""Offline tests for Milestone 9 Phase 2 Step 2: LLM labeling.

The real AnthropicMessagesClient is never invoked -- these tests use a
FakeLLMClient implementing the same protocol, so nothing here touches
the network (and tests/conftest.py would fail the test outright if it did).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.patch_alignment.change_flattening import FlattenedChange
from src.patch_alignment.llm_labeling import (
    AnthropicMessagesClient,
    LabelCache,
    LabelParseError,
    LLMClientError,
    PROMPT_VERSION,
    RawLLMResponse,
    build_prompt,
    label_change,
    parse_label_text,
)


def make_change(**overrides: object) -> FlattenedChange:
    defaults = dict(
        change_uid="fixture-uid",
        patch="9.99z",
        hero_id=1,
        hero_key="fixture_hero",
        json_path="heroes[0].hero_notes[0]",
        scope="hero",
        raw_text="Base damage reduced by 2",
    )
    defaults.update(overrides)
    return FlattenedChange(**defaults)


class FakeLLMClient:
    def __init__(self, responses: dict[str, RawLLMResponse | Exception]):
        self._responses = responses
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, *, model_id: str, system: str, user: str) -> RawLLMResponse:
        self.calls.append((model_id, system, user))
        outcome = self._responses[model_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def valid_response(model_id_returned: str = "claude-sonnet-5") -> RawLLMResponse:
    return RawLLMResponse(
        text=json.dumps(
            {"direction": "nerf", "magnitude": "minor", "change_type": "stat", "confidence": "high"}
        ),
        model_id_returned=model_id_returned,
        input_tokens=42,
        output_tokens=8,
    )


def test_build_prompt_includes_hero_context_and_no_stats_data() -> None:
    system, user = build_prompt(make_change())
    assert "fixture_hero" in user
    assert "scope=hero" in user
    assert "Base damage reduced by 2" in user
    # The system prompt tells the model it has no stats access (a negation);
    # the user prompt -- what actually varies per call -- must never carry
    # any pick-rate/win-rate figures.
    assert "pick rate" not in user.lower()
    assert "win rate" not in user.lower()


def test_build_prompt_flags_unmapped_hero() -> None:
    _, user = build_prompt(make_change(hero_key=None, hero_id=42))
    assert "unmapped (hero_id=42)" in user


@pytest.mark.parametrize(
    "text",
    [
        '{"direction": "buff", "magnitude": "major", "change_type": "ability", "confidence": "low"}',
        '```json\n{"direction": "unclear", "magnitude": "unclear", "change_type": "other", "confidence": "medium"}\n```',
    ],
)
def test_parse_label_text_accepts_valid_json(text: str) -> None:
    result = parse_label_text(text)
    assert set(result) == {"direction", "magnitude", "change_type", "confidence"}


def test_parse_label_text_recovers_self_correction_pattern() -> None:
    # Observed in production: the model writes an invalid first attempt
    # (duplicate key / extra key / bad enum value), notices, and writes a
    # corrected block afterward. The corrected, later block should win.
    text = (
        '```json\n{"direction": "unclear", "magnitude": "unclear", '
        '"change_type": "ability", "scaling": "stat"}\n```\n\n'
        "Wait, let me reconsider. The change_type should be one of the "
        "specified options only.\n\n"
        '```json\n{"direction": "unclear", "magnitude": "unclear", '
        '"change_type": "ability", "confidence": "low"}\n```'
    )
    result = parse_label_text(text)
    assert result == {
        "direction": "unclear", "magnitude": "unclear",
        "change_type": "ability", "confidence": "low",
    }


def test_parse_label_text_rejects_when_no_candidate_validates() -> None:
    # Both attempts are broken (missing confidence both times) -- there is
    # no valid answer to recover, so this must still fail loudly.
    text = (
        '```json\n{"direction": "buff", "magnitude": "minor", '
        '"change_type": "ability", "change_type": "other"}\n```\n\n'
        "Wait, that still is not right.\n\n"
        '```json\n{"direction": "buff", "magnitude": "minor", '
        '"change_type": "stat", "change_type": "other"}\n```'
    )
    with pytest.raises(LabelParseError):
        parse_label_text(text)


def test_parse_label_text_tolerates_extra_keys() -> None:
    text = json.dumps(
        {
            "direction": "buff", "magnitude": "major", "change_type": "ability",
            "confidence": "low", "rationale": "not requested but present",
        }
    )
    result = parse_label_text(text)
    assert "rationale" not in result


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        '{"direction": "buff"}',
        '{"direction": "op", "magnitude": "major", "change_type": "ability", "confidence": "low"}',
        "[]",
    ],
)
def test_parse_label_text_rejects_invalid_shapes(text: str) -> None:
    with pytest.raises(LabelParseError):
        parse_label_text(text)


def test_label_cache_round_trips_through_disk(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = LabelCache(cache_path)
    cache.put(change_uid="u1", model_id="m1", prompt_version="v1", entry={"status": "ok", "result": {"x": 1}})
    cache.save()

    reloaded = LabelCache(cache_path)
    assert reloaded.get(change_uid="u1", model_id="m1", prompt_version="v1") == {
        "status": "ok", "result": {"x": 1}
    }
    assert reloaded.get(change_uid="u1", model_id="m1", prompt_version="v2") is None


def test_label_change_calls_once_then_hits_cache(tmp_path: Path) -> None:
    change = make_change()
    client = FakeLLMClient({"claude-sonnet-5": valid_response()})
    cache = LabelCache(tmp_path / "cache.json")

    first = label_change(change, model_id="claude-sonnet-5", client=client, cache=cache)
    second = label_change(change, model_id="claude-sonnet-5", client=client, cache=cache)

    assert len(client.calls) == 1
    assert first == second
    assert first.direction == "nerf"
    assert first.model_id_requested == "claude-sonnet-5"
    assert first.model_id_returned == "claude-sonnet-5"


def test_label_change_records_model_id_mismatch(tmp_path: Path) -> None:
    change = make_change()
    client = FakeLLMClient({"claude-fable-5": valid_response(model_id_returned="claude-fable-5-20260101")})
    cache = LabelCache(tmp_path / "cache.json")

    result = label_change(change, model_id="claude-fable-5", client=client, cache=cache)
    assert result.model_id_requested == "claude-fable-5"
    assert result.model_id_returned == "claude-fable-5-20260101"


def test_label_change_caches_parse_failure_and_replays_without_a_new_call(tmp_path: Path) -> None:
    change = make_change()
    client = FakeLLMClient(
        {"claude-haiku-4-5-20251001": RawLLMResponse(
            text="not valid json", model_id_returned="claude-haiku-4-5-20251001",
            input_tokens=10, output_tokens=2,
        )}
    )
    cache = LabelCache(tmp_path / "cache.json")

    with pytest.raises(LabelParseError):
        label_change(change, model_id="claude-haiku-4-5-20251001", client=client, cache=cache)
    with pytest.raises(LabelParseError):
        label_change(change, model_id="claude-haiku-4-5-20251001", client=client, cache=cache)

    assert len(client.calls) == 1


def test_label_change_propagates_client_errors(tmp_path: Path) -> None:
    change = make_change()
    client = FakeLLMClient({"claude-sonnet-5": LLMClientError("boom")})
    cache = LabelCache(tmp_path / "cache.json")

    with pytest.raises(LLMClientError):
        label_change(change, model_id="claude-sonnet-5", client=client, cache=cache)


def test_prompt_version_is_a_stable_constant() -> None:
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION


def test_anthropic_client_from_env_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMClientError):
        AnthropicMessagesClient.from_env()


def _fake_response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code, json=body, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


class RecordingPostSequence:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.request_bodies: list[dict] = []

    def __call__(self, url, *, timeout, headers, json):
        self.request_bodies.append(json)
        return self._responses.pop(0)


def test_anthropic_client_retries_without_temperature_on_deprecation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deprecation_error = _fake_response(
        400,
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "`temperature` is deprecated for this model.",
            },
        },
    )
    success = _fake_response(
        200,
        {
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": '{"direction": "nerf", "magnitude": "minor", "change_type": "stat", "confidence": "high"}'}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    )
    fake_post = RecordingPostSequence([deprecation_error, success])
    monkeypatch.setattr(httpx, "post", fake_post)

    client = AnthropicMessagesClient(api_key="fake-key")
    response = client.complete(model_id="claude-sonnet-5", system="sys", user="usr")

    assert response.model_id_returned == "claude-sonnet-5"
    assert len(fake_post.request_bodies) == 2
    assert "temperature" in fake_post.request_bodies[0]
    assert "temperature" not in fake_post.request_bodies[1]


def test_anthropic_client_does_not_retry_unrelated_400_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated_error = _fake_response(
        400,
        {"type": "error", "error": {"type": "invalid_request_error", "message": "model: not found"}},
    )
    fake_post = RecordingPostSequence([unrelated_error])
    monkeypatch.setattr(httpx, "post", fake_post)

    client = AnthropicMessagesClient(api_key="fake-key")
    with pytest.raises(LLMClientError):
        client.complete(model_id="claude-sonnet-5", system="sys", user="usr")

    assert len(fake_post.request_bodies) == 1
