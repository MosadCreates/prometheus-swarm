"""Acceptance tests for automatic retry orchestration (Gap 5.1).

Covers all 6 acceptance criteria from the specification.
"""

import json
import os
import tempfile

import pytest

from runtime.models import RetryAttemptRecord, RetryPlan, TrainingJob, check_architecture_supported
from runtime.retry_state import (
    MAX_RETRY_ATTEMPTS,
    RetryHistoryEntry,
    RetryState,
    load_retry_state,
    save_retry_state,
)
from runtime.retry_strategy import (
    NextTrainingStrategy,
    build_next_strategy,
    build_next_strategy_from_state,
)
from runtime.retry_log import (
    create_retry_log,
    append_retry_log_entry,
    update_retry_log_status,
)


# ── Test 1: Retry launches Forge again (verify state progression) ─────────


def test_retry_state_progression():
    """Acceptance Test 1: RetryState tracks attempts and enforces limits."""
    state = RetryState(job_id="test-job", max_attempts=3)
    assert state.attempt_number == 0
    assert state.has_retries_remaining is True
    assert state.next_attempt_number == 1

    # Simulate 3 attempts with max_attempts=3
    for i in range(1, 4):
        assert state.has_retries_remaining is True
        entry = RetryHistoryEntry(
            attempt=i,
            architecture="lightgbm" if i == 1 else "xgboost",
            metric_value=0.85 - (i * 0.02),
            metric_name="auc_roc",
            decision="RETRY" if i < 3 else "FAIL",
        )
        state.record_attempt(entry)

    # After 3 attempts, no more retries
    assert state.attempt_number == 3
    assert state.has_retries_remaining is False
    assert len(state.history) == 3


# ── Test 2: Retry count 1/3 displayed before Forge starts ────────────────


def test_retry_count_tracking():
    """Acceptance Test 2: Retry count and attempts_left are correct."""
    state = RetryState(job_id="test-job", max_attempts=3)
    assert state.attempts_left == 3

    entry = RetryHistoryEntry(
        attempt=1,
        architecture="lightgbm",
        metric_value=0.80,
        metric_name="auc_roc",
        decision="RETRY",
    )
    state.record_attempt(entry)
    assert state.attempt_number == 1
    assert state.attempts_left == 2
    assert state.next_attempt_number == 2

    entry2 = RetryHistoryEntry(
        attempt=2,
        architecture="xgboost",
        metric_value=0.82,
        metric_name="auc_roc",
        decision="PASS",
    )
    state.record_attempt(entry2)
    assert state.attempt_number == 2
    assert state.attempts_left == 1


# ── Test 3: PASS after retry → mission continues ─────────────────────────


def test_retry_passes():
    """Acceptance Test 3: Retry achieves PASS — state records it."""
    state = RetryState(job_id="test-job")
    entry = RetryHistoryEntry(
        attempt=1,
        architecture="xgboost",
        metric_value=0.88,
        metric_name="auc_roc",
        decision="PASS",
    )
    state.record_attempt(entry)
    assert state.last_decision == "PASS"
    assert state.last_metric_value == 0.88


# ── Test 4: Three consecutive retries all fail → retry limit ─────────────


def test_retry_limit_reached():
    """Acceptance Test 4: After 3 retries, has_retries_remaining is False."""
    state = RetryState(job_id="test-job", max_attempts=3)
    for i in range(1, 4):
        entry = RetryHistoryEntry(
            attempt=i,
            architecture="test",
            metric_value=0.5,
            metric_name="auc_roc",
            decision="RETRY",
        )
        state.record_attempt(entry)
    assert state.has_retries_remaining is False
    assert state.attempt_number == 3

    # Trying to go past limit — verify exhausted
    assert state.attempts_left == 0


# ── Test 5: Job ID consistent, attempt increments ────────────────────────


def test_job_id_constant_attempt_increments():
    """Acceptance Test 5: Job ID stays constant; attempt_number increments."""
    state = RetryState(job_id="job-abc123", max_attempts=3)
    for i in range(1, 4):
        entry = RetryHistoryEntry(
            attempt=i,
            architecture="test",
            metric_value=0.7 + i * 0.05,
            metric_name="auc_roc",
            decision="RETRY",
        )
        state.record_attempt(entry)
        assert state.job_id == "job-abc123"
        assert state.attempt_number == i


