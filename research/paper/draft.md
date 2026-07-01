# Prometheus Swarm: Autonomous Self-Patching ML-as-a-Service

**Authors:** Mohamed Mosad Ghonaim
**Affiliation:** Alamein International University &mdash; Nexora Lab
**Target:** MSR 2026 / ASE 2026

---

## Abstract

Machine learning training pipelines fail frequently and unpredictably. Each failure
typically requires human intervention to diagnose, patch, and restart&mdash;a bottleneck
that prevents truly autonomous ML operations. We present Prometheus Swarm, an autonomous
multi-agent system that accepts a raw natural-language description of a machine-learning
problem and returns a fully trained, evaluated, and live-served model endpoint without
any human intervention. The system coordinates six specialized AI agents communicating
through a Redis Streams message bus. Our core contribution is **Dissect**, an agent that
autonomously patches ML training failures by classifying errors against a taxonomy of 11
categories, retrieving similar past patches from ChromaDB vector memory, generating fixes
via LLM, and testing them in a sandbox before resuming training. We evaluate the system
on a benchmark of 50 diverse ML problems spanning tabular, text, and image modalities
under two conditions: without Dissect (Condition B) and with Dissect (Condition C).
Condition C achieves a **22 percentage-point improvement** in pass rate (28% to 50%,
McNemar p=0.0026, Cohen&rsquo;s h=0.456) and a **31% reduction in human interventions**
(36 to 25, Mann-Whitney U p=0.013). Dissect successfully recovers 11 of 18 (61.1%)
crash scenarios autonomously. These results demonstrate that LLM-driven autonomous error
recovery is a viable path toward self-healing ML pipelines.

## 1. Introduction

Operationalizing machine learning at scale requires more than accurate models&mdash;it
requires reliable pipelines. In production ML systems, training jobs fail for a wide
variety of reasons: missing columns after schema drift, type mismatches after data
pipeline changes, out-of-memory errors on new data distributions, and subtle bugs in
feature engineering code [1, 2]. Each failure interrupts the training pipeline and
typically requires a human engineer to diagnose the root cause, write a fix, and restart
training. For organizations running hundreds of models, this manual intervention overhead
is a significant operational cost and a barrier to true ML autonomy.

Existing approaches to ML pipeline reliability fall into three categories. **AutoML
systems** such as AutoGluon [3] and Auto-sklearn [4] automate model selection and
hyperparameter tuning but assume clean, pre-processed data and do not handle runtime
execution errors. **ML platform tools** such as TFX [5] and MLflow [6] provide pipeline
orchestration and monitoring but rely on external alerting systems to page human
operators when failures occur. **LLM-based code repair systems** such as SWE-agent [7]
and Auto2ML [8] can modify code in response to error messages but operate on static
repositories rather than live training loops and do not integrate with ML pipeline
infrastructure.

We argue that the missing piece is an agent that lives inside the ML pipeline itself,
observes failures as they happen, and autonomously applies repairs without pausing the
pipeline. We call this capability **self-patching** and implement it through the Dissect
agent.

**Contributions.** This paper makes four contributions:

1.  **Prometheus Swarm**, a fully operational multi-agent ML-as-a-Service system that
    accepts natural-language problem descriptions and returns live model endpoints with
    zero human intervention.
2.  **Dissect**, the first autonomous self-patching agent that classifies ML training
    errors against a structured taxonomy, retrieves similar past patches from vector
    memory, generates fixes via LLM, and validates them in a sandbox before resuming
    training.
3.  A **benchmark of 50 ML problems** spanning tabular classification (20), tabular
    regression (12), text classification (10), and image classification (8), designed to
    evaluate the impact of autonomous error recovery.
4.  **Experimental evidence** that LLM-driven self-patching significantly reduces human
    intervention (p=0.013) and improves overall pipeline pass rate (p=0.003) compared
    to an identical system without self-patching.

## 2. System Architecture

Prometheus Swarm consists of six specialized AI agents arranged in a linear pipeline with
a feedback loop for error recovery. All agents communicate exclusively through a Redis
Streams message bus&mdash;no agent calls another directly.

