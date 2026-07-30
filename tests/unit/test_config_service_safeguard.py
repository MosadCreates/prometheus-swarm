"""Tests for ConfigService credential guard and .env.backup safeguard."""

import logging
from pathlib import Path

import pytest

from prometheus.services.config_service import ConfigService


# ===================================================================
# .env.backup safeguard
# ===================================================================


class TestEnvBackup:
    def test_backup_created_on_set_key(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-ant-old-key\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("ANTHROPIC_API_KEY", "sk-ant-new-key")
        backup = tmp_path / ".env.backup"
        assert backup.exists()
        assert "sk-ant-old-key" in backup.read_text()

    def test_no_backup_when_env_missing(self, tmp_path: Path):
        svc = ConfigService(root=tmp_path)
        svc.set_key("ANTHROPIC_API_KEY", "sk-ant-new-key")
        backup = tmp_path / ".env.backup"
        assert not backup.exists()
        assert (tmp_path / ".env").exists()
        assert "sk-ant-new-key" in (tmp_path / ".env").read_text()

    def test_multiple_backups(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("KEY=value1\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("KEY", "value2")
        backup = tmp_path / ".env.backup"
        assert backup.exists()
        assert "value1" in backup.read_text()

        svc.set_key("KEY", "value3")
        assert backup.exists()
        assert "value2" in backup.read_text()


# ===================================================================
# Credential overwrite guard (log warning, don't block)
# ===================================================================


class TestCredentialGuard:
    def test_warning_on_credential_to_placeholder(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        caplog.set_level(logging.WARNING)
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-ant-real-key-abc123\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("ANTHROPIC_API_KEY", "exit")
        assert any("looks like a real credential" in msg for msg in caplog.messages)
        # Key IS written (guard warns but does not block)
        assert (tmp_path / ".env").read_text().strip().endswith("ANTHROPIC_API_KEY=exit")

    def test_no_warning_on_credential_to_credential(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        caplog.set_level(logging.WARNING)
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-ant-old-key\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("ANTHROPIC_API_KEY", "sk-ant-new-key")
        assert not any("looks like a real credential" in msg for msg in caplog.messages)

    def test_no_warning_on_placeholder_to_credential(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        caplog.set_level(logging.WARNING)
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=exit\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("ANTHROPIC_API_KEY", "sk-ant-real-key")
        assert not any("looks like a real credential" in msg for msg in caplog.messages)

    def test_no_warning_on_new_key(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        caplog.set_level(logging.WARNING)
        svc = ConfigService(root=tmp_path)
        svc.set_key("ANTHROPIC_API_KEY", "sk-ant-new-key")
        assert not any("looks like a real credential" in msg for msg in caplog.messages)

    def test_openai_prefix_also_guarded(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        caplog.set_level(logging.WARNING)
        env = tmp_path / ".env"
        env.write_text("OPENAI_API_KEY=sk-proj-real-key\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("OPENAI_API_KEY", "")
        assert any("looks like a real credential" in msg for msg in caplog.messages)

    def test_non_credential_key_no_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        caplog.set_level(logging.WARNING)
        env = tmp_path / ".env"
        env.write_text("ACTIVE_PROVIDER=anthropic\n")
        svc = ConfigService(root=tmp_path)
        svc.set_key("ACTIVE_PROVIDER", "openai")
        assert not any("looks like a real credential" in msg for msg in caplog.messages)


# ===================================================================
# Root injection guarantees isolation
# ===================================================================


class TestRootIsolation:
    def test_root_param_isolates_writes(self, tmp_path: Path):
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        svc = ConfigService(root=isolated)
        svc.set_key("ANTHROPIC_API_KEY", "sk-ant-test-key")
        assert not (tmp_path / ".env").exists()
        assert (isolated / ".env").exists()
        assert "sk-ant-test-key" in (isolated / ".env").read_text()

    def test_root_is_cached(self, tmp_path: Path):
        svc = ConfigService(root=tmp_path)
        assert svc.root is tmp_path
        svc.set_key("K", "v")
        assert (tmp_path / ".env").exists()