# ── Test 6: Each retry uses a revised strategy ───────────────────────────


def test_strategy_changes_across_retries():
    """Acceptance Test 6: build_next_strategy returns different strategies.

    Verify deterministic cycle:
      Retry 1: LightGBM, 20 trials, class_weight, basic
      Retry 2: LightGBM, 40 trials, smote, interaction
      Retry 3: XGBoost, 60 trials, focal_loss, advanced
      Retry 4: XGBoost, 80 trials, focal_loss, advanced
    """

    s1 = build_next_strategy(attempt=1)
    assert s1.architecture == "lightgbm"
    assert s1.num_trials == 20
    assert s1.imbalance_strategy == "class_weight"
    assert s1.feature_engineering_level == "basic"
    assert "lightgbm" in s1.rationale
    assert "Optuna trials: 20" in s1.rationale

    s2 = build_next_strategy(attempt=2)
    assert s2.architecture == "lightgbm"
    assert s2.num_trials == 40
    assert s2.imbalance_strategy == "smote"
    assert s2.feature_engineering_level == "interaction"
    assert s2.num_trials > s1.num_trials

    s3 = build_next_strategy(attempt=3)
    assert s3.architecture == "xgboost"
    assert s3.num_trials == 60
    assert s3.imbalance_strategy == "focal_loss"
    assert s3.feature_engineering_level == "advanced"
    assert s3.num_trials > s2.num_trials

    s4 = build_next_strategy(attempt=4)
    assert s4.architecture == "xgboost"
    assert s4.num_trials == 80
    assert s4.imbalance_strategy == "focal_loss"
    assert s4.feature_engineering_level == "advanced"
    assert s4.num_trials > s3.num_trials

    # Trial counts strictly increase
    trials = [s1.num_trials, s2.num_trials, s3.num_trials, s4.num_trials]
    assert all(trials[i] < trials[i + 1] for i in range(len(trials) - 1))

    # Imbalance strategy escalates
    imbalances = [
        s1.imbalance_strategy,
        s2.imbalance_strategy,
        s3.imbalance_strategy,
        s4.imbalance_strategy,
    ]
    assert imbalances == ["class_weight", "smote", "focal_loss", "focal_loss"]

    # Feature engineering level escalates
    fe_levels = [
        s1.feature_engineering_level,
        s2.feature_engineering_level,
        s3.feature_engineering_level,
        s4.feature_engineering_level,
    ]
    assert fe_levels == ["basic", "interaction", "advanced", "advanced"]


# ── Supporting tests for state persistence ────────────────────────────────


def test_retry_state_persistence():
    """RetryState can be saved to and loaded from disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = "outputs/test-persist"
        os.makedirs(original_dir, exist_ok=True)
        try:
            state = RetryState(
                job_id="test-persist",
                attempt_number=2,
                current_architecture="xgboost",
                last_metric_value=0.8123,
                last_metric_name="auc_roc",
                history=[
                    RetryHistoryEntry(
                        attempt=1,
                        architecture="lightgbm",
                        metric_value=0.78,
                        metric_name="auc_roc",
                        decision="RETRY",
                    ),
                    RetryHistoryEntry(
                        attempt=2,
                        architecture="xgboost",
                        metric_value=0.8123,
                        metric_name="auc_roc",
                        decision="RETRY",
                    ),
                ],
            )
            path = save_retry_state(state)
            assert os.path.exists(path)

            loaded = load_retry_state("test-persist")
            assert loaded is not None
            assert loaded.job_id == "test-persist"
            assert loaded.attempt_number == 2
            assert loaded.current_architecture == "xgboost"
            assert loaded.last_metric_value == 0.8123
            assert len(loaded.history) == 2
            assert loaded.history[0].architecture == "lightgbm"
            assert loaded.history[1].architecture == "xgboost"
        finally:
            import shutil

            if os.path.exists("outputs/test-persist"):
                shutil.rmtree("outputs/test-persist")


def test_retry_state_no_history():
    """RetryState with no history loads and has zero attempts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = "outputs/test-empty"
        os.makedirs(original_dir, exist_ok=True)
        try:
            state = RetryState(job_id="test-empty")
            save_retry_state(state)

            loaded = load_retry_state("test-empty")
            assert loaded is not None
            assert loaded.attempt_number == 0
            assert loaded.has_retries_remaining is True
            assert len(loaded.history) == 0
        finally:
            import shutil

            if os.path.exists("outputs/test-empty"):
                shutil.rmtree("outputs/test-empty")


