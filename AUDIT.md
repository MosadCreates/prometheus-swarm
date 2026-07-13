# AUDIT — Prometheus Swarm Bug Fix Sprint

**Date:** 2026-07-10
**Source:** Real run of `new-mission churn.csv` (job-830acda1)
**Purpose:** Document all 6 bugs found in the retry pipeline with file+line evidence before fixing.

---

## Bug A — No LabelEncoder in tabular training scripts

**Root cause:** LightGBM, XGBoost, and TabNet templates and f-string generators do not encode string classification targets with `LabelEncoder`. When the target column contains string values (`No`, `Yes`, etc.), training crashes with `ValueError: Unknown label type`.

**Files affected:**
- `agents/forge/templates/lightgbm_binary.py.jinja` — no target encoding
- `agents/forge/templates/lightgbm_multiclass.py.jinja` — no target encoding
- `agents/forge/templates/xgboost_binary.py.jinja` — no target encoding
- `agents/forge/templates/xgboost_multiclass.py.jinja` — no target encoding
- `agents/forge/templates/tabnet.py.jinja:52-55` — LabelEncoder for *feature* columns only, not target
- `agents/forge/tools.py:_write_lightgbm_script()` — f-string generator, no target encoding
- `agents/forge/tools.py:_write_xgboost_script()` — f-string generator, no target encoding
- `agents/forge/tools.py:_write_tabnet_script()` — f-string generator, no target encoding, features only

**Contrast:** `distilbert.py.jinja` (line 40-42) and `efficientnet.py.jinja` (line 42-44) both encode the target with `LabelEncoder` and save it in the checkpoint. Tabular paths are missing this.

**Backup module:** `training/label_normalizer.py` exists with `normalize_target()` and `normalizer_code_snippet()` but is NOT used by any generated script.

---

## Bug B — TabNet proposed but `pytorch-tabnet` not installed

**Root cause:** The architecture fallback chain can select `tabnet`, but `pytorch-tabnet` is NOT in the base Docker image (`training/base_training_image/Dockerfile`). The training container crashes with `ModuleNotFoundError: No module named 'pytorch_tabnet'`.

**Files affected:**
- `training/base_training_image/Dockerfile` — missing `pytorch-tabnet` in `pip install`
- `runtime/retry_strategy.py:_next_architecture()` (line 32-48) — calls `check_architecture_supported()` (which only checks `SUPPORTED_ARCHITECTURES` dict) but does NOT check whether the library is actually available at runtime
- `runtime/models.py:SUPPORTED_ARCHITECTURES` (line 16-22) — only a static dict, no runtime availability probe

**Gap:** `check_architecture_supported()` is a static dictionary lookup, not a runtime availability check. There is no mechanism to verify that the architecture's library is installed in the training Docker image.

---

## Bug C — `state.imbalance_strategy` never updated after crash

**Root cause:** After a Furnace crash in the retry loop (`retry_orchestrator.py:175-198`), a `RetryAttemptRecord` is created and `state.record_retry_attempt(crash_entry)` is called, but `state.imbalance_strategy` is NOT updated from `strategy.imbalance_strategy`. The next iteration calls `build_next_strategy_from_state()` with the stale `state.imbalance_strategy`, so the imbalance chain never progresses.

**Files affected:**
- `runtime/retry_orchestrator.py:175-198` — crash handling block: sets `state.architecture = strategy.architecture` but NOT `state.imbalance_strategy` or `state.optuna_trials`

**Same bug applies after successful Furnace + Arbiter RETRY** (lines 220-249): `state.record_retry_attempt(entry)` is called but `state.imbalance_strategy` is never updated. On next iteration, stale value used.

---

## Bug D — `best_metric` stays 0.0

**Root cause:** `MissionState.record_retry_attempt()` in `runtime/models.py:362-372` only updates `best_metric` when `entry.decision == "PASS"`. If all retries result in `RETRY`, `best_metric` remains 0.0 throughout, and the final summary displays 0.0000.

**Code:**
```python
def record_retry_attempt(self, entry: RetryAttemptRecord) -> None:
    ...
    if entry.decision == "PASS" and entry.metric_value > self.best_metric:
        self.best_metric = entry.metric_value
```

**Fix should be:** `best_metric = max(best_metric, metric_value)` regardless of decision, so the best metric across all attempts is tracked.

---

## Bug E — `state.imbalance_strategy` never updated after success (same root as C)

**Root cause:** Identical to Bug C. After a successful retry attempt at `retry_orchestrator.py:220-231`, the `entry` is recorded but `state.imbalance_strategy = strategy.imbalance_strategy` is never assigned. When the next retry iteration starts, `build_next_strategy_from_state()` at line 102-110 receives the stale `previous_imbalance`.

**File affected:** `runtime/retry_orchestrator.py:220-249`

---

## Bug F — `wait_for_dissect=False` hardcoded in retry path

**Root cause:** Furnace is called with `wait_for_dissect=False` during retry mode in `retry_orchestrator.py:462`. This means Furnace skips the WAIT state after a crash (does not `XREAD` on `dissect_output`), so Dissect never receives `CRASH_EVENT`s from retry runs. Any fixable crash during retry guarantees a cascade failure.

**Files affected:**
- `runtime/retry_orchestrator.py:462` — `wait_for_dissect=False` in `_run_furnace_with_retry()`
- `prometheus/cli/mission/controller.py:414` — `wait_for_dissect=False` in initial run (separate concern)
- `agents/furnace/agent.py:657-660` — WAIT state skipped when `wait_for_dissect=False`

**Design implication:** During retry, Furnace needs `wait_for_dissect=True` so Dissect can patch crashes. But a separate mechanism is needed to distinguish "I crashed and need patching" (go to Dissect) from "I finished training but metric was bad" (go to Arbiter then retry Forge).

---

## Summary Table

| Bug | Description | Primary File | Line(s) | Type |
|-----|-------------|-------------|---------|------|
| A | No LabelEncoder in tabular training scripts | `agents/forge/templates/*.py.jinja` | All target usage | Missing feature |
| B | TabNet proposed but `pytorch-tabnet` not installed | `training/base_training_image/Dockerfile` | N/A | Docker gap |
| C | `state.imbalance_strategy` not updated after crash | `runtime/retry_orchestrator.py` | 175-198 | State leak |
| D | `best_metric` stays 0.0 | `runtime/models.py` | 368 | Wrong logic |
| E | `state.imbalance_strategy` not updated after RETRY | `runtime/retry_orchestrator.py` | 220-249 | State leak |
| F | `wait_for_dissect=False` during retry | `runtime/retry_orchestrator.py` | 462 | Design gap |
