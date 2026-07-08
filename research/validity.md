# Threats to Validity

Planned before the experimental campaign, following standard experimental
research methodology (Wohlin et al., "Experimentation in Software Engineering").

---

## Internal Validity

Does the experimental design allow causal conclusions?

### Threat: Maturation effects in the learning-over-time experiment

Running 30 consecutive jobs on the same dataset may improve Planner accuracy
because the ChromaDB experience collection grows, not because the Planner
itself adapts. Both mechanisms are outcomes of the system's design, but if
ChromaDB is disabled (ablation), the Planner should not improve.

**Mitigation:** The ablation study isolates the Planner from ChromaDB history
(configuration 2: Planner ON, Patch Memory OFF, Dissect OFF). If Planner
accuracy still improves without ChromaDB, maturation is present.

### Threat: Confounding between Dissect and Patch Memory

Dissect uses ChromaDB (patch_memory) to retrieve similar past patches.
Improvements attributed to Dissect may actually be from the memory retrieval.

**Mitigation:** The ablation toggles DISABLE_PATCH_MEMORY and DISABLE_DISSECT
independently. Configurations 4 (OFF/OFF/ON) vs 6 (ON/OFF/ON) isolate
memory contribution from the LLM-based repair contribution.

### Threat: Test set leakage across runs

The same 50 problems are reused across all 7 ablation configurations.
If later runs see the same test set, Forge or Dissect could "learn" the
test distribution rather than generalising.

**Mitigation:** Each ablation run uses a fresh job_id and fresh Redis
namespace. ChromaDB is the only persistent store. The ablation toggles
also disable ChromaDB writes when DISABLE_PATCH_MEMORY is True.

---

## External Validity

Can the results generalise beyond the experimental setup?

### Threat: Dataset diversity

The benchmark includes 50 datasets across 5 domains (binary classification,
multi-class, regression, NLP, vision), but all are public, curated benchmarks.
Real-world ML deployments involve messier data, proprietary formats, and
domain-specific preprocessing.

**Mitigation:** The stress test (Phase 4) injects real-world data quality
issues (corrupted CSV, missing columns, NaN explosion, schema drift) into
the same datasets, testing whether the system handles realistic data
problems.

### Threat: Single LLM provider

All agents use Claude Sonnet (claude-sonnet-4-6) via Anthropic. Results
may not generalise to other LLM providers (GPT-4, Gemini) or models.

**Mitigation:** The architecture loads the model name from ANTHROPIC_MODEL
env var; swapping models requires no code change. Reported with each
experiment result.

### Threat: Single hardware configuration

All experiments run on a single Windows 11 machine with a local Docker
daemon. GPU availability, RAM constraints, and network latency are
specific to this setup.

**Mitigation:** The scalability experiment (concurrency) tests the system
under load, providing some evidence of behaviour beyond single-job runs.

---

## Construct Validity

Do the metrics measure what they claim to measure?

### Threat: Deployment success as the primary metric

"Deployment success" is defined as Arbiter issuing EVALUATION_PASS followed
by Harbor deploying a serving endpoint. This counts a model that passes a
fixed threshold as "successful," but does not measure actual prediction
quality on future unseen data.

**Mitigation:** We report both deployment success rate and the primary
metric value (AUC-ROC, F1, RMSE) separately, so reviewers can assess
whether "successful" deployments actually produce good models.

### Threat: Prediction error conflates Planner and Scout

Planner resource estimates depend on Scout's MissionSpecification (modality,
task_type, expected architecture). If Scout misclassifies a problem, the
Planner's prediction error is inflated even though the Planner's estimation
logic is correct.

**Mitigation:** Planner calibration is reported per-architecture, per-modality
to control for Scout's upstream influence.

### Threat: Patch success rate definition

Dissect's sandbox test runs the patched script for 3 epochs. A patch that
passes the sandbox may still fail in full training (e.g., convergence failure
after epoch 10).

**Mitigation:** Sandbox success is labelled as "patch survived 3 epochs"
in patch_log.jsonl. Long-term patch viability is reflected in final
deployment success/failure.

---

## Conclusion Validity

Are the statistical conclusions justified?

### Threat: Multiple hypothesis testing

Running 7 ablation configurations × 5 research questions produces 35+
statistical comparisons. With p < 0.05, ~2 false positives are expected.

**Mitigation:** Report all p-values (not just significant ones). Use
Bonferroni correction within each research question. Report effect sizes
(Cohen's d, Cliff's Delta) alongside p-values.

### Threat: Small sample size per condition

Each ablation configuration runs 50 problems. Sub-group analyses (e.g.,
by modality) may have as few as 8 (image) or 10 (text) data points.

**Mitigation:** Mann-Whitney U test is non-parametric and valid for small
samples. Results are reported with confidence intervals (bootstrap, 5000
resamples). Sub-group analyses are flagged as exploratory.

### Threat: Non-independence of 30 repeated runs

The learning curve experiment runs 30 jobs on the same dataset. These are
not independent observations — later jobs benefit from earlier ones via
ChromaDB. Standard tests assume independence.

**Mitigation:** Use paired tests (Wilcoxon signed-rank) for comparing run
1 vs run 30. Report learning curves visually (prediction error vs run
index) as the primary evidence, with statistical test as supporting.

---

*Pre-registered: 2026-07-07*
*Last updated: 2026-07-07*