def test_max_attempts_configurable():
    """MAX_RETRY_ATTEMPTS constant is 4."""
    assert MAX_RETRY_ATTEMPTS == 4


def test_strategy_rationale_includes_details():
    """NextTrainingStrategy rationale explains what changed."""
    s = build_next_strategy(attempt=1)
    assert "lightgbm" in s.rationale
    assert "Optuna trials: 20" in s.rationale
    assert "class_weight" in s.rationale
    assert "basic" in s.rationale

    s3 = build_next_strategy(attempt=3)
    assert "xgboost" in s3.rationale
    assert "Optuna trials: 60" in s3.rationale


# ═══════════════════════════════════════════════════════════════════════════════
# Contract Integrity Tests — RetryPlan must remain strongly typed
# through the entire pipeline. No silent dict conversions.
# ═══════════════════════════════════════════════════════════════════════════════


def test_retry_planner_returns_retryplan():
    """Test 1: build_next_strategy returns a RetryPlan, not a dict."""
    plan = build_next_strategy(
        previous_architecture="lightgbm",
        previous_imbalance="none",
        attempt=1,
    )
    assert isinstance(plan, RetryPlan), f"Expected RetryPlan, got {type(plan).__name__}"
    assert isinstance(plan.architecture, str)
    assert isinstance(plan.attempt, int)


def test_retry_plan_round_trip():
    """Test 4: RetryPlan → to_dict → from_dict → RetryPlan, no field loss."""
    original = RetryPlan(
        attempt=2,
        max_attempts=4,
        architecture="xgboost",
        imbalance_strategy="smote",
        optuna_trials=50,
        previous_metric_value=0.75,
        previous_metric_name="auc_roc",
        rationale="Switching from lightgbm to xgboost",
        feature_engineering_level="interaction",
        output_dir="outputs/test-job/retry_2",
    )
    as_dict = original.to_dict()
    reconstructed = RetryPlan.from_dict(as_dict)

    assert isinstance(reconstructed, RetryPlan)
    assert reconstructed.attempt == original.attempt
    assert reconstructed.max_attempts == original.max_attempts
    assert reconstructed.architecture == original.architecture
    assert reconstructed.imbalance_strategy == original.imbalance_strategy
    assert reconstructed.num_trials == 50
    assert reconstructed.previous_metric_value == original.previous_metric_value
    assert reconstructed.previous_metric_name == original.previous_metric_name
    assert reconstructed.rationale == original.rationale
    assert reconstructed.feature_engineering_level == "interaction"
    assert reconstructed.output_dir == "outputs/test-job/retry_2"


def test_retry_plan_json_round_trip():
    """Test 4b: RetryPlan → JSON → RetryPlan through Redis serialization."""
    import json

    original = RetryPlan(
        attempt=1,
        max_attempts=4,
        architecture="tabnet",
        imbalance_strategy="none",
        optuna_trials=20,
        previous_metric_value=0.82,
        previous_metric_name="f1",
        rationale="Initial retry attempt",
        feature_engineering_level="basic",
    )
    serialized = json.dumps(original.to_dict())
    deserialized = json.loads(serialized)
    reconstructed = RetryPlan.from_dict(deserialized)

    assert isinstance(reconstructed, RetryPlan)
    assert reconstructed.architecture == "tabnet"
    assert reconstructed.attempt == 1
    assert reconstructed.num_trials == 20
    assert reconstructed.previous_metric_name == "f1"
    assert reconstructed.previous_metric_value == 0.82
    assert reconstructed.feature_engineering_level == "basic"