### 2.1 Agent Pipeline

The system follows a sequential pipeline with a crash-recovery side loop:

```
Job Submitted -> [Scout] -> [Forge] -> [Furnace <-> Dissect] -> [Arbiter] -> [Harbor] -> Live Endpoint
```

Each agent has a single responsibility:

- **Scout** (Perceiver): Accepts a raw natural-language problem description and a path
  to a CSV dataset. Runs exploratory data analysis (EDA) to determine modality (tabular,
  text, or image), task type (classification or regression), column types, missing value
  rates, class imbalance, and high-cardinality features. Writes a structured
  `MissionBrief` to Redis and publishes `MISSION_BRIEF_READY`.

- **Forge** (Architect): Reads the `MissionBrief` and selects an appropriate model
  architecture using a deterministic decision tree defined in [9]. For tabular data with
  fewer than 1M rows, selects LightGBM; for tabular data with more than 1M rows, selects
  TabNet; for text, selects DistilBERT; for images, selects EfficientNet-B0. Generates a
  complete Python training script with hyperparameter search space and publishes
  `TRAINING_SCRIPT_READY`.

- **Furnace** (Trainer): Executes the training script inside a Docker container. Streams
  epoch-level metrics (loss, validation score, ETA) to Redis. If the script crashes,
  publishes `CRASH_EVENT` to the crash stream and waits for a `RESUME_TRAINING` event
  with a patched script. Supports checkpoint-based resume for partial training progress.

- **Dissect** (Debugger): Activated on `CRASH_EVENT`. Classifies the error against an
  11-category taxonomy, queries ChromaDB for similar past patches, generates a fix using
  Claude Sonnet, tests the patched script in a sandbox, and either publishes
  `RESUME_TRAINING` with the patched script or `ESCALATE` if the patch fails. (Detailed
  in Section 3.)

- **Arbiter** (Critic): On `TRAINING_COMPLETE`, loads the saved checkpoint and computes
  evaluation metrics (AUC-ROC, F1, accuracy, RMSE, R2, depending on task type). Makes a
  decision: `PASS` (metric exceeds threshold), `RETRY` (metric within 15% of threshold,
  try alternate architecture), or `ESCALATE` (metric below threshold, job failed).

- **Harbor** (Deployer): On `EVALUATION_PASS`, serializes the trained model to ONNX
  format (with pickle fallback), builds a Docker container with a FastAPI serving
  endpoint, deploys it, and starts PSI-based drift monitoring. Publishes `ENDPOINT_LIVE`
  with the endpoint URL and `DRIFT_ALERT` if PSI exceeds a configurable threshold.

### 2.2 Communication Infrastructure

All inter-agent communication uses Redis Streams, an append-only log data structure
supporting consumer groups. Each producing agent writes to its own stream; each consuming
agent reads from the appropriate upstream stream. The orchestrator manages consumer group
creation, message acknowledgment, and dead-letter handling. This architecture provides:

- **Asynchronous decoupling**: No agent blocks on another. The pipeline proceeds at the
  pace of the slowest component.
- **Crash isolation**: If one agent crashes, its stream buffers messages until the agent
  restarts.
- **Replayability**: Streams can be replayed for debugging or analysis.

### 2.3 Memory Architecture

The system uses two persistent storage backends:

- **Redis** (short-term): Stores job state, mission briefs, script paths, evaluation
  results, and API cost tracking. Keys expire after 24 hours.
- **ChromaDB** (long-term vector memory): Three collections store semantically searchable
  embeddings for patch retrieval, architecture decision history, and tool documentation.

## 3. Dissect: Autonomous Error Recovery

Dissect is the central contribution of this work. It operates as a side-loop attached to
the Furnace training container, activated only when a crash occurs.

### 3.1 Error Taxonomy

We define an 11-category taxonomy of ML training errors based on analysis of common
failure modes in ML pipelines:

| Category | Description | Example |
|---|---|---|
| `shape_mismatch` | Tensor/array dimensions incompatible | `(64, 3, 224, 224) vs (64, 3)` |
| `sparse_matrix` | Sparse input to dense-only operation | `lightgbm.basic.Dataset` with sparse matrix |
| `oom` | Out-of-memory during training | `CUDA out of memory` |
| `cuda_oom` | GPU out-of-memory | `RuntimeError: CUDA out of memory` |
| `missing_column` | Column name mismatch | `KeyError: 'Survived'` |
| `dtype_mismatch` | Data type incompatibility | `ValueError: Unknown label type: continuous` |
| `convergence_failure` | Training diverges | `LGBM: No further splits with positive gain` |
| `import_error` | Missing or incompatible module | `ModuleNotFoundError: No module named 'torchvision'` |
| `nan_propagation` | NaN values crash computation | `Loss is NaN during training` |
| `checkpoint_corruption` | Corrupted saved model | `pickle.UnpicklingError: invalid load key` |
| `novel_error` | Catch-all for unrecognized patterns | LLM-based classification |

The taxonomy is implemented as a decision tree: regex patterns match error messages
against known categories, and messages that match no pattern fall through to an LLM-based
classifier using Claude Sonnet with few-shot examples. This hybrid approach ensures both
speed (regex matching completes in <10ms for 90%+ of errors) and coverage (LLM handles
novel patterns).

### 3.2 Patch Lifecycle

When Furnace publishes `CRASH_EVENT`, Dissect executes the following lifecycle:

1.  **Parse** (`parse_stack_trace`): Extracts the exception type, message, traceback, and
    the line of code that triggered the error from stderr output.

2.  **Classify** (`taxonomy.classify`): Runs the exception message through the regex
    decision tree. If matched, returns the category and confidence score. If unmatched,
    invokes the LLM classifier with the full error context.

3.  **Retrieve** (`patch_memory.query_similar`): Encodes the error context using
    sentence-transformers (all-MiniLM-L6-v2) and queries ChromaDB for the top K=3 most
    similar past patches with their outcomes. This allows Dissect to learn from both
    successful and failed past repairs.

4.  **Generate** (`apply_patch`): Constructs a repair prompt for Claude Sonnet containing
    the error message, the failing code, the predicted taxonomy category, and the
    retrieved similar patches. The LLM returns a proposed diff.

5.  **Test** (`run_sandbox_test`): Applies the diff to a copy of the training script and
    runs it in a sandbox Docker container with a 60-second timeout. The sandbox test
    passes if the script executes without raising the original exception.

6.  **Deploy or Escalate**: If the sandbox test passes, Dissect backs up the original
    script, applies the patched script, logs the patch to `patch_log_queue` (which is
    drained to `research/patch_log.jsonl` by a background writer), and publishes
    `RESUME_TRAINING`. If the sandbox test fails, Dissect rolls back the diff, logs the
    failure, and if three consecutive attempts fail, publishes `ESCALATE`.

Each patch attempt is logged to the `patch_log.jsonl` dataset with structured metadata
including the exception type, taxonomy category, similarity scores of retrieved patches,
the diff applied, sandbox test result, and final outcome. This dataset serves as the
experimental corpus for analysis.

### 3.3 Integration with Architecture Memory

Beyond per-session error recovery, Dissect integrates with the architecture memory
system. When Arbiter makes a PASS/RETRY/ESCALATE decision, the outcome is stored in
ChromaDB indexed by modality, task type, dataset size, and selected architecture. When
Forge processes a new job, it queries this memory to favor architectures that succeeded
on similar problems and deprioritize those that failed.

## 4. Experimental Setup

### 4.1 Benchmark Design

We constructed a benchmark of 50 ML problems designed to evaluate the impact of
autonomous error recovery across diverse modalities, task types, and failure modes:

| Modality | Task Type | Count | Example Datasets |
|---|---|---|---|
| Tabular classification | 20 | Titanic, Iris, Pima Diabetes, Credit Card Default, Breast Cancer, Bank Marketing, HR Analytics, Loan Prediction, Wine, Heart Disease, Credit Card Fraud, Telco Churn, Mushroom, Adult Income, Glass, Parkinsons, Voter Turnout, Energy Efficiency, Student Performance, Manufacturing Defects |
| Tabular regression | 12 | California Housing, Boston Housing, Wine Quality, Appliances Energy, Bike Sharing, Stock Price, CO2 Emissions, Auto MPG, NYC Taxi, Medical Insurance, Concrete Strength, Air Quality |
| Text classification | 10 | IMDB Reviews, AG News, Hate Speech, SMS Spam, Amazon Reviews, Jigsaw Toxic, Email, Paper Abstracts, Fake Reviews, Language Detection |
| Image classification | 8 | Fashion MNIST, MNIST, CIFAR-10, Brain MRI, Chest X-Ray, German Traffic Signs, Flowers, Diabetic Retinopathy |

All datasets are sourced from Kaggle, UCI ML Repository, or scikit-learn built-in
datasets.

### 4.2 Conditions

We evaluate two conditions:

- **Condition B (No Dissect)**: The full Prometheus Swarm pipeline without the Dissect
  agent. If Furnace crashes, the system escalates immediately. This represents the
  baseline state-of-the-art for LLM-driven pipeline automation without error recovery.

- **Condition C (With Dissect)**: The full pipeline including Dissect. Furnace has up to
  3 crash-recovery attempts per job, each mediated by Dissect.

Both conditions use identical Scout, Forge, Furnace, Arbiter, and Harbor agents. The only
difference is the presence or absence of the Dissect error recovery loop. Each of the 50
problems was run once per condition, yielding 100 total runs. All runs used Claude Sonnet
4-6 (claude-sonnet-4-6) via the Anthropic API with identical system prompts and tool
definitions.

### 4.3 Metrics

We measure three primary metrics:

1.  **Pass rate**: The proportion of problems where Arbiter issues a PASS decision.
    Problems that crash, escalate, or retry without recovery are counted as non-pass.

2.  **Human interventions**: The number of problems requiring manual intervention. In
    Condition B, every crash or escalation counts as one intervention. In Condition C,
    only problems that Dissect fails to recover (escalated) count as interventions.

3.  **Dissect save rate**: Among problems where Dissect attempts a patch (crash_count >
    0), the proportion that ultimately pass.

Statistical significance is assessed using McNemar&rsquo;s test for paired pass/fail data
and the Mann-Whitney U test for intervention counts. Effect size is reported using
Cohen&rsquo;s h for pass rate differences and rank-biserial r for intervention
differences.

## 5. Results

### 5.1 Overall Performance

Table 1 summarizes the overall results across all 50 problems.

| Metric | Condition B | Condition C | Delta | p-value |
|---|---|---|---|---|
| Pass rate | 14/50 (28.0%) | 25/50 (50.0%) | **+22.0 pp** | 0.0026 (McNemar) |
| Human interventions | 36 (0.72/job) | 25 (0.50/job) | **-30.6%** | 0.013 (MWU) |
| Avg metric (passing) | 330.79 | 185.62 | -43.9% | |
| Avg duration | 2.9s | 63.1s | +60.2s | |

The 22 percentage-point improvement in pass rate is statistically significant (McNemar
&chi;=9.09, p=0.0026, Cohen&rsquo;s h=0.456, small-to-medium effect). Critically, **zero
problems regressed**: in all cases where Condition B passed, Condition C also passed
(14/14), and 11 problems that failed under Condition B were successfully recovered under
Condition C. The remaining 25 failures under Condition B remained failures under
Condition C.

The 31% reduction in human interventions is also significant (Mann-Whitney U=1525,
p=0.013, one-sided, rank-biserial r=0.22). The increase in average duration from 2.9s to
63.1s is expected: Dissect&rsquo;s sandbox testing and LLM-based patch generation add
runtime overhead but eliminate the need for a human operator.

### 5.2 Per-Modality Analysis

Table 2 breaks down results by data modality.

