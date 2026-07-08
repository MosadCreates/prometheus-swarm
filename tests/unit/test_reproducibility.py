"""Tests for reproducibility context — gathering, recording, and display."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from memory.schemas import ReproducibilityContext


class TestReproducibilityContextModel:
    def test_default_fields(self):
        ctx = ReproducibilityContext(job_id="test-job-001")
        assert ctx.job_id == "test-job-001"
        assert ctx.reproducibility_version == "1.0"
        assert ctx.configuration_hash == ""
        assert ctx.python_version == ""

    def test_all_fields(self):
        ctx = ReproducibilityContext(
            job_id="test-job-002",
            git_commit="abc123def456",
            git_branch="main",
            has_uncommitted_changes=True,
            configuration_hash="sha256-abcdef",
            python_version="CPython 3.11.15",
            dependency_versions={"pydantic": "2.7.1", "redis": "5.0.4"},
            mission_spec_version="2.0",
            execution_plan_version="1.0",
            planner_version="1.0",
            agent_versions={"scout": "1.0", "forge": "1.0"},
            dataset_fingerprint={
                "file_path": "/data/titanic.csv",
                "exists": True,
                "size_bytes": 89123,
                "content_hash": "abc123",
            },
        )
        assert ctx.git_commit == "abc123def456"
        assert ctx.dependency_versions["pydantic"] == "2.7.1"
        assert ctx.dataset_fingerprint["content_hash"] == "abc123"

    def test_json_serializable(self):
        ctx = ReproducibilityContext(job_id="test-job-003")
        data = ctx.model_dump_json()
        parsed = json.loads(data)
        assert parsed["job_id"] == "test-job-003"
        assert parsed["reproducibility_version"] == "1.0"


class TestGatherContext:
    @pytest.mark.asyncio
    async def test_gather_basic_context(self):
        from orchestrator.reproducibility import gather_reproducibility_context

        ctx = await gather_reproducibility_context(
            job_id="test-job-004",
            dataset_path="",
        )

        assert ctx.job_id == "test-job-004"
        assert ctx.mission_spec_version == "2.0"
        assert ctx.execution_plan_version == "1.0"
        assert ctx.planner_version == "1.0"
        assert isinstance(ctx.python_version, str)
        assert len(ctx.python_version) > 0

    @pytest.mark.asyncio
    async def test_gather_git_info(self):
        from orchestrator.reproducibility import gather_reproducibility_context

        ctx = await gather_reproducibility_context(job_id="test-job-005")

        # If git is available, commit should be non-empty in a git repo
        if ctx.git_commit:
            assert len(ctx.git_commit) == 40  # full SHA

    @pytest.mark.asyncio
    async def test_gather_config_hash(self):
        from orchestrator.reproducibility import gather_reproducibility_context

        ctx = await gather_reproducibility_context(job_id="test-job-006")

        if ctx.configuration_hash:
            assert len(ctx.configuration_hash) == 16  # truncated SHA256

    @pytest.mark.asyncio
    async def test_gather_dataset_fingerprint_missing(self):
        from orchestrator.reproducibility import gather_reproducibility_context

        ctx = await gather_reproducibility_context(
            job_id="test-job-007",
            dataset_path="/nonexistent/path/data.csv",
        )

        fp = ctx.dataset_fingerprint
        assert fp.get("exists") is False

    @pytest.mark.asyncio
    async def test_gather_dataset_fingerprint_exists(self, tmp_path):
        from orchestrator.reproducibility import gather_reproducibility_context

        dataset = tmp_path / "test_data.csv"
        dataset.write_text("col1,col2\n1,2\n3,4\n5,6\n")

        ctx = await gather_reproducibility_context(
            job_id="test-job-008",
            dataset_path=str(dataset),
        )

        fp = ctx.dataset_fingerprint
        assert fp.get("exists") is True
        assert fp.get("size_bytes", 0) > 0
        assert fp.get("content_hash", "") != ""

    @pytest.mark.asyncio
    async def test_gather_never_crashes(self):
        from orchestrator.reproducibility import gather_reproducibility_context

        # Should never raise even if all internal calls fail
        with patch("orchestrator.reproducibility._git_commit", side_effect=RuntimeError("no git")):
            with patch(
                "orchestrator.reproducibility._config_hash", side_effect=OSError("no config")
            ):
                ctx = await gather_reproducibility_context(
                    job_id="test-job-009",
                    dataset_path="/definitely/does/not/exist.csv",
                )
        assert ctx.job_id == "test-job-009"
        assert ctx.git_commit == ""


class TestRecordContext:
    @pytest.mark.asyncio
    async def test_record_with_redis_client(self):
        from orchestrator.reproducibility import record_reproducibility

        redis = AsyncMock()
        redis.set_json = AsyncMock()

        ctx = ReproducibilityContext(job_id="test-job-010")

        await record_reproducibility(redis, ctx)
        assert redis.set_json.called
        args = redis.set_json.call_args[0]
        assert args[0] == "job:test-job-010:reproducibility"

    @pytest.mark.asyncio
    async def test_record_with_raw_redis(self):
        from orchestrator.reproducibility import record_reproducibility

        redis = AsyncMock()
        # Only has set(), not set_json or set_str
        redis.set = AsyncMock()
        del redis.set_json
        del redis.set_str

        ctx = ReproducibilityContext(job_id="test-job-011")

        await record_reproducibility(redis, ctx)
        assert redis.set.called

    @pytest.mark.asyncio
    async def test_record_fails_gracefully(self):
        from orchestrator.reproducibility import record_reproducibility

        redis = AsyncMock()
        redis.set_json = AsyncMock(side_effect=RuntimeError("Redis down"))

        ctx = ReproducibilityContext(job_id="test-job-012")

        # Should not raise
        await record_reproducibility(redis, ctx)


class TestDatasetFingerprint:
    def test_missing_file(self):
        from orchestrator.reproducibility import _dataset_fingerprint

        fp = _dataset_fingerprint("/nonexistent/file.csv")
        assert fp["exists"] is False

    def test_small_file(self, tmp_path):
        from orchestrator.reproducibility import _dataset_fingerprint

        dataset = tmp_path / "small.csv"
        dataset.write_text("a,b\n1,2\n3,4\n")

        fp = _dataset_fingerprint(str(dataset))
        assert fp["exists"] is True
        assert fp["size_bytes"] > 0
        assert fp["content_hash"] != ""

    def test_large_file(self, tmp_path):
        from orchestrator.reproducibility import _dataset_fingerprint

        dataset = tmp_path / "large.csv"
        content = "x,y\n" + "1,2\n" * 100_000  # ~600KB
        dataset.write_text(content)

        fp = _dataset_fingerprint(str(dataset))
        assert fp["exists"] is True
        assert fp["content_hash"] != ""
        assert fp["size_bytes"] > 500_000


class TestConfigHash:
    def test_config_hash_deterministic(self, tmp_path):
        from orchestrator.reproducibility import _config_hash

        with patch("orchestrator.reproducibility._REPO_ROOT", tmp_path):
            (tmp_path / "requirements.txt").write_text("pydantic==2.7.1\nredis==5.0.4\n")
            h1 = _config_hash()
            h2 = _config_hash()
            assert h1 == h2
            assert len(h1) == 16

    def test_config_hash_changes_on_file_change(self, tmp_path):
        from orchestrator.reproducibility import _config_hash

        with patch("orchestrator.reproducibility._REPO_ROOT", tmp_path):
            (tmp_path / ".env.example").write_text("KEY=value\n")
            h1 = _config_hash()
            (tmp_path / ".env.example").write_text("KEY=changed\n")
            h2 = _config_hash()
            assert h1 != h2


class TestDependencyVersions:
    def test_reads_pinned_versions(self, tmp_path):
        from orchestrator.reproducibility import _dependency_versions

        with patch("orchestrator.reproducibility._REPO_ROOT", tmp_path):
            (tmp_path / "requirements.txt").write_text(
                "pydantic==2.7.1\nredis==5.0.4\n# comment\nnumpy>=1.26.4,<2.0\n"
            )
            deps = _dependency_versions()
            assert deps["pydantic"] == "2.7.1"
            assert deps["redis"] == "5.0.4"
            assert "numpy" not in deps  # not pinned with ==


class TestJobQueueIntegration:
    @pytest.mark.asyncio
    async def test_record_reproducibility_in_submit(self):
        from orchestrator.job_queue import _record_reproducibility

        redis = AsyncMock()
        redis.set_json = AsyncMock()

        await _record_reproducibility(redis, "test-job-013", "/data/test.csv")

        # Should not raise even with impossible dataset path
        assert True