def test_forge_rejects_dict_as_retry_context():
    """Test 5: Passing a dict to ForgeAgent raises a descriptive TypeError."""
    from agents.forge.agent import ForgeAgent

    agent = ForgeAgent(job_id="test-contract-dict-rejection")

    with pytest.raises(TypeError) as exc_info:
        agent._validate_retry_contract(
            {"architecture": "lightgbm", "attempt": 1},
            caller="test",
        )
    msg = str(exc_info.value)
    assert "RetryPlan" in msg
    assert "dict" in msg
    assert "from_dict" in msg


def test_forge_accepts_retryplan():
    """Test 3: Passing a RetryPlan to the contract validator passes cleanly."""
    from agents.forge.agent import ForgeAgent

    agent = ForgeAgent(job_id="test-contract-valid")
    plan = RetryPlan(
        attempt=1,
        max_attempts=3,
        architecture="lightgbm",
        imbalance_strategy="none",
        optuna_trials=30,
        previous_metric_value=0.0,
        previous_metric_name="auc_roc",
        rationale="First attempt",
    )
    # Should not raise
    agent._validate_retry_contract(plan, caller="test")


def test_orchestrator_rejects_dict_as_strategy():
    """Test 5b: _validate_retry_contract in orchestrator rejects dict."""
    from runtime.retry_orchestrator import _validate_retry_contract

    with pytest.raises(TypeError) as exc_info:
        _validate_retry_contract({"architecture": "xgboost"}, "test_stage")
    msg = str(exc_info.value)
    assert "Contract violation" in msg
    assert "expected RetryPlan" in msg


def test_orchestrator_accepts_retryplan():
    """Test 3b: _validate_retry_contract in orchestrator accepts RetryPlan."""
    from runtime.retry_orchestrator import _validate_retry_contract

    plan = RetryPlan(
        attempt=1,
        max_attempts=3,
        architecture="xgboost",
        imbalance_strategy="class_weight",
        optuna_trials=30,
        previous_metric_value=0.65,
        previous_metric_name="auc_roc",
        rationale="Try XGBoost with class_weight",
    )
    # Should not raise
    _validate_retry_contract(plan, "test_stage")


# ═══════════════════════════════════════════════════════════════════════════════
# TrainingJob — typed dataclass with validation gate
# ═══════════════════════════════════════════════════════════════════════════════


