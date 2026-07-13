"""Unit tests for MissionState state machine — transitions, validation, persistence."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from contracts.state import (
    MISSION_PHASE_TRANSITIONS,
    TERMINAL_PHASES,
    SUCCESS_PHASES,
    FAILURE_PHASES,
    LEGACY_STATUS_MAP,
    MissionPhase,
    MissionState,
    FailureReport,
    RetryAttemptRecord,
    TimelineEntry,
    canonical_phase,
    validate_phase_transition,
    transition_and_save,
)


class TestMissionPhase:
    def test_all_phases_in_transition_matrix(self):
        """Every enum value must appear as a key in the transition matrix."""
        for phase in MissionPhase:
            assert (
                phase.value in MISSION_PHASE_TRANSITIONS
            ), f"{phase.value} missing from MISSION_PHASE_TRANSITIONS"

    def test_all_transition_targets_are_valid_phases(self):
        """Every transition target must be a known phase."""
        valid = {p.value for p in MissionPhase}
        for src, targets in MISSION_PHASE_TRANSITIONS.items():
            for t in targets:
                assert t in valid, f"Transition {src} -> {t}: {t} is not a valid MissionPhase"

    def test_terminal_phases_have_no_outgoing(self):
        """Terminal phases must have empty transition lists."""
        for terminal in TERMINAL_PHASES:
            assert (
                MISSION_PHASE_TRANSITIONS[terminal] == []
            ), f"Terminal phase {terminal} should have no outgoing transitions"


class TestCanonicalPhase:
    def test_known_legacy_statuses(self):
        assert canonical_phase("QUEUED") == "MISSION_CREATED"
        assert canonical_phase("SCOUT_ANALYZING") == "SCOUT_RUNNING"
        assert canonical_phase("FORGE_WORKING") == "FORGE_RUNNING"
        assert canonical_phase("DISSECT_PATCHING") == "DISSECT_RUNNING"
        assert canonical_phase("COMPLETED") == "HARBOR_COMPLETED"
        assert canonical_phase("COMPLETE") == "MISSION_PASSED"
        assert canonical_phase("ESCALATED") == "MISSION_FAILED"
        assert canonical_phase("cancelled") == "CANCELLED"
        assert canonical_phase("PASS") == "MISSION_PASSED"
        assert canonical_phase("crash") == "MISSION_FAILED"
        assert canonical_phase("timeout") == "MISSION_FAILED"

    def test_unknown_returns_raw(self):
        assert canonical_phase("BOGUS_PHASE") == "BOGUS_PHASE"

    def test_canonical_passthrough(self):
        assert canonical_phase("SCOUT_RUNNING") == "SCOUT_RUNNING"
        assert canonical_phase("MISSION_FAILED") == "MISSION_FAILED"


class TestValidateTransition:
    def test_valid_transition(self):
        validate_phase_transition("MISSION_CREATED", "SCOUT_RUNNING")

    def test_invalid_transition_raises(self):
        with pytest.raises(ValueError, match="Invalid phase transition"):
            validate_phase_transition("MISSION_CREATED", "MISSION_FAILED")

    def test_from_unknown_phase_raises(self):
        with pytest.raises(ValueError):
            validate_phase_transition("NONEXISTENT", "SCOUT_RUNNING")

    def test_to_terminal_no_outgoing(self):
        for terminal in TERMINAL_PHASES:
            targets = MISSION_PHASE_TRANSITIONS.get(terminal, [])
            assert (
                targets == []
            ), f"{terminal} should have no outgoing transitions but has {targets}"
            for target in MissionPhase:
                if terminal != target.value:
                    with pytest.raises(ValueError):
                        validate_phase_transition(terminal, target.value)

    def test_full_pipeline_happy_path(self):
        """Verify the full Scout->...->Harbor_COMPLETED path is valid."""
        path = [
            "MISSION_CREATED",
            "SCOUT_RUNNING",
            "SCOUT_COMPLETED",
            "FORGE_RUNNING",
            "FORGE_COMPLETED",
            "FURNACE_RUNNING",
            "FURNACE_COMPLETED",
            "ARBITER_RUNNING",
            "ARBITER_COMPLETED",
            "MISSION_PASSED",
            "HARBOR_DEPLOYING",
            "HARBOR_COMPLETED",
        ]
        for i in range(len(path) - 1):
            validate_phase_transition(path[i], path[i + 1])

    def test_dissect_loop_path(self):
        """FURNACE_RUNNING -> TRAINING_FAILED -> DISSECT_RUNNING -> DISSECT_COMPLETED -> FURNACE_RUNNING"""
        validate_phase_transition("FURNACE_RUNNING", "TRAINING_FAILED")
        validate_phase_transition("TRAINING_FAILED", "DISSECT_RUNNING")
        validate_phase_transition("DISSECT_RUNNING", "DISSECT_COMPLETED")
        validate_phase_transition("DISSECT_COMPLETED", "FURNACE_RUNNING")

    def test_retry_path(self):
        """ARBITER_COMPLETED -> RETRY_PENDING -> RETRY_RUNNING -> FORGE_RUNNING"""
        validate_phase_transition("ARBITER_COMPLETED", "RETRY_PENDING")
        validate_phase_transition("RETRY_PENDING", "RETRY_RUNNING")
        validate_phase_transition("RETRY_RUNNING", "FORGE_RUNNING")

    def test_cancel_from_any_non_terminal(self):
        non_terminal = [p.value for p in MissionPhase if p.value not in TERMINAL_PHASES]
        for phase in non_terminal:
            # Should not raise
            validate_phase_transition(phase, "CANCELLED")

    def test_scout_retrain_cycle(self):
        validate_phase_transition("MISSION_PASSED", "SCOUT_RETRAIN")
        validate_phase_transition("HARBOR_COMPLETED", "SCOUT_RETRAIN")
        validate_phase_transition("SCOUT_RETRAIN", "SCOUT_RUNNING")


class TestMissionStateModel:
    def test_create_default_phase(self):
        state = MissionState(job_id="test-1")
        assert state.phase == "MISSION_CREATED"
        assert state.job_id == "test-1"
        assert state.schema_version == "1"

    def test_transition_to_valid(self):
        state = MissionState(job_id="test-1")
        state.transition_to("SCOUT_RUNNING")
        assert state.phase == "SCOUT_RUNNING"
        assert "SCOUT_RUNNING" in state.phase_timestamps

    def test_transition_to_invalid_raises(self):
        state = MissionState(job_id="test-1")
        with pytest.raises(ValueError):
            state.transition_to("MISSION_FAILED")  # Can't go CREATED -> FAILED directly

    def test_is_terminal(self):
        failed = MissionState(job_id="test-1", phase="MISSION_FAILED")
        cancelled = MissionState(job_id="test-1", phase="CANCELLED")
        completed = MissionState(job_id="test-1", phase="HARBOR_COMPLETED")
        created = MissionState(job_id="test-1", phase="MISSION_CREATED")
        passed = MissionState(job_id="test-1", phase="MISSION_PASSED")
        assert failed.is_terminal
        assert cancelled.is_terminal
        assert not completed.is_terminal  # HARBOR_COMPLETED -> SCOUT_RETRAIN possible
        assert not created.is_terminal
        assert not passed.is_terminal  # PASSED -> HARBOR_DEPLOYING -> HARBOR_COMPLETED

    def test_has_retries_remaining(self):
        state = MissionState(job_id="test-1", retry_number=0, max_retries=3)
        assert state.has_retries_remaining
        state.retry_number = 3
        assert not state.has_retries_remaining

    def test_next_attempt_number(self):
        state = MissionState(job_id="test-1", retry_number=0)
        assert state.next_attempt_number == 1
        state.retry_number = 2
        assert state.next_attempt_number == 3

    def test_add_timeline(self):
        state = MissionState(job_id="test-1")
        state.add_timeline(agent="Scout", message="Analysis complete", rows=100)
        assert len(state.timeline) == 1
        entry = state.timeline[0]
        assert entry.agent == "Scout"
        assert entry.message == "Analysis complete"
        assert entry.detail == {"rows": 100}

    def test_record_failure(self):
        state = MissionState(job_id="test-1")
        failure = FailureReport(phase="FURNACE_RUNNING", exception_type="ValueError")
        state.record_failure(failure)
        assert len(state.failures) == 1

    def test_record_retry_attempt(self):
        state = MissionState(job_id="test-1")
        entry = RetryAttemptRecord(
            attempt=1,
            architecture="xgboost",
            metric_value=0.85,
            decision="RETRY",
        )
        state.record_retry_attempt(entry)
        assert state.retry_number == 1
        assert state.architecture == "xgboost"
        assert state.best_metric == 0.85

    def test_to_dict_from_dict_roundtrip(self):
        state = MissionState(job_id="roundtrip-test", phase="SCOUT_RUNNING")
        state.add_timeline(agent="Scout", message="started")
        data = state.to_dict()
        restored = MissionState.from_dict(data)
        assert restored.job_id == "roundtrip-test"
        assert restored.phase == "SCOUT_RUNNING"
        assert len(restored.timeline) == 1
        assert restored.timeline[0].agent == "Scout"

    def test_to_dict_from_dict_with_failures(self):
        state = MissionState(job_id="fail-test")
        state.record_failure(FailureReport(phase="FURNACE_RUNNING", exception_type="OOM"))
        data = state.to_dict()
        restored = MissionState.from_dict(data)
        assert len(restored.failures) == 1

    def test_to_dict_from_dict_with_retry_history(self):
        state = MissionState(job_id="retry-test")
        state.record_retry_attempt(
            RetryAttemptRecord(
                attempt=1, architecture="lightgbm", metric_value=0.9, decision="PASS"
            )
        )
        data = state.to_dict()
        restored = MissionState.from_dict(data)
        assert restored.retry_number == 1
        assert restored.best_metric == 0.9


class TestRedisPersistence:
    @pytest.mark.asyncio
    async def test_save_to_redis(self):
        mock_redis = AsyncMock()
        state = MissionState(job_id="persist-test", phase="SCOUT_RUNNING")
        await state.save_to_redis(mock_redis)

        calls = {c[0][0] for c in mock_redis.set.call_args_list}
        assert "job:persist-test:mission_state" in calls
        assert "job:persist-test:status" in calls

        # Verify mission_state is valid JSON
        mission_call = [
            c for c in mock_redis.set.call_args_list if c[0][0] == "job:persist-test:mission_state"
        ]
        raw = mission_call[0][0][1]
        assert isinstance(raw, str)
        parsed = json.loads(raw)
        assert parsed["job_id"] == "persist-test"
        assert parsed["phase"] == "SCOUT_RUNNING"

    @pytest.mark.asyncio
    async def test_load_from_redis_found(self):
        mock_redis = AsyncMock()
        expected = MissionState(job_id="load-test", phase="FORGE_RUNNING")
        mock_redis.get.return_value = expected.model_dump_json()

        loaded = await MissionState.load_from_redis(mock_redis, "load-test")
        assert loaded is not None
        assert loaded.job_id == "load-test"
        assert loaded.phase == "FORGE_RUNNING"

    @pytest.mark.asyncio
    async def test_load_from_redis_not_found(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        loaded = await MissionState.load_from_redis(mock_redis, "no-such-job")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_from_redis_fallback_to_legacy_status(self):
        """When mission_state key doesn't exist, fall back to legacy status key."""
        mock_redis = AsyncMock()

        async def mock_get(key):
            key_str = key.decode() if isinstance(key, bytes) else key
            if key_str == "job:legacy-test:status":
                return "COMPLETED"
            return None

        mock_redis.get = mock_get

        loaded = await MissionState.load_from_redis(mock_redis, "legacy-test")
        assert loaded is not None
        assert loaded.phase == "HARBOR_COMPLETED"

    @pytest.mark.asyncio
    async def test_create_or_load_creates_new(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        state = await MissionState.create_or_load(mock_redis, "new-job")
        assert state.job_id == "new-job"
        assert state.phase == "MISSION_CREATED"

    @pytest.mark.asyncio
    async def test_create_or_load_returns_existing(self):
        mock_redis = AsyncMock()
        expected = MissionState(job_id="existing-job", phase="SCOUT_COMPLETED")
        mock_redis.get.return_value = expected.model_dump_json()

        state = await MissionState.create_or_load(mock_redis, "existing-job")
        assert state.job_id == "existing-job"
        assert state.phase == "SCOUT_COMPLETED"

    @pytest.mark.asyncio
    async def test_create_or_load_with_defaults(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        state = await MissionState.create_or_load(
            mock_redis,
            "defaults-job",
            phase="MISSION_CREATED",
            max_retries=5,
        )
        assert state.job_id == "defaults-job"
        assert state.max_retries == 5


class TestTransitionAndSave:
    @pytest.mark.asyncio
    async def test_transition_and_save_new_state(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        state = await transition_and_save(
            mock_redis,
            "trans-test",
            "SCOUT_RUNNING",
            agent="Scout",
        )
        assert state.phase == "SCOUT_RUNNING"
        assert "SCOUT_RUNNING" in state.phase_timestamps
        assert len(state.timeline) == 1
        assert state.timeline[0].agent == "Scout"

    @pytest.mark.asyncio
    async def test_transition_and_save_fresh_state_any_phase(self):
        """A fresh job with no prior state can be set to any phase
        (no transition validation for first write)."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        state = await transition_and_save(
            mock_redis,
            "fresh-fail",
            "MISSION_FAILED",
            agent="System",
        )
        assert state.phase == "MISSION_FAILED"

    @pytest.mark.asyncio
    async def test_transition_and_save_existing_state(self):
        mock_redis = AsyncMock()
        existing = MissionState(job_id="trans-existing", phase="SCOUT_COMPLETED")
        mock_redis.get.return_value = existing.model_dump_json()

        state = await transition_and_save(
            mock_redis,
            "trans-existing",
            "FORGE_RUNNING",
            agent="Forge",
        )
        assert state.phase == "FORGE_RUNNING"
        assert len(state.timeline) >= 1

    @pytest.mark.asyncio
    async def test_transition_and_save_invalid_raises(self):
        mock_redis = AsyncMock()
        existing = MissionState(job_id="trans-bad", phase="MISSION_CREATED")
        mock_redis.get.return_value = existing.model_dump_json()

        with pytest.raises(ValueError, match="Invalid phase transition"):
            await transition_and_save(mock_redis, "trans-bad", "MISSION_FAILED")


class TestTerminalRollupHelpers:
    def test_terminal_phases_set(self):
        assert "MISSION_FAILED" in TERMINAL_PHASES
        assert "CANCELLED" in TERMINAL_PHASES
        assert "HARBOR_COMPLETED" not in TERMINAL_PHASES  # Can -> SCOUT_RETRAIN
        assert "MISSION_PASSED" not in TERMINAL_PHASES  # Not terminal

    def test_success_phases(self):
        assert "HARBOR_COMPLETED" in SUCCESS_PHASES
        assert "MISSION_PASSED" not in SUCCESS_PHASES  # Middle state, not final success

    def test_failure_phases(self):
        assert "MISSION_FAILED" in FAILURE_PHASES
        assert "CANCELLED" in FAILURE_PHASES

    def test_legacy_status_map_completeness(self):
        """Every canonical phase should have a forward mapping if applicable."""
        known_legacy = {
            "QUEUED",
            "SCOUT_ANALYZING",
            "FORGE_WORKING",
            "FORGE_RETRY",
            "FURNACE_TRAINING",
            "DISSECT_PATCHING",
            "ARBITER_EVALUATING",
            "COMPLETED",
            "COMPLETE",
            "PASSED",
            "PASS",
            "ESCALATED",
            "ESCALATE",
            "FAILED",
            "error",
            "crash",
            "timeout",
            "RETRY_NEEDED",
            "FURNACE_RUNNING",
            "CANCELLED",
            "cancelled",
            "UNKNOWN",
        }
        for legacy in known_legacy:
            assert legacy in LEGACY_STATUS_MAP, f"{legacy} missing from LEGACY_STATUS_MAP"
            mapped = LEGACY_STATUS_MAP[legacy]
            assert mapped in {
                p.value for p in MissionPhase
            }, f"{legacy} maps to {mapped}, which is not a valid MissionPhase"
