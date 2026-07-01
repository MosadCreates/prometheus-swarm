# Result JSON Schemas

## Batch Result (`research/benchmark/results/batch_N_condition_X.json`)

```json
{
  "problem_id": "string — e.g. TC01",
  "condition": "B_no_dissect | C_with_dissect",
  "status": "pass | crash | escalate",
  "job_id": "string — unique job identifier",
  "best_val_metric": "float — best validation metric (0.0 if crash)",
  "decision": "string — Arbiter decision (pass | retry | escalate) or empty if crash",
  "duration_seconds": "float — wall-clock time in seconds",
  "crash_count": "int — number of crashes encountered (Dissect patches applied)",
  "human_interventions": "int — 0 if autonomous, 1 if human intervention needed",
  "architecture": "string — model architecture used (lightgbm, xgboost, etc.)",
  "error": "string | null — error message truncated to 500 chars, null if success"
}
```

## Baseline (`research/benchmark/baseline_v{N}.json`)

```json
{
  "schema_version": "string — schema version",
  "created_at": "string — ISO 8601 timestamp",
  "condition_b": {
    "total_problems": "int",
    "passed": "int",
    "crashed": "int",
    "escalated": "int",
    "avg_metric": "float",
    "avg_duration_seconds": "float",
    "total_human_interventions": "int",
    "results": ["array of batch result objects"]
  },
  "condition_c": {
    "total_problems": "int",
    "passed": "int",
    "crashed": "int",
    "escalated": "int",
    "avg_metric": "float",
    "avg_duration_seconds": "float",
    "total_human_interventions": "int",
    "total_patches": "int",
    "results": ["array of batch result objects"]
  },
  "dissect_metrics": {
    "problems_attempted": "int — Condition C problems where crash_count > 0",
    "patches_saved": "int — problems Dissect successfully repaired",
    "confirmed_failures": "int — problems that failed despite Dissect",
    "save_rate": "float — patches_saved / problems_attempted"
  },
  "comparison": {
    "pass_rate_b": "float",
    "pass_rate_c": "float",
    "improvement_pp": "float — pass_rate_c - pass_rate_b in percentage points",
    "avg_metric_b": "float",
    "avg_metric_c": "float"
  }
}
```

## Patch Log Entry (`research/patch_log.jsonl`)

```json
{
  "patch_id": "string — UUID",
  "job_id": "string",
  "timestamp": "string — ISO 8601",
  "exception_type": "string — Python exception class name",
  "exception_message": "string",
  "error_taxonomy_category": "string — one of 11 taxonomy categories",
  "taxonomy_match_method": "regex | llm_classification",
  "repair_strategy_used": "string",
  "retrieved_similar_patches": [
    {
      "patch_id": "string",
      "similarity_score": "float",
      "category": "string",
      "outcome": "string",
      "repair_strategy": "string"
    }
  ],
  "diff_applied": "string — unified diff text",
  "lines_changed": "int",
  "sandbox_test_result": "pass | fail",
  "patch_outcome": "success | rollback | escalated",
  "confidence_score": "float — 0.0 to 1.0",
  "attempt_number": "int — 1-indexed",
  "resume_from_checkpoint": "string | null"
}
```

## Statistical Analysis (`outputs/statistical_analysis_results.json`)

```json
{
  "condition_b": {
    "count": "int",
    "mean_metric": "float",
    "median_metric": "float",
    "std_metric": "float",
    "min_metric": "float",
    "max_metric": "float"
  },
  "condition_c": {
    "count": "int",
    "mean_metric": "float",
    "median_metric": "float",
    "std_metric": "float",
    "min_metric": "float",
    "max_metric": "float"
  },
  "mann_whitney_u": {
    "statistic": "float",
    "p_value": "float",
    "significant": "bool (p < 0.05)"
  },
  "mcnemar": {
    "statistic": "float",
    "p_value": "float",
    "significant": "bool (p < 0.05)",
    "contingency_table": {
      "both_pass": "int",
      "b_only_pass": "int",
      "c_only_pass": "int",
      "both_fail": "int"
    }
  },
  "cohens_h": {
    "effect_size": "float",
    "interpretation": "small | medium | large"
  }
}
```

## Patch Log Analysis (`outputs/patch_log_analysis.json`)

```json
{
  "total_entries": "int",
  "outcome_distribution": {
    "success": "int",
    "rollback": "int",
    "escalated": "int"
  },
  "average_confidence": "float",
  "average_lines_changed": "float",
  "category_distribution": {
    "category_name": "int — count"
  },
  "match_method_distribution": {
    "regex": "int",
    "llm_classification": "int"
  }
}
```
