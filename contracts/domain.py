"""Domain models — typed contracts that cross agent boundaries.

Every serialized object carries schema_version for forward/backward compatibility.
Every agent reads these objects, not raw dicts.
No dict access (`.get("key")`) on contracts — always `.key`.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Schema versions ──────────────────────────────────────────────────────

SCHEMA_VERSION_V1 = "1"


# ── Enums ────────────────────────────────────────────────────────────────


class CrashCategory(str, Enum):
    SHAPE_MISMATCH = "shape_mismatch"
    SPARSE_MATRIX = "sparse_matrix"
    OOM = "oom"
    CUDA_OOM = "cuda_oom"
    MISSING_COLUMN = "missing_column"
    DTYPE_MISMATCH = "dtype_mismatch"
    CONVERGENCE_FAILURE = "convergence_failure"
    IMPORT_ERROR = "import_error"
    NAN_PROPAGATION = "nan_propagation"
    CHECKPOINT_CORRUPTION = "checkpoint_corruption"
    LABEL_ENCODING = "label_encoding"
    TIMEOUT = "timeout"
    DOCKER_FAILURE = "docker_failure"
    TRAINING_EXCEPTION = "training_exception"
    UNKNOWN = "unknown"


class RepairDecision(str, Enum):
    RESUME = "resume"
    ESCALATE = "escalate"


class EvaluationDecision(str, Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    FAIL = "FAIL"
    ESCALATE = "ESCALATE"


# ── Supporting models ────────────────────────────────────────────────────


class DatasetInfo(BaseModel):
    schema_version: str = SCHEMA_VERSION_V1
    file_path: str
    num_rows: int = 0
    num_columns: int = 0
    column_types: dict[str, str] = Field(default_factory=dict)
    delimiter: str = ","

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "schema_version" not in data:
                data["schema_version"] = SCHEMA_VERSION_V1
        return data


class DataQuality(BaseModel):
    schema_version: str = SCHEMA_VERSION_V1
    class_imbalance_ratio: float | None = None
    missing_value_rate: dict[str, float] = Field(default_factory=dict)
    high_cardinality_columns: list[str] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "schema_version" not in data:
                data["schema_version"] = SCHEMA_VERSION_V1
        return data


class Constraints(BaseModel):
    schema_version: str = SCHEMA_VERSION_V1
    max_latency_ms: int | None = None
    max_model_size_mb: int | None = None
    deployment_threshold: float | None = None
    deployment_operator: str = ">"

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "schema_version" not in data:
                data["schema_version"] = SCHEMA_VERSION_V1
        return data


# ── Agent-facing domain models ──────────────────────────────────────────


class MissionBrief(BaseModel):
    """Written by Scout → Redis `job:{job_id}:mission_brief`.
    Read by Forge, Furnace, Arbiter, Harbor.
    Access fields as `.field` — never `.get("field")`.
    """

    schema_version: str = SCHEMA_VERSION_V1
    job_id: str
    problem_description: str = ""
    task_type: str = "classification"
    modality: str = "tabular"
    target_column: str | None = None
    evaluation_metric: str | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    deployment_threshold: float | None = None
    deployment_operator: str = ">"
    dataset: DatasetInfo = Field(default_factory=lambda: DatasetInfo(file_path=""))
    data_quality: DataQuality = Field(default_factory=DataQuality)
    imbalance_strategy: str = "none"
    recommended_architecture_family: str | None = None
    engineering_reasoning: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="before")
    @classmethod
    def _coerce_nested(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "schema_version" not in data:
                data["schema_version"] = SCHEMA_VERSION_V1
            for nested_key, nested_model in [
                ("constraints", Constraints),
                ("dataset", DatasetInfo),
                ("data_quality", DataQuality),
            ]:
                if nested_key in data and isinstance(data[nested_key], dict):
                    if "schema_version" not in data[nested_key]:
                        data[nested_key]["schema_version"] = SCHEMA_VERSION_V1
        return data


class MissionSpecification(BaseModel):
    """Rich mission spec — primary contract from Scout.
    Stored at `job:{job_id}:mission_spec`.
    """

    schema_version: str = "2.0"
    spec_version: str = "2.0"
    job_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    objective: dict[str, Any] = Field(default_factory=dict)
    dataset_analysis: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    leakage_analysis: dict[str, Any] = Field(default_factory=dict)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    recommended_pipeline: dict[str, Any] = Field(default_factory=dict)
    candidate_models: dict[str, Any] = Field(default_factory=dict)
    engineering_decisions: dict[str, Any] = Field(default_factory=dict)
    feature_engineering: dict[str, Any] = Field(default_factory=dict)
    outlier_strategy: str = "none"
    confidence: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)


class ScoutIntelligence(BaseModel):
    """Structured dataset intelligence from Scout — consumed by RetryStrategy.

    Every field is derived from run_eda, infer_task_type, and detect_modality.
    RetryStrategy uses these to make informed decisions instead of hardcoded
    escalation. Populated once at the start of each retry cycle and carried
    on every RetryPlan.

    Frozen — never mutated after construction.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION_V1

    # ── Task & modality ─────────────────────────────────────────────────
    task_type: str = "classification"
    modality: str = "tabular"

    # ── Dataset dimensions ──────────────────────────────────────────────
    num_rows: int = 0
    num_columns: int = 0
    categorical_columns: int = 0
    text_columns: int = 0
    image_columns: int = 0

    # ── Data quality ────────────────────────────────────────────────────
    imbalance_ratio: float | None = None  # majority/minority; None = balanced or N/A
    null_ratio: float = 0.0  # fraction of all cells that are null
    memory_estimate_mb: float = 0.0

    # ── Scout's best guess (used as starting point) ─────────────────────
    recommended_architecture: str | None = None
    recommended_imbalance_strategy: str = "none"

    @classmethod
    def from_mission_data(
        cls,
        brief: dict[str, Any] | None,
        spec: dict[str, Any] | None,
    ) -> ScoutIntelligence:
        """Build ScoutIntelligence from mission_brief and mission_spec dicts.

        Extracts all available intelligence from Scout's EDA output.
        Missing fields fall back to safe defaults — never raises.
        """
        collected: dict[str, Any] = {}

        # ── Task & modality ─────────────────────────────────────────────
        collected["task_type"] = _get_str(brief, "task_type", "classification")
        collected["modality"] = _get_str(brief, "modality", "tabular")

        # ── Dataset dimensions ──────────────────────────────────────────
        ds = brief.get("dataset", {}) if brief else {}
        collected["num_rows"] = ds.get("num_rows", 0)
        collected["num_columns"] = ds.get("num_columns", 0)

        coltypes = ds.get("column_types", {})
        cat_count = sum(1 for v in coltypes.values() if v == "categorical")
        text_count = sum(1 for v in coltypes.values() if v == "text")
        image_count = sum(1 for v in coltypes.values() if v == "image")
        collected["categorical_columns"] = cat_count
        collected["text_columns"] = text_count
        collected["image_columns"] = image_count

        # ── Data quality ────────────────────────────────────────────────
        dq = brief.get("data_quality", {}) if brief else {}
        collected["imbalance_ratio"] = dq.get("class_imbalance_ratio")

        missing_rates = dq.get("missing_value_rate", {})
        null_sum = sum(missing_rates.values())
        collected["null_ratio"] = round(null_sum / max(collected["num_columns"], 1), 4)

        # Try spec dataset_analysis for memory estimate
        da = spec.get("dataset_analysis", {}) if spec else {}
        mem_bytes = da.get("memory_usage_bytes", 0) or 0
        collected["memory_estimate_mb"] = round(mem_bytes / (1024 * 1024), 2)

        # ── Scout recommendations ───────────────────────────────────────
        pipeline = spec.get("recommended_pipeline", {}) if spec else {}
        collected["recommended_architecture"] = pipeline.get("architecture")
        collected["recommended_imbalance_strategy"] = _get_str(brief, "imbalance_strategy", "none")

        return cls(**collected)