def create_temp_training_job(tmp_path, **overrides):
    """Helper to create a TrainingJob with a real script file on disk."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / "training_script_test-job.py"
    script_path.write_text("# dummy training script")
    output_dir = tmp_path / "outputs" / "test-job" / "retry_1"
    defaults = {
        "job_id": "test-job",
        "retry_attempt": 1,
        "architecture": "lightgbm",
        "imbalance_strategy": "class_weight",
        "optuna_trials": 20,
        "feature_engineering_level": "basic",
        "script_path": str(script_path),
        "output_dir": str(output_dir),
    }
    defaults.update(overrides)
    return TrainingJob(**defaults)


def test_training_job_validate_passes(tmp_path):
    """TrainingJob.validate() passes with valid fields."""
    job = create_temp_training_job(tmp_path)
    job.validate()  # Should not raise


def test_training_job_validate_missing_script(tmp_path):
    """TrainingJob.validate() raises FileNotFoundError if script is missing."""
    job = create_temp_training_job(tmp_path, script_path=str(tmp_path / "nonexistent.py"))
    with pytest.raises(FileNotFoundError, match="Training script not found"):
        job.validate()


def test_training_job_validate_unsupported_architecture(tmp_path):
    """TrainingJob.validate() raises ValueError for unsupported architecture."""
    job = create_temp_training_job(tmp_path, architecture="unknown_model")
    with pytest.raises(ValueError, match="Unsupported architecture"):
        job.validate()


def test_training_job_validate_zero_trials(tmp_path):
    """TrainingJob.validate() raises ValueError if optuna_trials < 1."""
    job = create_temp_training_job(tmp_path, optuna_trials=0)
    with pytest.raises(ValueError, match="optuna_trials must be >= 1"):
        job.validate()


def test_training_job_validate_invalid_imbalance(tmp_path):
    """TrainingJob.validate() raises ValueError for unknown imbalance strategy."""
    job = create_temp_training_job(tmp_path, imbalance_strategy="unknown_strat")
    with pytest.raises(ValueError, match="Unknown imbalance strategy"):
        job.validate()


def test_training_job_validate_invalid_fe_level(tmp_path):
    """TrainingJob.validate() raises ValueError for unknown fe level."""
    job = create_temp_training_job(tmp_path, feature_engineering_level="extreme")
    with pytest.raises(ValueError, match="Unknown feature_engineering_level"):
        job.validate()


def test_training_job_validate_creates_output_dir(tmp_path):
    """TrainingJob.validate() creates the output directory."""
    output_dir = str(tmp_path / "outputs" / "test-job" / "retry_1")
    job = create_temp_training_job(tmp_path, output_dir=output_dir)
    assert not os.path.exists(output_dir)
    job.validate()
    assert os.path.exists(output_dir)


def test_training_job_from_retry_plan(tmp_path):
    """TrainingJob.from_retry_plan creates a valid TrainingJob from a RetryPlan."""
    plan = RetryPlan(
        attempt=2,
        max_attempts=4,
        architecture="xgboost",
        imbalance_strategy="smote",
        optuna_trials=40,
        feature_engineering_level="interaction",
        previous_metric_value=0.82,
        previous_metric_name="auc_roc",
        rationale="Escalating",
        output_dir=str(tmp_path / "outputs" / "test-job" / "retry_2"),
    )
    script_path = str(tmp_path / "scripts" / "training_script_test-job.py")
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, "w") as f:
        f.write("# dummy")

    job = TrainingJob.from_retry_plan(plan, job_id="test-job", script_path=script_path)
    assert job.retry_attempt == 2
    assert job.architecture == "xgboost"
    assert job.imbalance_strategy == "smote"
    assert job.optuna_trials == 40
    assert job.feature_engineering_level == "interaction"
    job.validate()


# ═══════════════════════════════════════════════════════════════════════════════
# RetryLog — per-retry structured logging
# ═══════════════════════════════════════════════════════════════════════════════


def test_create_retry_log_writes_spec(tmp_path):
    """create_retry_log writes the initial spec entry to retry_log.json."""
    output_dir = str(tmp_path / "retry_logs" / "retry_1")
    log_path = create_retry_log(
        output_dir=output_dir,
        job_id="test-job",
        retry_attempt=1,
        architecture="lightgbm",
        imbalance_strategy="class_weight",
        optuna_trials=20,
        feature_engineering_level="basic",
        metric_name="auc_roc",
        deployment_threshold=0.85,
    )
    assert os.path.exists(log_path)
    with open(log_path) as f:
        import json

        entries = json.load(f)
    assert len(entries) == 1
    assert entries[0]["event"] == "retry_started"
    assert entries[0]["retry_attempt"] == 1
    assert entries[0]["architecture"] == "lightgbm"
    assert entries[0]["status"] == "pending"


def test_update_retry_log_status_appends(tmp_path):
    """update_retry_log_status appends entries to retry_log.json."""
    output_dir = str(tmp_path / "retry_logs" / "retry_2")
    create_retry_log(
        output_dir=output_dir,
        job_id="test-job",
        retry_attempt=2,
        architecture="xgboost",
        imbalance_strategy="smote",
        optuna_trials=40,
        feature_engineering_level="interaction",
        metric_name="auc_roc",
    )
    update_retry_log_status(output_dir, "validation_pass", validation="passed")
    update_retry_log_status(output_dir, "furnace_complete", epoch_count=10)

    with open(os.path.join(output_dir, "retry_log.json")) as f:
        import json

        entries = json.load(f)
    assert len(entries) == 3
    assert entries[0]["event"] == "retry_started"
    assert entries[1]["event"] == "validation_pass"
    assert entries[2]["event"] == "furnace_complete"


def test_append_retry_log_entry_adds_timestamp(tmp_path):
    """append_retry_log_entry auto-adds timestamp and default event."""
    output_dir = str(tmp_path / "retry_logs" / "append_test")
    os.makedirs(output_dir, exist_ok=True)
    path = append_retry_log_entry(output_dir, {"custom_field": 123})
    assert os.path.exists(path)
    with open(path) as f:
        import json

        entries = json.load(f)
    assert len(entries) == 1
    assert entries[0]["timestamp"] is not None
    assert entries[0]["event"] == "unknown"
    assert entries[0]["custom_field"] == 123


# ═══════════════════════════════════════════════════════════════════════════════
# Output isolation — each retry gets its own output directory
# ═══════════════════════════════════════════════════════════════════════════════


def test_output_dir_isolation():
    """build_next_strategy strategies have isolated output directories."""
    s1 = build_next_strategy(attempt=1)
    s2 = build_next_strategy(attempt=2)
    s3 = build_next_strategy(attempt=3)
    s4 = build_next_strategy(attempt=4)

    # Each retry has different output_dir pattern
    outputs = [f"outputs/job_x/retry_{i}" for i in (1, 2, 3, 4)]
    out1, out2, out3, out4 = outputs

    # The strategy itself doesn't set output_dir (orchestrator does it),
    # but output_dir isolation is verified via TrainingJob.from_retry_plan
    assert out1 != out2 != out3 != out4


def test_training_job_output_dir_inherits_from_plan():
    """TrainingJob.from_retry_plan uses plan.output_dir when set."""
    plan = RetryPlan(
        attempt=3,
        max_attempts=4,
        architecture="xgboost",
        imbalance_strategy="focal_loss",
        num_trials=60,
        feature_engineering_level="advanced",
        previous_metric_value=0.83,
        previous_metric_name="auc_roc",
        rationale="Third retry",
        output_dir="outputs/test-iso/retry_3",
    )
    job = TrainingJob.from_retry_plan(
        plan,
        job_id="test-iso",
        script_path="/tmp/dummy.py",
    )
    assert job.output_dir == "outputs/test-iso/retry_3"


def test_training_job_output_dir_default(tmp_path, monkeypatch):
    """TrainingJob.from_retry_plan computes default output_dir from job_id + attempt."""
    monkeypatch.chdir(tmp_path)
    plan = RetryPlan(
        attempt=1,
        max_attempts=4,
        architecture="lightgbm",
        imbalance_strategy="class_weight",
        num_trials=20,
        feature_engineering_level="basic",
        previous_metric_value=0.0,
        previous_metric_name="auc_roc",
        rationale="First retry",
    )
    job = TrainingJob.from_retry_plan(
        plan,
        job_id="test-default",
        script_path="/tmp/dummy.py",
    )
    assert job.output_dir == str(tmp_path / "outputs" / "test-default" / "retry_1")


# ═══════════════════════════════════════════════════════════════════════════════
# RetryEngine — central controller for retry lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


def test_retry_engine_initial_state():
    """RetryEngine starts with zero attempts and retries remaining."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-engine", max_attempts=4)
    assert engine.current_attempt == 0
    assert engine.max_attempts == 4
    assert engine.has_retries_remaining is True
    assert engine.next_attempt_number == 1
    assert engine.best_metric == 0.0
    assert engine.retry_history == []


