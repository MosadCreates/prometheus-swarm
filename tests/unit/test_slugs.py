from __future__ import annotations

from prometheus.utils.slugs import uuid_to_slug, format_slug, _extract_hex


def test_extract_hex_job_prefix() -> None:
    assert _extract_hex("job-a1b2c3d4") == "a1b2"


def test_extract_hex_full_uuid() -> None:
    assert _extract_hex("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d") == "a1b2"


def test_extract_hex_already_slug() -> None:
    assert _extract_hex("swift-falcon-3a9c") == "3a9c"


def test_extract_hex_short() -> None:
    assert _extract_hex("abc") == "abc"


def test_slug_format_is_three_parts() -> None:
    s = uuid_to_slug("job-a1b2c3d4")
    parts = s.split("-")
    assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}: {s}"
    assert len(parts[2]) == 4, f"Expected 4-char hex, got {len(parts[2])}"


def test_slug_deterministic() -> None:
    assert uuid_to_slug("job-a1b2c3d4") == uuid_to_slug("job-a1b2c3d4")


def test_slug_different_inputs_different_slugs() -> None:
    s1 = uuid_to_slug("job-a1b2c3d4")
    s2 = uuid_to_slug("job-ff779911")
    assert s1 != s2


def test_slug_uses_first_four_hex_chars() -> None:
    s = uuid_to_slug("job-abc12345")
    assert s.endswith("-abc1")


def test_format_slug_passthrough() -> None:
    s = uuid_to_slug("job-a1b2c3d4")
    assert format_slug(s) == s


def test_format_slug_converts_job_id() -> None:
    s = uuid_to_slug("job-a1b2c3d4")
    assert format_slug("job-a1b2c3d4") == s


def test_format_slug_latest() -> None:
    assert format_slug("latest") == "latest"
