"""Tests for shareable challenge bundles (issue #7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regex_rumble.bundle import (
    BUNDLE_VERSION,
    BundleError,
    ChallengeBundle,
    load_bundle,
)


def _sample() -> ChallengeBundle:
    return ChallengeBundle(
        name="ipv4-strict",
        hint="Match dotted-quad IPv4.",
        allies=("1.2.3.4", "127.0.0.1"),
        enemies=("256.1.1.1", "1.2.3"),
        goal_pattern=r"^\d{1,3}(\.\d{1,3}){3}$",
        author="Sensei",
    )


def test_round_trip_json() -> None:
    bundle = _sample()
    raw = bundle.to_json()
    decoded = ChallengeBundle.from_json(raw)
    assert decoded == bundle
    # Pretty-printed by default and stable across runs.
    assert raw == bundle.to_json()


def test_round_trip_url() -> None:
    bundle = _sample()
    url = bundle.to_url()
    assert url.startswith("regex-rumble://challenge/")
    assert ChallengeBundle.from_url(url) == bundle


def test_write_and_read_file(tmp_path: Path) -> None:
    bundle = _sample()
    path = bundle.write_file(tmp_path / "challenge.json")
    assert path.exists()
    loaded = ChallengeBundle.read_file(path)
    assert loaded == bundle


def test_load_bundle_dispatch(tmp_path: Path) -> None:
    bundle = _sample()
    path = tmp_path / "c.json"
    bundle.write_file(path)
    assert load_bundle(path) == bundle
    assert load_bundle(str(path)) == bundle
    assert load_bundle(bundle.to_url()) == bundle
    assert load_bundle(bundle.to_json(pretty=False)) == bundle
    # https URL with embedded fragment payload.
    payload = bundle.to_url().split("/")[-1]
    assert load_bundle(f"https://example.com/x#challenge={payload}") == bundle


def test_from_dict_validation() -> None:
    with pytest.raises(BundleError):
        ChallengeBundle.from_dict({})  # missing name
    with pytest.raises(BundleError):
        ChallengeBundle.from_dict({"name": "x", "allies": "not-a-list"})
    with pytest.raises(BundleError):
        ChallengeBundle.from_dict({"name": "x", "enemies": [1, 2]})
    with pytest.raises(BundleError):
        ChallengeBundle.from_dict({"name": "x", "version": BUNDLE_VERSION + 99})


def test_from_json_invalid() -> None:
    with pytest.raises(BundleError):
        ChallengeBundle.from_json("{not json")


def test_url_payload_unknown_host() -> None:
    bundle = _sample()
    payload = bundle.to_url().split("/")[-1]
    with pytest.raises(BundleError):
        ChallengeBundle.from_url(f"regex-rumble://nope/{payload}")


def test_minimal_bundle_no_goal_no_examples() -> None:
    bundle = ChallengeBundle(name="empty")
    decoded = ChallengeBundle.from_json(bundle.to_json())
    assert decoded == bundle
    assert decoded.goal_pattern is None
    assert decoded.allies == ()
    assert decoded.enemies == ()


def test_load_bundle_rejects_empty_source() -> None:
    with pytest.raises(BundleError):
        load_bundle("   ")


def test_to_dict_is_json_serialisable() -> None:
    bundle = _sample()
    raw = json.dumps(bundle.to_dict())
    assert "ipv4-strict" in raw