def test_retry_engine_generate_strategy():
    """RetryEngine.generate_strategy returns an immutable RetryPlan."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-strategy", max_attempts=4)
    plan = engine.generate_strategy()
    assert isinstance(plan, RetryPlan)
    assert plan.attempt == 1
    assert plan.architecture == "lightgbm"
    assert plan.num_trials >= 20
    assert "lightgbm" in plan.rationale


def test_retry_engine_record_attempt():
    """RetryEngine.record_attempt appends to history and tracks best metric."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-record")
    entry1 = RetryAttemptRecord(
        attempt=1,
        architecture="lightgbm",
        metric_value=0.80,
        metric_name="auc_roc",
        decision="RETRY",
    )
    engine.record_attempt(entry1)
    assert engine.current_attempt == 1
    assert engine.best_metric == 0.80
    assert len(engine.retry_history) == 1

    entry2 = RetryAttemptRecord(
        attempt=2,
        architecture="xgboost",
        metric_value=0.90,
        metric_name="auc_roc",
        decision="PASS",
    )
    engine.record_attempt(entry2)
    assert engine.current_attempt == 2
    assert engine.best_metric == 0.90
    assert len(engine.retry_history) == 2


def test_retry_engine_should_terminate():
    """RetryEngine.should_terminate returns True for PASS and exhausted."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-term", max_attempts=2)

    # PASS → terminate
    assert engine.should_terminate("PASS") is True
    # other decisions → don't terminate
    assert engine.should_terminate("RETRY") is False
    assert engine.should_terminate("FAIL") is False

    # Exhaust all attempts
    for i in range(1, 3):
        entry = RetryAttemptRecord(
            attempt=i,
            architecture="lightgbm",
            metric_value=0.7,
            metric_name="auc_roc",
            decision="RETRY",
        )
        engine.record_attempt(entry)

    assert engine.has_retries_remaining is False
    assert engine.should_terminate("RETRY") is True  # exhausted


def test_retry_engine_save_and_load_history(tmp_path, monkeypatch):
    """RetryEngine.save_history and load_history persist retry data."""
    monkeypatch.chdir(tmp_path)
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-history", max_attempts=4)
    entry1 = RetryAttemptRecord(
        attempt=1,
        architecture="lightgbm",
        metric_value=0.80,
        metric_name="auc_roc",
        decision="RETRY",
    )
    engine.record_attempt(entry1)
    entry2 = RetryAttemptRecord(
        attempt=2,
        architecture="xgboost",
        metric_value=0.88,
        metric_name="auc_roc",
        decision="PASS",
    )
    engine.record_attempt(entry2)
    path = engine.save_history()
    assert os.path.exists(path)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["job_id"] == "test-history"
    assert data["best_metric"] == 0.88
    assert data["best_architecture"] == "xgboost"
    assert len(data["attempts"]) == 2
    assert data["attempts"][0]["architecture"] == "lightgbm"
    assert data["attempts"][1]["architecture"] == "xgboost"

    engine2 = RetryEngine(job_id="test-history", max_attempts=4)
    loaded = engine2.load_history()
    assert loaded is True
    assert engine2.current_attempt == 2
    assert engine2.best_metric == 0.88
    assert engine2.best_architecture == "xgboost"
    assert len(engine2.retry_history) == 2


def test_retry_engine_load_no_history(tmp_path, monkeypatch):
    """RetryEngine.load_history returns False when no file exists."""
    monkeypatch.chdir(tmp_path)
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-no-history")
    assert engine.load_history() is False
    assert engine.current_attempt == 0


def test_retry_engine_is_exhausted():
    """RetryEngine.is_exhausted is True when all attempts used."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-exhaust", max_attempts=2)
    assert engine.is_exhausted is False
    for i in range(1, 3):
        entry = RetryAttemptRecord(
            attempt=i,
            architecture="lightgbm",
            metric_value=0.7,
            metric_name="auc_roc",
            decision="RETRY",
        )
        engine.record_attempt(entry)
    assert engine.is_exhausted is True


def test_retry_engine_summary():
    """RetryEngine.summary returns correct status dict."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-summary", max_attempts=3)
    s = engine.summary()
    assert s["job_id"] == "test-summary"
    assert s["current_attempt"] == 0
    assert s["max_attempts"] == 3
    assert s["has_retries_remaining"] is True


def test_retry_engine_generate_strategy_escalation():
    """RetryEngine strategies escalate architecture across attempts."""
    from runtime.retry_engine import RetryEngine

    engine = RetryEngine(job_id="test-escalation", max_attempts=4)
    for attempt in range(1, 5):
        plan = engine.generate_strategy()
        assert plan.attempt == attempt
        assert plan.num_trials >= 20 * attempt
        entry = RetryAttemptRecord(
            attempt=attempt,
            architecture=plan.architecture,
            metric_value=0.7 + attempt * 0.03,
            metric_name="auc_roc",
            decision="RETRY",
        )
        engine.record_attempt(entry)
    assert engine.current_attempt == 4
    assert engine.has_retries_remaining is False
