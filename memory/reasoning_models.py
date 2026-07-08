"""Pydantic models for engineering reasoning produced by Scout and planning by Forge."""

from pydantic import BaseModel, Field


class EngineeringDecision(BaseModel):
    title: str = Field(..., description="Short name of the decision, e.g. 'Handle Missing Values'")
    rationale: str = Field(
        ..., description="Why this decision was made, e.g. '12% missing in 3 numerical features'"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in this decision (0.0 to 1.0)"
    )
    alternatives: list[str] = Field(
        default_factory=list, description="Other viable options considered"
    )
    selected: str = Field(..., description="The chosen option")


class EngineeringReasoning(BaseModel):
    problem_type: EngineeringDecision
    data_quality: EngineeringDecision
    leakage: EngineeringDecision
    preprocessing: EngineeringDecision
    imbalance: EngineeringDecision | None = None
    architecture: EngineeringDecision
    validation: EngineeringDecision
    risks: list[str] = Field(default_factory=list, description="Identified training risks")
    overall_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence in the analysis"
    )


# ---------------------------------------------------------------------------
# Stage 2: Forge Engineering Planner
# ---------------------------------------------------------------------------


class ArchitectureProposal(BaseModel):
    name: str = Field(..., description="Architecture name, e.g. 'lightgbm'")
    pros: list[str] = Field(default_factory=list, description="Advantages of this architecture")
    cons: list[str] = Field(default_factory=list, description="Disadvantages of this architecture")
    expected_training_minutes: int = Field(
        ..., description="Estimated wall-clock training time in minutes"
    )
    expected_ram_mb: int = Field(..., description="Estimated peak memory usage in MB")
    expected_metric_range: list[float] | None = Field(
        default=None, description="Expected primary metric range [low, high]"
    )
    reason_for_selection: str = Field(..., description="Why this architecture was chosen")


class PreprocessingStep(BaseModel):
    name: str = Field(..., description="Step name, e.g. 'median_imputation_numeric'")
    rationale: str = Field(..., description="Why this step is needed")
    library: str = Field(default="sklearn", description="Library providing this step")


class HyperparameterStrategy(BaseModel):
    approach: str = Field(
        ..., description="Tuning approach: 'optuna_bayesian', 'grid_search', or 'manual'"
    )
    max_trials: int = Field(..., description="Maximum Optuna trials (1 if manual)")
    early_stopping_rounds: int | None = Field(default=None, description="Early stopping patience")
    key_params_to_tune: list[str] = Field(..., description="Which hyperparameters will be tuned")


class ComputationalBudget(BaseModel):
    estimated_training_minutes: int = Field(..., description="Expected wall-clock training time")
    estimated_ram_mb: int = Field(..., description="Expected peak memory usage")
    expected_disk_mb: int = Field(..., description="Expected disk usage for checkpoints + logs")
    gpu_required: bool = Field(..., description="Whether GPU is recommended or required")


class EngineeringPlan(BaseModel):
    architecture_selected: ArchitectureProposal = Field(
        ..., description="The primary architecture chosen and why"
    )
    alternatives: list[ArchitectureProposal] = Field(
        default_factory=list, description="Alternative architectures considered"
    )
    preprocessing_pipeline: list[PreprocessingStep] = Field(
        default_factory=list, description="Preprocessing steps in order"
    )
    hyperparameter_strategy: HyperparameterStrategy = Field(
        ..., description="Hyperparameter tuning strategy"
    )
    computational_budget: ComputationalBudget = Field(
        ..., description="Expected compute resource usage"
    )
    fallback_plan: str = Field(..., description="What to try if the primary architecture fails")
    feature_engineering_notes: list[str] = Field(
        default_factory=list,
        description="Feature engineering recommendations from Scout's analysis",
    )