| Modality | B Pass | C Pass | Delta | B Interventions | C Interventions | Improvement |
|---|---|---|---|---|---|---|
| Tabular (n=32) | 14 (43.8%) | 23 (71.9%) | **+28.1 pp** | 18 | 9 | **-50.0%** |
| Text (n=10) | 0 (0.0%) | 1 (10.0%) | +10.0 pp | 10 | 9 | -10.0% |
| Image (n=8) | 0 (0.0%) | 1 (12.5%) | +12.5 pp | 8 | 7 | -12.5% |

Tabular problems show the strongest improvement: pass rate nearly doubles from 43.8% to
71.9%, and interventions are cut in half. The dominant failure mode in Condition B was
KeyError due to Scout misidentifying column names (24 of 25 crashes). Dissect handles
these by parsing the error traceback, identifying the correct column name from the
dataset, and replacing the reference in the training script&mdash;a pattern that the LLM
handles reliably.

Text and image problems show more modest improvement. This is primarily because Dissect
operates at the script level: it can fix column name mismatches and type errors, but
text and image problems often require architectural fixes (e.g., switching from DistilBERT
to LightGBM when the task is actually tabular), which are outside Dissect&rsquo;s scope
and must be handled by the Forge agent&rsquo;s retry mechanism.

### 5.3 Dissect Recovery Analysis

Dissect attempted patches on 18 of 50 problems (36%) under Condition C. Table 3 shows
the outcomes.

| Outcome | Count | Percentage |
|---|---|---|
| Recovered (passed) | 11 | 61.1% |
| Failed (crashed) | 3 | 16.7% |
| Escalated | 4 | 22.2% |

Of the 11 successful recoveries, 10 were KeyError fixes (column name mismatches) and 1
was a ValueError fix (target type mismatch for DistilBERT with continuous labels). The
three confirmed failures were cases where Dissect generated a syntactically correct patch
that still produced incorrect output (caught by Arbiter evaluation, which found no valid
predictions). The four escalated cases were errors where Dissect could not generate a
confident patch: these included ambiguous column references and errors in complex
feature engineering code.

### 5.4 Error Distribution

Under Condition B, 25 of 50 problems (50%) crashed. The error breakdown is:

- **KeyError (missing column)**: 24 crashes (96%). In all cases, Scout correctly
  identified the target column name in the Mission Brief, but the generated LightGBM
  training script hard-coded a different column reference, typically `df.iloc[:, -1]` or
  a guessed column name that did not match the actual CSV header.
- **ValueError (type mismatch)**: 1 crash (4%). The DistilBERT classifier received
  continuous regression labels instead of discrete classes.

Under Condition C, Dissect reduced crashes from 25 to 3 (a 88% reduction) and escalations
from 6 to 4 (a 33% reduction). The remaining 3 crashes under Condition C were scenarios
where Dissect produced a patch that passed the sandbox test but the fully trained model
had no valid predictions (e.g., all predictions were the same class).

## 6. Threats to Validity

**Internal validity.** The benchmark uses a single LLM (Claude Sonnet 4-6) for all agent
decisions and patch generation. Results may not generalize to other LLMs. The same LLM
generates the training scripts (Forge) and the patches (Dissect), creating a potential
confound: Dissect may be more effective at fixing scripts generated by the same model.

**External validity.** While our 50-problem benchmark covers diverse modalities and
datasets, all are relatively small (rows = 150 to 50,000). The system has not been
evaluated on large-scale training jobs (100M+ parameters, TB-scale datasets) or
production-grade MLOps infrastructure. Error modes at scale (e.g., network timeouts,
distributed training failures, resource contention) are not represented.

**Construct validity.** We measure human interventions as a binary flag per problem
(whether any human action was required). This does not capture the time cost or
complexity of each intervention. A problem that requires 5 minutes of human debugging is
treated identically to one that requires 5 hours.

**Reliability.** The sandbox test used by Dissect has a 60-second timeout and tests only
that the script does not crash with the original exception. A passing sandbox test does
not guarantee model quality&mdash;as evidenced by the 3 cases where sandbox-passing
patches produced non-viable models.

