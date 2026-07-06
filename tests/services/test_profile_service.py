import os
import tempfile
from pathlib import Path

import pytest

from prometheus.services.profile_service import ProfileService, _PROFILES_DIR


@pytest.fixture(autouse=True)
def _isolate_profiles(monkeypatch, tmp_path):
    profiles_dir = tmp_path / ".prometheus" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    def mock_profile_path(name):
        return profiles_dir / f"{name}.env"

    monkeypatch.setattr(
        _PROFILES_DIR.__class__, "parent", property(lambda s: tmp_path / ".prometheus")
    )
    monkeypatch.setattr("prometheus.services.profile_service._PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(
        "prometheus.services.profile_service._ACTIVE_FILE",
        tmp_path / ".prometheus" / "active_profile",
    )
    return profiles_dir


class TestProfileService:
    def test_list_empty(self):
        svc = ProfileService()
        assert svc.list() == []

    def test_save_and_list(self):
        svc = ProfileService()
        svc.save("test1", {"KEY": "value", "FOO": "bar"})
        assert svc.list() == ["test1"]

    def test_save_multiple(self):
        svc = ProfileService()
        svc.save("a", {"X": "1"})
        svc.save("b", {"Y": "2"})
        assert svc.list() == ["a", "b"]

    def test_current_returns_none_when_no_active(self):
        svc = ProfileService()
        assert svc.current() is None

    def test_switch_and_current(self):
        svc = ProfileService()
        svc.save("test1", {"KEY": "value"})
        assert svc.switch("test1") is True
        assert svc.current() == "test1"

    def test_switch_nonexistent(self):
        svc = ProfileService()
        assert svc.switch("nonexistent") is False

    def test_delete(self):
        svc = ProfileService()
        svc.save("test1", {"KEY": "value"})
        assert svc.delete("test1") is True
        assert svc.list() == []

    def test_delete_nonexistent(self):
        svc = ProfileService()
        assert svc.delete("nonexistent") is False

    def test_inspect(self):
        svc = ProfileService()
        svc.save("test1", {"KEY": "value", "FOO": "bar"})
        env = svc.inspect("test1")
        assert env is not None
        assert env["FOO"] == "bar"

    def test_inspect_nonexistent(self):
        svc = ProfileService()
        assert svc.inspect("nonexistent") is None

    def test_delete_clears_active(self):
        svc = ProfileService()
        svc.save("test1", {"KEY": "value"})
        svc.switch("test1")
        svc.delete("test1")
        assert svc.current() is None
