# Engineering Improvement Dashboard

**Generated:** 2026-07-08 17:56:00 UTC
**Git:** `bf6a6f2` on `main`
**Problems:** 10 | **Conditions:** 3

## Overview

| Metric | Value |
|---|---|
| Patch success rate | 29.6% |
| Total patches attempted | 301 |
| Successful patches | 89 |
| Rolled back | 167 |
| Escalated | 45 |
| Avg confidence score | 0.83 |
| Avg lines changed per patch | 43.3 |
| LLM estimated cost | $5.84 |
| LLM total calls | 301 |
| Patch memory size | 301 |
| Unique error categories | 11 |
| Failure rate | 73.1% |
| Avg duration | 248.5s |
| First-pass success rate | 51.5% |
| Avg attempts per job | 2.16 |

## Cascade Level Distribution (Phase 4)

| Level | Hits | Description |
|---|---|---|
| level0_rule | 23 | Deterministic rules (regex) |
| level3_memory | 137 | Patch memory hit |
| level4_llm | 98 | LLM classification |
| level5_escalation | 43 | Escalated to human |

## Template Quality by Architecture

| Architecture | Generations | Passes | Failures | Error Rate | Avg Metric |
|---|---|---|---|---|---|
| distilbert | 31 | 1 | 28 | 90.3% | 0.0942 |
| efficientnet | 16 | 0 | 16 | 100.0% | 0.0000 |
| lightgbm | 111 | 56 | 51 | 45.9% | 3313.9509 |
| unknown | 5 | 0 | 0 | 0.0% | -- |

## Forge Reliability

| Architecture | Selections |
|---|---|
| distilbert | 31 |
| efficientnet | 16 |
| lightgbm | 111 |
| unknown | 5 |

## Dissect Effectiveness by Error Category

| Category | Occurrences | Success Rate |
|---|---|---|
| convergence_failure | 12 | 66.7% |
| dtype_mismatch | 50 | 8.0% |
| empty_dataset | 4 | 0.0% |
| encoding_error | 29 | 62.1% |
| import_error | 6 | 83.3% |
| missing_column | 100 | 32.0% |
| nan_propagation | 4 | 0.0% |
| novel_error | 51 | 35.3% |
| permission_error | 12 | 8.3% |
| pickle_version_mismatch | 16 | 0.0% |
| syntax_error | 17 | 17.6% |

## Patch Attempt Distribution (Phase 6)

| Attempt Number | Count |
|---|---|
| 1 | 138 |
| 2 | 66 |
| 3 | 97 |

## LLM Usage (Phase 5)

- **Total calls:** 301
- **Input tokens:** 834,000
- **Output tokens:** 222,400
- **Estimated cost:** $5.84
- **Regex fallback rate:** 7.6%
- **Avg cost per call:** $0.019395

| Agent | Calls |
|---|---|
| dissect | 278 |

## Knowledge Progress (Phase 7)

- **Patch memory entries:** 301
- **Unique patches:** 256
- **Unique error categories:** 11
- **Total jobs in patch log:** 68
- **Avg patches per job:** 4.4
- **Max patches per job:** 15
- **Growth rate:** 1.7 patches/hour
- **Oldest entry:** 2026-07-01T12:30:38.923942+00:00
- **Newest entry:** 2026-07-08T17:44:25.602860+00:00

## Performance Summary (Phase 8)

- **Average total duration:** 248.5s
- **Median total duration:** 108.4s
- **Total problems profiled:** 52

## Root Cause Analysis (Phase 2)

- **Total failures:** 38/52 (73.1%)

| Error Category | Failures |
|---|---|
| convergence_failure | 4 |
| dtype_mismatch | 46 |
| empty_dataset | 4 |
| encoding_error | 11 |
| import_error | 1 |
| missing_column | 68 |
| nan_propagation | 4 |
| novel_error | 33 |
| permission_error | 11 |
| pickle_version_mismatch | 16 |
| syntax_error | 14 |

