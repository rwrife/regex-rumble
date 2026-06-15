"""Tests for the sensei attack loop."""

from __future__ import annotations

import json

import httpx
import pytest

from regex_rumble.sensei import (
    Attack,
    CannedProvider,
    MockProvider,
    OpenAIProvider,
    _parse_attacks,
    run_attack,
    select_provider,
)

# ---- canned & mock providers ----------------------------------------------


def test_canned_provider_returns_at_most_five_attacks():
    provider = CannedProvider(seed=1)
    attacks = provider.attack(r"\d+", ["123", "456"], ["abc"])
    assert 1 <= len(attacks) <= 5
    for a in attacks:
        assert a.label in ("should-match", "should-not-match")


def test_mock_provider_round_trip():
    fixed = [Attack("hi", "should-match"), Attack("!!!", "should-not-match")]
    provider = MockProvider(fixed)
    assert provider.attack("foo", [], []) == fixed


# ---- classification / scoring ---------------------------------------------


def test_run_attack_scores_xp_and_damage_correctly():
    attacks = [
        Attack("abc", "should-match"),       # \d+ won't match → miss
        Attack("123", "should-match"),       # \d+ matches → correct
        Attack("xyz", "should-not-match"),   # \d+ won't match → correct
        Attack("42", "should-not-match"),    # \d+ matches → miss
    ]
    report = run_attack(r"\d+", [], [], provider=MockProvider(attacks))
    assert report.xp == 2
    assert report.damage == 2
    assert {a.text for a in report.correct} == {"123", "xyz"}
    assert {a.text for a in report.misses} == {"abc", "42"}
    assert report.used_fallback is False


def test_run_attack_handles_invalid_pattern_gracefully():
    attacks = [Attack("anything", "should-not-match")]
    report = run_attack("[unclosed", [], [], provider=MockProvider(attacks))
    # Invalid pattern matches nothing → a should-not-match correctly "passes".
    assert report.xp == 1
    assert report.damage == 0


def test_run_attack_empty_pattern_no_explode():
    report = run_attack("", [], [], provider=MockProvider([]))
    assert report.attacks == ()
    assert report.xp == 0
    assert report.damage == 0


# ---- fallback behavior -----------------------------------------------------


class _BrokenProvider:
    name = "broken"

    def attack(self, pattern, allies, enemies):
        raise RuntimeError("network down")


def test_provider_failure_falls_back_to_canned():
    report = run_attack(r"\d+", ["12"], ["ab"], provider=_BrokenProvider())
    assert report.used_fallback is True
    assert "broken" in report.provider
    assert "canned" in report.provider
    # Canned provider should have produced *something*.
    assert len(report.attacks) >= 1


# ---- provider selection ---------------------------------------------------


def test_select_provider_no_key_returns_canned():
    provider = select_provider(env={})
    assert isinstance(provider, CannedProvider)


def test_select_provider_with_key_returns_openai():
    provider = select_provider(env={"OPENAI_API_KEY": "sk-test"})
    assert isinstance(provider, OpenAIProvider)


# ---- JSON parsing ---------------------------------------------------------


def test_parse_attacks_strict_json():
    blob = json.dumps(
        {
            "attacks": [
                {"text": "foo", "label": "should-match", "rationale": "why"},
                {"text": "bar", "label": "should-not-match"},
            ]
        }
    )
    out = _parse_attacks(blob)
    assert [a.text for a in out] == ["foo", "bar"]
    assert out[0].rationale == "why"
    assert out[1].rationale == ""


def test_parse_attacks_handles_code_fence_wrapping():
    blob = "```json\n" + json.dumps({"attacks": [{"text": "x", "label": "should-match"}]}) + "\n```"
    out = _parse_attacks(blob)
    assert len(out) == 1 and out[0].text == "x"


def test_parse_attacks_filters_bad_entries():
    blob = json.dumps(
        {
            "attacks": [
                {"text": "ok", "label": "should-match"},
                {"text": 123, "label": "should-match"},
                {"text": "bad-label", "label": "maybe"},
                "not even an object",
                {"text": "also-ok", "label": "should-not-match"},
            ]
        }
    )
    out = _parse_attacks(blob)
    assert [a.text for a in out] == ["ok", "also-ok"]


def test_parse_attacks_caps_at_max():
    items = [{"text": str(i), "label": "should-match"} for i in range(20)]
    out = _parse_attacks(json.dumps({"attacks": items}))
    assert len(out) == 5


def test_parse_attacks_returns_empty_on_garbage():
    assert _parse_attacks("not json at all") == []
    assert _parse_attacks(json.dumps({"nope": []})) == []


# ---- OpenAIProvider wire format -------------------------------------------


def test_openai_provider_posts_expected_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"attacks": [{"text": "evil", "label": "should-not-match"}]}
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    provider = OpenAIProvider(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="test-model",
        client=client,
    )
    attacks = provider.attack(r"\d+", ["1"], ["a"])

    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["authorization"] == "Bearer sk-test"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert len(captured["body"]["messages"]) == 2
    assert attacks == [Attack("evil", "should-not-match")]


def test_openai_provider_network_error_propagates_for_run_attack_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    provider = OpenAIProvider(api_key="sk-test", client=client)

    with pytest.raises(httpx.ConnectError):
        provider.attack(r"\d+", [], [])


def test_run_attack_with_failing_openai_provider_falls_back():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    provider = OpenAIProvider(api_key="sk-test", client=client)

    report = run_attack(r"\d+", ["12"], ["ab"], provider=provider)
    assert report.used_fallback is True
    assert "openai" in report.provider