def _get_str(d: dict[str, Any] | None, key: str, default: str) -> str:
    """Safely extract a string value from a dict."""
    if d is None:
        return default
    val = d.get(key)
    return str(val) if val is not None else default


class RetryPlan(BaseModel):
    """Immutable retry decision — written by RetryEngine, consumed by Forge.
    Never accessed as a dict. Always as `.field`.
    Never mutated after creation — treated as immutable.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION_V1
    attempt: int
    max_attempts: int = 4
    architecture: str
    imbalance_strategy: str = "none"
    num_trials: int = 30
    previous_metric_value: float = 0.0
    previous_metric_name: str = "auc_roc"
    rationale: str = ""
    feature_engineering_level: str = "basic"
    output_dir: str = ""
    capable_architectures: list[str] = Field(default_factory=list)
    search_space: dict[str, Any] | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scout_intelligence: ScoutIntelligence | None = None

    @model_validator(mode="before")
    @classmethod
    def _backward_compat(cls, data: Any) -> Any:
        """Map optuna_trials → num_trials for backward compatibility."""
        if isinstance(data, dict):
            if "optuna_trials" in data and "num_trials" not in data:
                data["num_trials"] = data.pop("optuna_trials")
        return data

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryPlan:
        return cls.model_validate(data)


class TrainingPlan(BaseModel):
    """What Forge tells Furnace to execute."""

    schema_version: str = SCHEMA_VERSION_V1
    job_id: str
    retry_attempt: int = 0
    architecture: str
    imbalance_strategy: str = "none"
    optuna_trials: int = 30
    feature_engineering_level: str = "basic"
    script_path: str
    output_dir: str
    search_space_json: str | None = None
    checkpoint_path: str | None = None
    metric_name: str = "auc_roc"
    deployment_threshold: float | None = None


class CrashEvent(BaseModel):
    """Published by Furnace on CRASH_EVENT stream — consumed by Dissect."""

    schema_version: str = SCHEMA_VERSION_V1
    job_id: str
    script_path: str
    container_name: str = ""
    exit_code: int = -1
    exception_type: str
    exception_message: str
    category: str = "training_exception"
    traceback: str = ""
    container_logs: str = ""
    last_checkpoint_path: str | None = None
    epoch_at_crash: int = 0
    current_trial: int = 0
    crash_attempt_number: int = 1
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RepairResult(BaseModel):
    """Structured repair result — Dissect returns one of these on every exit path.

    Furnace consumes this from the dissect_output stream. The fields let Furnace
    decide whether to resume training, which script to use, and why a patch failed.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION_V1
    job_id: str
    patch_id: str = ""

    # ── Decision fields ───────────────────────────────────────────────────
    status: str = "resume"  # "resume" | "escalate" | "skip"
    resume_allowed: bool = True
    patched_script_path: str = ""
    resume_from_checkpoint: str | None = None

    # ── Sandbox result ────────────────────────────────────────────────────
    sandbox_passed: bool = False
    sandbox_output: str = ""

    # ── Attempt tracking ──────────────────────────────────────────────────
    attempt: int = 0
    message: str = ""

    # ── Backward compat ───────────────────────────────────────────────────
    decision: str = "resume"  # kept for legacy consumers
    escalation_reason: str = ""
    epoch_count: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="before")
    @classmethod
    def _backward_compat(cls, data: Any) -> Any:
        """Map legacy fields to new structure."""
        if isinstance(data, dict):
            # Map legacy `decision` to `status`
            if "decision" in data and "status" not in data:
                data["status"] = data["decision"]
            # Map legacy `attempt_number` to `attempt`
            if "attempt_number" in data and "attempt" not in data:
                data["attempt"] = data.pop("attempt_number")
        return data