| Architecture | Failures |
|---|---|
| distilbert | 28 |
| efficientnet | 16 |
| lightgbm | 51 |

### Common Failure Patterns
- KeyError: 103x
- TypeError: 50x
- NameError: 42x
- RuntimeError: 26x
- AttributeError: 24x

### Recommendations
- Prioritize fixing lightgbm templates (51 failures)
- Focus Dissect training on missing_column category (68 unresolved failures)
- Add static prevention rule for 'KeyError' (103 occurrences)

## Benchmark Comparison (Phase 9)

- **Condition B (no Dissect):** 50 problems
- **Condition C (with Dissect):** 50 problems
- **Pass rate delta:** +18.0pp
- **Avg metric delta:** -4562.2900
- **Avg duration delta:** +151.63s

### Per-Problem Comparison

| Problem | B Status | C Status | B Metric | C Metric | Delta |
|---|---|---|---|---|---|
| TR11 | crash | escalate ✗ | -- | -- | -- |
| TR12 | crash | escalate ✗ | -- | -- | -- |
| TC01 | pass | pass ✓ | 0.8588 | 0.8588 | +0.0000 |
| TC02 | crash | escalate ✗ | -- | -- | -- |
| TC03 | crash | pass ✓ | -- | 0.8347 | -- |
| TC04 | crash | pass ✓ | -- | 0.7835 | -- |
| TC05 | crash | escalate ✗ | -- | -- | -- |
| TC06 | crash | escalate ✗ | -- | -- | -- |
| TC07 | crash | escalate ✗ | -- | -- | -- |
| TC08 | crash | pass ✓ | -- | 0.9747 | -- |
| TC09 | pass | pass ✓ | 1.0000 | 1.0000 | +0.0000 |
| TC10 | crash | pass ✓ | -- | 0.7282 | -- |
| TC11 | pass | pass ✓ | 0.7931 | 0.7931 | +0.0000 |
| TC12 | pass | pass ✓ | 0.8072 | 0.8072 | +0.0000 |
| TC13 | crash | pass ✓ | -- | 0.4338 | -- |
| TC14 | crash | pass ✓ | -- | 0.9297 | -- |
| TC15 | crash | pass ✓ | -- | 1.0000 | -- |
| TC16 | pass | pass ✓ | 0.8929 | 0.8929 | +0.0000 |
| TC17 | pass | pass ✓ | 0.9088 | 0.9088 | +0.0000 |
| TC18 | crash | pass ✓ | -- | 0.9608 | -- |
| TC19 | crash | escalate ✗ | -- | -- | -- |
| TC20 | escalate | escalate ✗ | -- | -- | -- |
| TR01 | pass | pass ✓ | 0.4635 | 0.4635 | +0.0000 |
| TR02 | pass | pass ✓ | 56.5731 | 56.5731 | +0.0000 |
| TR03 | pass | pass ✓ | 0.6928 | 0.6928 | +0.0000 |
| TR04 | retry | retry ? | 91.9148 | 91.9148 | +0.0000 |
| TR05 | pass | pass ✓ | 3.2323 | 3.2323 | +0.0000 |
| TR06 | escalate | escalate ✗ | 68.1677 | 68.1677 | +0.0000 |
| TR07 | crash | escalate ✗ | -- | -- | -- |
| TR08 | pass | pass ✓ | 2.2255 | 2.2255 | +0.0000 |
| TR09 | escalate | escalate ✗ | 174410.4420 | 174410.4420 | +0.0000 |
| TR10 | pass | pass ✓ | 4546.1076 | 4546.1076 | +0.0000 |
| TX01 | crash | crash ✗ | -- | -- | -- |
| TX02 | crash | escalate ✗ | -- | -- | -- |
| TX03 | crash | pass ✓ | -- | 1.0000 | -- |
| TX04 | retry | retry ? | 0.6160 | 0.6160 | +0.0000 |
| TX05 | crash | escalate ✗ | -- | 0.0359 | -- |
| TX06 | crash | escalate ✗ | -- | -- | -- |
| TX07 | crash | crash ✗ | -- | -- | -- |
| TX08 | crash | escalate ✗ | -- | 0.6536 | -- |
| TX09 | crash | escalate ✗ | -- | -- | -- |
| TX10 | crash | escalate ✗ | -- | -- | -- |
| IC01 | crash | escalate ✗ | -- | -- | -- |
| IC02 | crash | escalate ✗ | -- | -- | -- |
| IC03 | crash | escalate ✗ | -- | -- | -- |
| IC04 | crash | escalate ✗ | -- | -- | -- |
| IC05 | crash | escalate ✗ | -- | -- | -- |
| IC06 | crash | escalate ✗ | -- | -- | -- |
| IC07 | crash | escalate ✗ | -- | -- | -- |
| IC08 | crash | escalate ✗ | -- | -- | -- |