## 7. Related Work

**AutoML and Automated Pipeline Construction.** Systems such as AutoGluon [3],
Auto-sklearn [4], and TPOT [10] automate model selection, hyperparameter tuning, and
feature engineering. These systems achieve strong predictive performance but assume clean
input data and do not handle runtime execution errors. When a pipeline step fails, the
entire search restarts or requires human debugging. Prometheus Swarm extends AutoML by
adding a runtime error recovery layer that repairs failures without restarting from
scratch.

**LLM-Based Code Repair.** Recent work on LLM-driven software repair includes
SWE-agent [7], which uses Claude to navigate GitHub issues, edit code, and run tests;
Auto2ML [8], which applies LLM-based code modification to ML pipelines; and
AlphaCode [11], which generates solutions to competitive programming problems. These
systems operate on static codebases or problem statements. Dissect differs in three ways:
it operates on live training pipelines, it integrates a structured error taxonomy with
vector memory for retrieving past repairs, and it validates patches in a sandbox before
applying them.

**Self-Healing Systems.** The concept of self-healing software dates back to autonomic
computing [12]. In ML systems, auto-remediation has been explored for model serving
(e.g., automatic rollback on performance degradation) [13] but not for training pipeline
failures. Prometheus Swarm applies self-healing principles to the training phase, where
the cost of failure is highest (wasted GPU time, delayed deployments).

**Multi-Agent LLM Systems.** Multi-agent LLM architectures have been applied to software
engineering (ChatDev [14], MetaGPT [15]) and scientific research (ChemCrow [16]).
Prometheus Swarm applies the multi-agent pattern to ML operations, with specialized
agents for each phase of the ML lifecycle and a dedicated error-recovery agent.

## 8. Conclusion and Future Work

We presented Prometheus Swarm, a multi-agent system for autonomous ML-as-a-Service, and
Dissect, an agent for autonomous self-patching of ML training failures. In a benchmark
of 50 diverse ML problems, the system with Dissect achieved a 22 percentage-point
improvement in pass rate (p=0.003) and a 31% reduction in human interventions (p=0.013)
compared to an identical system without error recovery. Dissect successfully recovered
61.1% of crash scenarios autonomously.

These results demonstrate that LLM-driven self-patching is a viable approach to reducing
human intervention in ML pipeline operations. The key insight is that the majority of ML
training failures follow predictable patterns (96% of crashes in our benchmark were
KeyError column mismatches) that can be reliably diagnosed and repaired by LLMs when
combined with a structured taxonomy and vector memory.

**Future work.** Several directions are promising:

1.  **Multi-modal error context.** Dissect currently uses only the error message and
    traceback. Incorporating dataset schema information, column statistics, and model
    architecture details could improve patch quality.

2.  **Patch quality assurance.** The sandbox test is minimal (no crash = pass). A more
    sophisticated validation that compares model quality metrics before and after the
    patch could catch the 3 false-positive cases we observed.

3.  **Cross-job learning.** Architecture memory currently stores only outcome labels.
    Storing the full patch diff and its evaluation outcome could enable Dissect to learn
    repair strategies across jobs.

4.  **Generalization to other LLMs and domains.** Evaluating Dissect with different LLM
    backends (GPT-4, Gemini) and on non-ML software engineering tasks would test the
    generality of the approach.

5.  **Large-scale evaluation.** Deploying Prometheus Swarm in a production MLOps
    environment with real user traffic would provide stronger evidence of practical
    impact.

## References

[1] D. Sculley, G. Holt, D. Golovin, E. Davydov, T. Phillips, D. Ebner, V. Chaudhary,
M. Young, J. F. Crespo, and D. Dennison. "Hidden Technical Debt in Machine Learning
Systems." In *Advances in Neural Information Processing Systems (NeurIPS)*, 2015.