class TrainingResult(BaseModel):
    """Published by Furnace on TRAINING_COMPLETE — consumed by Arbiter."""

    schema_version: str = SCHEMA_VERSION_V1
    job_id: str
    checkpoint_path: str
    metrics_path: str = ""
    best_metric: float = 0.0
    best_val_metric: float = 0.0
    metric_name: str = "auc_roc"
    training_time: float = 0.0
    total_epochs: int = 1
    total_trials: int = 1
    total_crashes_recovered: int = 0
    artifact_directory: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EvaluationResult(BaseModel):
    """Published by Arbiter on arbiter_output stream — consumed by Harbor / Orchestrator."""

    schema_version: str = SCHEMA_VERSION_V1
    decision: str  # "PASS" | "RETRY" | "FAIL" | "ESCALATE"
    job_id: str
    eval_report_path: str = ""
    primary_metric: str = "auc_roc"
    primary_metric_value: float = 0.0
    threshold: float | None = None
    reason: str = ""
    all_metrics: dict[str, float] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Preprocessing Contract ────────────────────────────────────────────


class PreprocessingStep(BaseModel):
    """A single step in the preprocessing pipeline."""

    name: str = ""
    step_type: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class PreprocessingContract(BaseModel):
    """Single source of truth for all preprocessing metadata.

    Written by Harbor's export step → `preprocessing_contract.json`.
    Read by:
      - ONNX export (to verify input dimensions match)
      - Generated FastAPI app (to replicate preprocessing exactly)
      - Deployment verifier (to validate all artifacts match)
      - Startup validator (to refuse serving on mismatch)

    schema_version: contract schema version
    training_framework: "lightgbm", "xgboost", "sklearn", etc.
    feature_order: ALL feature names in the exact order the model expects
    feature_types: dict of feature_name → "numeric" | "categorical"
    numeric_columns: subset of feature_order that are numeric
    categorical_columns: subset of feature_order that are categorical
    ordinal_categories: list of lists — each inner list is the category labels for one ordinal encoder column
    preprocessing_pipeline: ordered list of (name, step_type, config) for full traceability
    expected_input_shape: [None, n_features]
    expected_input_dtype: "float32"
    onnx_input_name: name of the ONNX graph input node
    onnx_input_dtype: ONNX tensor type string
    n_features: total number of features
    feature_hash: SHA256 of canonicalized feature_order string (for cross-artifact verification)
    contract_hash: SHA256 of this contract's canonical JSON (tamper evidence)
    training_version: identifier for the training run
    """

    schema_version: str = SCHEMA_VERSION_V1
    contract_version: str = "2.0"
    job_id: str = ""

    # Training metadata
    training_framework: str = ""
    training_version: str = ""

    # Feature specification
    feature_order: list[str] = Field(default_factory=list)
    feature_types: dict[str, str] = Field(default_factory=dict)
    numeric_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)

    # Categorical encoding
    ordinal_categories: list[list[str]] = Field(default_factory=list)
    ordinal_handle_unknown: str = "error"
    ordinal_unknown_value: int | None = None

    # Preprocessing pipeline trace
    preprocessing_pipeline: list[PreprocessingStep] = Field(default_factory=list)

    # ONNX contract
    expected_input_shape: list[int | None] = Field(default_factory=list)
    expected_input_dtype: str = "float32"
    onnx_input_name: str = "input"
    onnx_input_dtype: str = "tensor(float)"
    n_features: int = 0

    # Cross-artifact hashes
    feature_hash: str = ""
    contract_hash: str = ""

    def compute_feature_hash(self) -> str:
        """SHA256 of canonical feature_order string."""
        import hashlib

        canonical = "|".join(self.feature_order).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:16]

    def compute_contract_hash(self) -> str:
        """SHA256 of this contract's canonical JSON."""
        import hashlib
        import json

        raw = self.model_dump(exclude={"contract_hash"})
        canonical = json.dumps(raw, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def finalize(self) -> "PreprocessingContract":
        """Populate all computed fields and return self."""
        self.n_features = len(self.feature_order)
        self.expected_input_shape = [None, self.n_features]
        self.feature_hash = self.compute_feature_hash()
        self.contract_hash = self.compute_contract_hash()
        return self

    def verify_feature_hash(self, other_hash: str) -> bool:
        return self.compute_feature_hash() == other_hash

    def verify_contract_hash(self, other_hash: str) -> bool:
        return self.compute_contract_hash() == other_hash


# ── Backward-compatible dataclass aliases ───────────────────────────────

RetryContext = RetryPlan