### Improvements with Dissect
- Pass rate improved by 18.0% with Dissect
- Human interventions reduced: 38 → 29
- TC03: recovered from crash to pass with Dissect
- TC04: recovered from crash to pass with Dissect
- TC08: recovered from crash to pass with Dissect
- TC10: recovered from crash to pass with Dissect
- TC13: recovered from crash to pass with Dissect
- TC14: recovered from crash to pass with Dissect
- TC15: recovered from crash to pass with Dissect
- TC18: recovered from crash to pass with Dissect
- TX03: recovered from crash to pass with Dissect

### Regressions with Dissect
- Average validation metric decreased by 4562.2900

## Failure Lifecycle — LLM Elimination Pipeline (Phase 10)

| Category | Occurrences | Stage | LLM Calls | Savable | Success Rate | Recommendation |
|---|---|---|---|---|---|---|
| missing_column | 100 | FailureLifecycleStage.has_template | 100 | 100 | 32% | Convert template to deterministic rule; then add forge prevention |
| novel_error | 51 | FailureLifecycleStage.llm_only | 51 | 0 | 35% | Add to taxonomy as deterministic rule; classify patterns from patch_log |
| dtype_mismatch | 50 | FailureLifecycleStage.forge_prevented | 50 | 50 | 8% | Forge prevention active — monitor for regression |
| encoding_error | 29 | FailureLifecycleStage.forge_prevented | 29 | 29 | 62% | Forge prevention active — monitor for regression |
| syntax_error | 17 | FailureLifecycleStage.has_rule | 17 | 17 | 18% | Add forge-level prevention to eliminate LLM calls entirely |
| pickle_version_mismatch | 16 | FailureLifecycleStage.has_rule | 16 | 16 | 0% | Add forge-level prevention to eliminate LLM calls entirely |
| convergence_failure | 12 | FailureLifecycleStage.has_rule | 12 | 12 | 67% | Add forge-level prevention to eliminate LLM calls entirely |
| permission_error | 12 | FailureLifecycleStage.has_rule | 12 | 12 | 8% | Add forge-level prevention to eliminate LLM calls entirely |
| import_error | 6 | FailureLifecycleStage.has_rule | 6 | 6 | 83% | Add forge-level prevention to eliminate LLM calls entirely |
| empty_dataset | 4 | FailureLifecycleStage.has_template | 4 | 4 | 0% | Convert template to deterministic rule; then add forge prevention |
| nan_propagation | 4 | FailureLifecycleStage.has_rule | 4 | 4 | 0% | Add forge-level prevention to eliminate LLM calls entirely |

### Summary

- **Total LLM calls that could be saved if deterministic:** 250
- **Categories with forge prevention:** 2
- **Categories with deterministic rules:** 6
- **Categories with templates:** 2
- **Categories still LLM-only:** 1

---
*Report generated by Prometheus Swarm Engineering Dashboard (Phases 1-10)*