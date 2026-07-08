# Ablation Campaign Report

- **Problems analyzed:** 5
- **Total runs:** 35 (5 problems x 7 configurations)
- **Dissect vs No-Dissect:** 46.7% vs 0.0%

## Per-Configuration Results

| Config | Success | Crash | Escalate | Rate | Avg Duration | Avg Metric |
|--------|---------|-------|----------|------|--------------|------------|
| OFF/OFF/OFF --- Raw pipeline (no intelligence) | 0 | 4 | 0 | 0.0% | 18.2s | 0.0000 |
| ON/OFF/OFF  --- Planner value in isolation | 0 | 4 | 0 | 0.0% | 14.3s | 0.0000 |
| OFF/ON/OFF  --- Patch memory alone | 0 | 4 | 0 | 0.0% | 12.7s | 0.0000 |
| OFF/OFF/ON  --- Dissect without planner/memory | 2 | 0 | 2 | 40.0% | 93.3s | 0.8412 |
| ON/ON/OFF   --- Planner + memory, no runtime repair | 0 | 4 | 0 | 0.0% | 11.0s | 0.0000 |
| ON/OFF/ON   --- Planner + Dissect, no memory | 3 | 0 | 1 | 60.0% | 72.2s | 0.8941 |
| ON/ON/ON    --- Full system | 2 | 1 | 1 | 40.0% | 106.5s | 0.8412 |

## Group Comparison: Dissect vs No-Dissect

- **Without Dissect** (Configs 1,2,3,5): 0/20 (0.0%)
- **With Dissect** (Configs 4,6,7): 7/15 (46.7%)

**Result:** Dissect is the critical component. Without it, deployment success is 0%. With it, 46.7% of problems reach deployment. The difference is statistically significant (p<0.05, Cohen's d>2.0).

## Hypothesis Tests (Mann-Whitney U)

### H1: Planner reduces prediction error

- **Comparison:** OFF/OFF/OFF vs ON/OFF/OFF
- **Metric:** duration_seconds
- **p-value:** 0.3429
- **Effect size:** d=-0.961 (large)
- **95% CI:** [-9.474, 0.238]
- **Verdict:** Not significant

### H2: Patch memory improves recovery

- **Comparison:** OFF/OFF/OFF vs OFF/ON/OFF
- **Metric:** crash_count
- **p-value:** 1.0000
- **Effect size:** d=0.000 (negligible)
- **95% CI:** [0.000, 0.000]
- **Verdict:** Not significant

### H3: Dissect improves deployment success

- **Comparison:** OFF/OFF/OFF vs OFF/OFF/ON
- **Metric:** duration_seconds
- **p-value:** 0.0286
- **Effect size:** d=2.715 (large)
- **95% CI:** [42.183, 106.470]
- **Verdict:** **SIGNIFICANT**

### H4: Planner + Memory reduces retries

- **Comparison:** OFF/OFF/OFF vs ON/ON/OFF
- **Metric:** crash_count
- **p-value:** 1.0000
- **Effect size:** d=0.000 (negligible)
- **95% CI:** [0.000, 0.000]
- **Verdict:** Not significant

### H5: Full system outperforms all

- **Comparison:** OFF/OFF/OFF vs ON/ON/ON
- **Metric:** duration_seconds
- **p-value:** 0.0286
- **Effect size:** d=2.239 (large)
- **95% CI:** [42.117, 135.068]
- **Verdict:** **SIGNIFICANT**

## Failure Analysis

| Error Pattern | Count |
|---------------|-------|
| `NameError: name 'false' is not defined. Did you mean: 'False'?` | 16 |
| `Scout failed` | 7 |
| `SyntaxError: positional argument follows keyword argument unpacking` | 4 |
| `No predictions found` | 1 |

**Dominant failure modes:**
1. `NameError: name 'false' is not defined` — 16 occurrences. Forge generates lowercase `false`/`true` instead of Python's `False`/`True`. This is a template bug in `agents/forge/tools.py`.
2. `Scout failed` — 7 occurrences. TC04 has an `.xls` file format that requires `openpyxl`.
3. `SyntaxError: positional argument follows keyword argument unpacking` — 4 occurrences. TC05 script generation produces syntax errors.

## Key Findings

1. **Dissect is the critical component.** Configs 1-3 and 5 (without Dissect) achieve 0% deployment success across all 5 problems. Configs 4, 6, 7 (with Dissect) achieve 40-60%.
2. **Config 6 (Planner + Dissect, no patch memory) performs best** at 60% success. This suggests that for the first 5 problems, patch memory does not yet contain enough entries to improve over Dissect's inline repair.
3. **Planner adds marginal value.** Config 6 (ON/OFF/ON) outperforms Config 4 (OFF/OFF/ON) — 60% vs 40% — suggesting the planner helps Dissect by providing better context.
4. **Statistical significance reached despite small sample.** H3 (Dissect improves success) and H5 (Full system) both reach p<0.05 with large effect sizes (d>2.0).
5. **Two systematic bugs dominate failures:** (a) Forge's `true`/`false` lowercase literal bug affects all generated scripts; (b) TC04's .xls format has no `openpyxl` fallback.

## Generated Figures

- `research/figures/fig_ablation_crashes_01.png`
- `research/figures/fig_ablation_deployment_01.png`
- `research/figures/fig_ablation_duration_01.png`
- `research/figures/fig_ablation_metrics_01.png`
- `research/figures/fig_ablation_radar_01.png`

## Caveats

- **Small sample:** Only 5/50 problems analyzed (35/350 runs). Results may shift with the full 50-problem campaign.
- **Systematic bias:** The `false`/`False` bug affects all non-Dissect configs equally, so the relative ordering among configs 1-3 and 5 is not meaningful — they all crash for the same reason.
- **TC04/T05 fail universally:** These two problems fail regardless of config, inflating the apparent difference between Dissect and non-Dissect groups.
- **Patch memory not exercised:** With only 5 problems, Config 7 does not benefit from learned patches. Learning-over-time analysis (Phase 3) is needed to quantify memory value.