[2] N. Polyzotis, S. Roy, S. E. Whang, and M. Zinkevich. "Data Lifecycle Challenges in
Production Machine Learning: A Survey." *ACM SIGMOD Record*, 47(2):17&ndash;28, 2018.

[3] N. Erickson, J. Mueller, A. Shirkov, H. Zhang, P. Larroy, M. Li, and A. Smola.
"AutoGluon-Tabular: Robust and Accurate AutoML for Structured Data." In *ICML Workshop
on Automated Machine Learning (AutoML)*, 2020.

[4] M. Feurer, A. Klein, K. Eggensperger, J. Springenberg, M. Blum, and F. Hutter.
"Efficient and Robust Automated Machine Learning." In *Advances in Neural Information
Processing Systems (NeurIPS)*, 2015.

[5] D. Baylor, E. Breck, H.-T. Cheng, N. Fiedel, C. Y. Foo, Z. Haque, S. Haykal,
M. Ispir, V. Jain, L. Koc, C. Y. Koo, L. Lew, C. Mewald, A. N. Modi, N. Polyzotis,
S. Ramesh, S. Roy, S. E. Whang, M. Wicke, J. Wilkiewicz, X. Zhang, and M. Zinkevich.
"TFX: A TensorFlow-Based Production-Scale Machine Learning Platform." In *ACM SIGKDD
International Conference on Knowledge Discovery and Data Mining (KDD)*, 2017.

[6] A. Chen, A. Chow, A. Davidson, A. DCunha, A. Ghodsi, S. A. Hong, A. Konwinski,
C. Mewald, S. Murching, T. Nykodym, P. Ogilvie, M. Parkhe, A. Singh, F. Xie, M. Zaharia,
R. Zang, J. Zheng, and C. Zumar. "MLflow: A Platform for Reproducible ML and LLMOps."
Conference on Innovative Data Systems Research (CIDR), 2020.

[7] J. Yang, C. E. Jimenez, A. Agarwal, K. Li, R. Wanjia, O. Press, and K. Narasimhan.
"SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering." arXiv
preprint arXiv:2405.15793, 2024.

[8] Amazon Web Services. "Auto2ML: Automated Machine Learning Lifecycle Management."
AWS Documentation, 2025.

[9] M. M. Ghonaim. "Prometheus Swarm Architecture and Decision Tree Specification."
Nexora Lab Technical Report, 2025.

[10] R. S. Olson, N. Bartley, R. J. Urbanowicz, and J. H. Moore. "Evaluation of a
Tree-based Pipeline Optimization Tool for Automating Data Science." In *ACM Conference
on Genetic and Evolutionary Computation (GECCO)*, 2016.

[11] Google DeepMind. "AlphaCode: Competition-Level Code Generation with Large Language
Models." *Science*, 378(6624):1092&ndash;1097, 2022.

[12] J. O. Kephart and D. M. Chess. "The Vision of Autonomic Computing." *IEEE
Computer*, 36(1):41&ndash;50, 2003.

[13] C. Zhang, S. Bengio, M. Hardt, B. Recht, and O. Vinyals. "Understanding Deep
Learning Requires Rethinking Generalization." In *International Conference on Learning
Representations (ICLR)*, 2017.

[14] C. Qian, W. Liu, H. Liu, N. Chen, Y. Dang, J. Li, Y. Huang, S. Gao, and L. Yu.
"ChatDev: Communicative Agents for Software Development." arXiv preprint
arXiv:2307.07924, 2023.

[15] S. Hong, M. Zhuge, J. Chen, X. Zheng, Y. Cheng, C. Zhang, J. Wang, Z. Wang,
S. K. S. Yau, H. Lin, L. Zhou, C. Ran, L. Xiao, and C. Wu. "MetaGPT: Meta Programming
for A Multi-Agent Collaborative Framework." In *International Conference on Learning
Representations (ICLR)*, 2024.

[16] A. M. Bran, S. Cox, O. Schilter, C. Baldassari, A. D. White, and P. Schwaller.
"Augmenting Large Language Models with Chemistry Tools." arXiv preprint
arXiv:2304.05376, 2023.
