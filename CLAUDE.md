# CLAUDE.md — Prometheus Swarm
# Foundational Operating Document for All Claude Code Sessions
# Version: 1.0 | Project: Prometheus Swarm | Owner: Mohamed Mosad Ghonaim
# Alamein International University — Nexora Lab — nexoraintel.com
# This file is the single source of truth. Never contradict it. Never improvise against it.

---

## 0. WHAT THIS PROJECT IS — READ THIS FIRST

Prometheus Swarm is an autonomous multi-agent system that accepts a raw natural-language
description of a machine-learning problem and returns — without any human intervention —
a fully trained, evaluated, and live-served model endpoint.

The system coordinates six specialized AI agents. Each agent is an independent process with
its own system prompt, its own callable tools, and its own memory scope. Agents communicate
exclusively through a Redis Streams message bus. No agent calls another agent directly.

This is simultaneously:
1. A graduation research project targeting publication at MSR or ASE 2026
2. The architectural foundation for a commercial SaaS product (ML-as-a-service)
3. The next product in the Nexora portfolio (nexoraintel.com)

The core scientific contribution is the Dissect agent: autonomous self-patching of ML
training failures without human input.

The one-sentence product definition: "You describe the task. The swarm does the rest."

---

## 1. ABSOLUTE RULES — NEVER VIOLATE THESE

1. NEVER rename any of the six agents. Their names are: Scout, Forge, Furnace, Dissect,
   Arbiter, Harbor. These names are used in system prompts, Redis event keys, log files,
   paper drafts, and the frontend. Changing a name breaks everything.

2. NEVER change the Redis event taxonomy without explicit instruction. Event names are
   contracts between agents. Changing CRASH_EVENT to TRAINING_ERROR breaks Dissect's
   consumer. See Section 5 for the full taxonomy.

3. NEVER change the mission_brief.json schema without explicit instruction. Every agent
   downstream of Scout reads this file. See Section 6 for the exact schema.

4. NEVER put agent logic inside another agent's module. Scout does not train. Forge does
   not evaluate. Dissect does not deploy. Each agent owns exactly one phase. If you find
   yourself writing cross-agent logic, stop and ask.

5. NEVER use synchronous blocking calls between agents. All inter-agent communication is
   asynchronous via Redis Streams. If Agent A needs Agent B's output, it reads it from
   the stream or from Redis key-value, not by calling Agent B's function directly.

6. NEVER hardcode API keys, model names as literals, or infrastructure endpoints in
   agent code. All such values come from environment variables defined in .env and
   loaded via python-dotenv. See Section 9 for the full env var list.

7. NEVER skip writing to the patch log when Dissect attempts a patch. This log is the
   research dataset. Every attempt (success OR failure) must be recorded. Missing entries
   invalidate the paper's experimental results. Write path: Dissect → Redis RPUSH
   "patch_log_queue" → patch_log_writer.py → research/patch_log.jsonl. Never write
   directly to the file from agent code. See Section 7 for the full write path.

8. NEVER let a module be "owned by everyone." Every file has exactly one owner listed
   in Section 4. If ownership is unclear, ask before writing.

9. NEVER deploy to GKE during Phase 0, 1, 2, or 3. Local Docker Compose is the serving
   environment for all research. GKE is Phase 4 only.

10. NEVER commit code that breaks the integration test suite. The Titanic end-to-end test
    (Phase 1 gate) must stay green at all times after Phase 1 completes.

---

## 2. PROJECT DIRECTORY STRUCTURE

All paths are relative to the repository root. Do not create files outside this structure
without explicit instruction.

```
prometheus-swarm/
│
├── CLAUDE.md                          ← THIS FILE. Never move it.
├── .env                               ← Environment variables. Never commit to git.
├── .env.example                       ← Committed env template with no values.
├── .gitignore
├── requirements.txt                   ← Pinned dependencies. All versions pinned.
├── pyproject.toml
├── README.md
│
├── agents/                            ← One module per agent. No cross-imports.
│   ├── __init__.py
│   ├── scout/
│   │   ├── __init__.py
│   │   ├── agent.py                   ← Scout agent loop + LLM call
│   │   ├── tools.py                   ← parse_problem, detect_modality, run_eda
│   │   └── prompts.py                 ← Scout system prompt (string constant)
│   ├── forge/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── tools.py                   ← select_architecture, write_training_script
│   │   ├── decision_tree.py           ← Architecture selection heuristics
│   │   └── prompts.py
│   ├── furnace/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── tools.py                   ← launch_container, monitor_loss, publish_metrics
│   │   └── prompts.py
│   ├── dissect/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── tools.py                   ← parse_trace, classify_error, apply_patch
│   │   ├── taxonomy.py                ← Error taxonomy: categories + repair strategies
│   │   ├── patch_log.py               ← patch_log.jsonl writer (NEVER skip this)
│   │   └── prompts.py
│   ├── arbiter/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── tools.py                   ← compute_metrics, failure_analysis, decide
│   │   └── prompts.py
│   └── harbor/
│       ├── __init__.py
│       ├── agent.py
│       ├── tools.py                   ← serialize_model, build_api, deploy, monitor_drift
│       ├── serving_template.py        ← FastAPI app template Harbor fills per model
│       └── prompts.py
│
├── orchestrator/                      ← Owns the runtime that launches + manages agents
│   ├── __init__.py
│   ├── runtime.py                     ← Main orchestration loop
│   ├── job_queue.py                   ← Job submission + queuing
│   ├── health_monitor.py             ← Agent crash detection + restart logic
│   └── patch_log_writer.py           ← Single-threaded BLPOP → JSONL writer (see §7)
│
├── memory/                            ← All memory layer code
│   ├── __init__.py
│   ├── redis_client.py                ← Redis connection + Streams helpers
│   ├── chroma_client.py               ← ChromaDB connection + collection helpers
│   ├── collections/
│   │   ├── patch_memory.py            ← patch_memory collection logic
│   │   ├── architecture_memory.py     ← architecture_memory collection logic
│   │   └── tool_memory.py             ← tool_memory collection logic
│   └── schemas.py                     ← Pydantic models for all memory records
│
├── bus/                               ← Redis Streams message bus abstraction
│   ├── __init__.py
│   ├── publisher.py                   ← publish(stream_name, event_type, payload)
│   ├── consumer.py                    ← consume(stream_name, consumer_group, handler)
│   └── events.py                      ← All event type constants (single source of truth)
│
├── training/                          ← Training environment management
│   ├── __init__.py
│   ├── docker_manager.py              ← Container lifecycle: launch, monitor, kill, restart
│   ├── checkpoint_manager.py          ← Save, restore, integrity-check checkpoints
│   └── base_training_image/
│       └── Dockerfile                 ← Base Docker image for all training containers
│
├── serving/                           ← Model serving infrastructure
│   ├── __init__.py
│   ├── onnx_runtime.py                ← ONNX model loading + inference
│   ├── drift_monitor.py               ← PSI computation service
│   └── docker/
│       └── Dockerfile                 ← Serving container Dockerfile
│
├── scripts/                           ← All training scripts written by Forge live here
│   └── .gitkeep                       ← Forge writes training_script_{job_id}.py here
│
├── outputs/                           ← All job outputs: models, logs, reports
│   └── .gitkeep
│
├── data/                              ← Dataset uploads for local dev/testing
│   └── .gitkeep
│
├── tests/                             ← All test files
│   ├── __init__.py
│   ├── integration/
│   │   ├── test_titanic_e2e.py        ← Phase 1 gate test. Must stay green.
│   │   └── test_three_kaggle_e2e.py   ← Phase 2 gate test.
│   ├── unit/
│   │   ├── test_scout_tools.py
│   │   ├── test_forge_decision_tree.py
│   │   ├── test_dissect_taxonomy.py   ← Test each error category + repair strategy
│   │   ├── test_arbiter_metrics.py
│   │   └── test_bus_events.py
│   └── fixtures/
│       ├── titanic.csv
│       └── injected_errors/           ← 5 deliberately broken scripts for Dissect testing
│
├── frontend/                          ← Next.js live agent feed UI
│   ├── package.json
│   └── src/
│       └── app/
│           └── feed/                  ← Live SSE feed page
│
├── infra/                             ← Infrastructure config (Phase 3)
│   ├── kubernetes/
│   │   └── deployment.yaml
│   ├── helm/
│   └── monitoring/
│       ├── prometheus.yml
│       └── grafana_dashboard.json
│
├── research/                          ← Research experiment for MSR/ASE 2026 paper
│   ├── benchmark/
│   │   ├── problems.json              ← 50 ML problems definition
│   │   └── results/
│   ├── patch_log.jsonl                ← THE RESEARCH DATASET (JSONL). Never delete.
│   ├── convert_jsonl_to_json.py       ← Post-experiment: JSONL → JSON array for paper
│   └── paper/
│       └── draft.md
│
└── docker-compose.yml                 ← Local dev: Redis + ChromaDB + serving stack
```

---

## 3. THE SIX AGENTS — CONTRACTS

Each agent has a fixed role. Read this before writing any agent code.

### 3.1 Scout — The Perceiver
- **Input:** Raw natural-language problem description + dataset file path + constraints
- **Output:** `mission_brief.json` written to Redis key `job:{job_id}:mission_brief`
- **Tools it can call:** `parse_problem`, `detect_modality`, `run_eda`, `write_mission_brief`
- **Publishes to bus:** `MISSION_BRIEF_READY` event on stream `scout_output`
- **Subscribes to:** Nothing (Scout is the entry point)
- **Must detect:** task_type, modality, target_column, class_imbalance_ratio,
  feature_types, recommended_metric, data_warnings
- **Does NOT do:** Training, architecture selection, evaluation, deployment

### 3.2 Forge — The Architect
- **Input:** `mission_brief.json` from Redis
- **Output:** `training_script_{job_id}.py` written to `scripts/` + `search_space.json`
  written to Redis key `job:{job_id}:search_space`
- **Tools it can call:** `read_mission_brief`, `select_architecture`, `write_training_script`,
  `define_optuna_space`
- **Publishes to bus:** `TRAINING_SCRIPT_READY` event on stream `forge_output`
- **Subscribes to:** `scout_output` stream (waits for `MISSION_BRIEF_READY`)
- **Architecture decision logic lives in:** `agents/forge/decision_tree.py`
- **Does NOT do:** Running training, evaluating, patching errors, deploying

### 3.3 Furnace — The Trainer
- **Input:** `training_script_{job_id}.py` path from Redis + `search_space.json`
- **Output:** Trained model checkpoint at `outputs/{job_id}/checkpoints/best.ckpt`
  + live metrics stream
- **Tools it can call:** `launch_training_container`, `monitor_loss_curves`,
  `publish_epoch_metrics`, `save_checkpoint`, `catch_crash`
- **Publishes to bus:**
  - `EPOCH_COMPLETE` (every epoch) on stream `furnace_feed`
  - `TRAINING_COMPLETE` on stream `furnace_output`
  - `CRASH_EVENT` (on any Python exception) on stream `furnace_crash`
- **Subscribes to:** `forge_output` stream + `dissect_output` stream (RESUME_TRAINING)
- **Does NOT do:** Writing code, evaluating, deploying, patching

### 3.4 Dissect — The Debugger (Core Scientific Contribution)
- **Input:** `CRASH_EVENT` from `furnace_crash` stream
- **Output:** Patched `training_script_{job_id}.py` + entry in `research/patch_log.jsonl`
  + `RESUME_TRAINING` event
- **Tools it can call:** `parse_stack_trace`, `classify_error`, `query_patch_memory`,
  `generate_patch`, `apply_patch`, `write_patch_log`, `publish_resume`
- **Publishes to bus:**
  - `RESUME_TRAINING` on stream `dissect_output`
  - `ESCALATE` on stream `dissect_output` (after 3 failed patch attempts)
- **Subscribes to:** `furnace_crash` stream
- **Max auto-patch attempts per crash:** 3. After 3, publish ESCALATE.
- **Patch must be tested:** Apply patch → run patched script in sandbox container →
  if it fails again within 3 epochs → rollback → try next strategy → if no strategy
  works after 3 attempts → ESCALATE.
- **patch_log.jsonl entry is MANDATORY for every patch attempt, success or failure**
- **Does NOT do:** Training, evaluating, deploying, selecting architectures

### 3.5 Arbiter — The Critic
- **Input:** Best model checkpoint path from Redis + test dataset path
- **Output:** `eval_report_{job_id}.json` written to `outputs/{job_id}/` +
  decision signal
- **Tools it can call:** `load_checkpoint`, `compute_classification_metrics`,
  `compute_regression_metrics`, `generate_failure_analysis`, `make_decision`
- **Publishes to bus:**
  - `PASS` on stream `arbiter_output` (metrics exceed thresholds)
  - `RETRY` on stream `arbiter_output` (metrics within 15% of threshold)
  - `ESCALATE` on stream `arbiter_output` (metrics far below or 3+ crashes occurred)
- **Subscribes to:** `furnace_output` stream (waits for `TRAINING_COMPLETE`)
- **Decision logic:**
  - All metrics ≥ threshold → PASS
  - Metrics < threshold but within 15% → RETRY (signals Forge for new architecture)
  - Metrics > 15% below threshold OR ≥ 3 crashes → ESCALATE
- **Regression threshold strategy:** Regression metrics (RMSE, MAE) are dataset-relative,
  not absolute. The baseline is `std(y_target)` (standard deviation of the target column).
  A model must beat the naive mean prediction by ≥15%: `threshold_rmse = std(y_target) * 0.85`.
  Arbiter computes this dynamically from the test set, not from a hardcoded constant.
- **Does NOT do:** Training, patching, deploying, modifying scripts

### 3.6 Harbor — The Deployer
- **Input:** `PASS` event from `arbiter_output` + checkpoint path
- **Output:** Live HTTPS endpoint URL + monitoring dashboard
- **Tools it can call:** `serialize_to_onnx`, `generate_fastapi_app`, `build_docker_image`,
  `deploy_local_compose` (Phase 1-3) / `deploy_to_gke` (Phase 4 only),
  `configure_drift_monitor`, `publish_endpoint`
- **Publishes to bus:**
  - `ENDPOINT_LIVE` on stream `harbor_output`
  - `DRIFT_ALERT` on stream `harbor_output` (when PSI > 0.2)
- **Subscribes to:** `arbiter_output` (waits for PASS) + `harbor_output` for its own
  DRIFT_ALERT (to trigger retraining cycle back to Scout)
- **Drift check:** PSI computed hourly on last 1,000 live inputs vs training distribution
- **PSI threshold:** > 0.2 triggers DRIFT_ALERT → Scout begins new cycle
- **Does NOT do:** Training, patching, evaluating, architecture selection
- **Phase 1-3:** Deploy to local Docker Compose only
- **Phase 4:** Deploy to GKE (Kubernetes manifests in `infra/kubernetes/`)

---

## 4. FILE OWNERSHIP

Every file has exactly one owner. Since this is a solo build, all files are owned by Mohamed.
The owner column is retained per path for traceability if external contributors join later.

| Path | Owner |
|------|-------|
| `agents/*` | @mohamed |
| `orchestrator/*` | @mohamed |
| `bus/*` | @mohamed |
| `memory/*` | @mohamed |
| `training/*` | @mohamed |
| `serving/*` | @mohamed |
| `tests/*` | @mohamed |
| `research/*` | @mohamed |
| `frontend/*` | @mohamed |
| `infra/*` | @mohamed |
| `docker-compose.yml` | @mohamed |
| `requirements.txt` | @mohamed |
| `CLAUDE.md`, `PLAN.md` | @mohamed |

---

## 5. REDIS EVENT TAXONOMY — EXACT SCHEMAS

These are the contracts between agents. Never add, remove, or rename a field without
updating this section and all subscriber code simultaneously.

All events are published to Redis Streams via `bus/publisher.py`.
All events are consumed via `bus/consumer.py`.
All event type string constants live in `bus/events.py`. Import from there. Never use
raw strings for event types in agent or tool code.

```python
# bus/events.py — the ONLY place event type strings are defined

MISSION_BRIEF_READY   = "MISSION_BRIEF_READY"
TRAINING_SCRIPT_READY = "TRAINING_SCRIPT_READY"
EPOCH_COMPLETE        = "EPOCH_COMPLETE"
TRAINING_COMPLETE     = "TRAINING_COMPLETE"
CRASH_EVENT           = "CRASH_EVENT"
RESUME_TRAINING       = "RESUME_TRAINING"
PASS                  = "EVALUATION_PASS"
RETRY                 = "EVALUATION_RETRY"
ESCALATE              = "ESCALATE"
ENDPOINT_LIVE         = "ENDPOINT_LIVE"
DRIFT_ALERT           = "DRIFT_ALERT"
JOB_FAILED            = "JOB_FAILED"
```

### Event Payload Schemas

```python
# MISSION_BRIEF_READY
{
    "event_type": "MISSION_BRIEF_READY",
    "job_id": str,                    # UUID4, generated at job submission
    "mission_brief_redis_key": str,   # "job:{job_id}:mission_brief"
    "timestamp": str                  # ISO 8601
}

# TRAINING_SCRIPT_READY
{
    "event_type": "TRAINING_SCRIPT_READY",
    "job_id": str,
    "script_path": str,               # "scripts/training_script_{job_id}.py"
    "search_space_redis_key": str,    # "job:{job_id}:search_space"
    "timestamp": str
}

# EPOCH_COMPLETE
{
    "event_type": "EPOCH_COMPLETE",
    "job_id": str,
    "epoch": int,
    "train_loss": float,
    "val_loss": float,
    "eta_seconds": int,               # Estimated time to completion
    "timestamp": str
}

# TRAINING_COMPLETE
{
    "event_type": "TRAINING_COMPLETE",
    "job_id": str,
    "checkpoint_path": str,           # "outputs/{job_id}/checkpoints/best.ckpt"
    "best_val_metric": float,
    "total_epochs": int,
    "total_crashes_recovered": int,   # Count of successful Dissect recoveries
    "timestamp": str
}

# CRASH_EVENT
{
    "event_type": "CRASH_EVENT",
    "job_id": str,
    "exception_type": str,            # e.g. "ValueError", "MemoryError"
    "exception_message": str,
    "traceback": str,                 # Full stack trace as string
    "script_path": str,               # Path to the crashed script
    "last_checkpoint_path": str,      # Path to last valid checkpoint (or null)
    "epoch_at_crash": int,
    "crash_attempt_number": int,      # 1, 2, or 3 — escalate after 3
    "timestamp": str
}

# RESUME_TRAINING
{
    "event_type": "RESUME_TRAINING",
    "job_id": str,
    "patched_script_path": str,
    "resume_from_checkpoint": str,    # Path or null (restart from 0 if null)
    "patch_id": str,                  # UUID4, links to patch_log.jsonl entry
    "timestamp": str
}

# EVALUATION_PASS
{
    "event_type": "EVALUATION_PASS",
    "job_id": str,
    "eval_report_path": str,          # "outputs/{job_id}/eval_report_{job_id}.json"
    "primary_metric": str,            # e.g. "auc_roc"
    "primary_metric_value": float,
    "timestamp": str
}

# EVALUATION_RETRY
{
    "event_type": "EVALUATION_RETRY",
    "job_id": str,
    "eval_report_path": str,
    "reason": str,                    # Human-readable reason for retry
    "timestamp": str
}

# ESCALATE
{
    "event_type": "ESCALATE",
    "job_id": str,
    "source_agent": str,              # Which agent is escalating: "Dissect" or "Arbiter"
    "reason": str,
    "diagnostic_report_path": str,   # Full diagnostic for human review
    "timestamp": str
}

# JOB_FAILED  ← published by Orchestrator after consuming ESCALATE (not by agents)
{
    "event_type": "JOB_FAILED",
    "job_id": str,
    "source_agent": str,              # Passed through from ESCALATE
    "reason": str,                    # Passed through from ESCALATE
    "diagnostic_report_path": str,   # Path to full diagnostic for user download
    "timestamp": str
}

# ENDPOINT_LIVE  ← published by Harbor after successful deployment
{
    "event_type": "ENDPOINT_LIVE",
    "job_id": str,
    "endpoint_url": str,
    "val_metric": float,
    "p95_latency_ms": float,
    "model_format": str,              # "onnx" or "pickle" (ONNX preferred, pickle fallback)
    "timestamp": str
}

# DRIFT_ALERT  ← published by Harbor when PSI exceeds threshold
{
    "event_type": "DRIFT_ALERT",
    "job_id": str,
    "psi_score": float,
    "psi_threshold": 0.2,
    "window_size": 1000,              # Number of recent inputs PSI was computed on
    "timestamp": str
}
```

### ESCALATE Resolution Path — What Happens After ESCALATE

ESCALATE is consumed by the Orchestrator via `orchestrator_consumers` group on the
stream where it was published (`dissect_output` or `arbiter_output`).

**What the Orchestrator does on receiving ESCALATE:**
1. Sets `job:{job_id}:status` in Redis to `"ESCALATED"`
2. If source is Dissect: sends KILL signal to Furnace → Furnace kills the training
   container and releases Docker resources
3. If source is Arbiter: no container to kill (training already complete)
4. Writes `diagnostic_report_{job_id}.json` to `outputs/{job_id}/` containing:
   - All EPOCH_COMPLETE events (training history)
   - All patch_log entries for this job (Dissect's attempts, if any)
   - The eval_report (if Arbiter escalated)
   - The reason string from the ESCALATE event
5. Publishes `JOB_FAILED` event to stream `orchestrator_output`
6. Frontend SSE feed reads `JOB_FAILED` and displays to the user:
   "Job failed — Prometheus Swarm could not automatically resolve this issue.
   Download the diagnostic report to understand what went wrong."
   with a link to `diagnostic_report_{job_id}.json`

**System state after ESCALATE:**
- Training container: killed and removed (if Dissect-sourced)
- Redis keys `job:{job_id}:*`: preserved for 24 hours (TTL), then auto-deleted
- `research/patch_log.jsonl`: all Dissect attempts recorded with `outcome=escalated`
- Harbor: never receives this job. Harbor ONLY processes EVALUATION_PASS events.
- The job does NOT block new submissions — orchestrator continues serving the queue
- The escalated job_id is permanently marked `ESCALATED` in job history

**ESCALATE does NOT mean the system stops. It means this specific job failed.**

---

## 6. mission_brief.json — EXACT SCHEMA

Written by Scout to Redis key `job:{job_id}:mission_brief`.
Read by Forge, Furnace, Arbiter, and Harbor.
Never add or remove fields without updating all reader agents.

```json
{
    "schema_version": "1.0",
    "job_id": "uuid4-string",
    "problem_description": "raw user input string",
    "task_type": "classification | regression | detection | generation",
    "modality": "tabular | text | image",
    "target_column": "string | null",
    "evaluation_metric": "auc_roc | f1 | rmse | mae | map | null",
    "constraints": {
        "max_latency_ms": "int | null",
        "max_model_size_mb": "int | null"
    },
    "dataset": {
        "file_path": "string",
        "num_rows": "int",
        "num_columns": "int",
        "column_types": {
            "column_name": "numeric | categorical | text | datetime | target"
        }
    },
    "data_quality": {
        "class_imbalance_ratio": "float | null",
        "missing_value_rate": {
            "column_name": "float (0.0 to 1.0)"
        },
        "high_cardinality_columns": ["column_name"],
        "data_warnings": ["human-readable warning strings"]
    },
    "imbalance_strategy": "none | class_weight | smote | focal_loss",
    "recommended_architecture_family": "lightgbm | xgboost | tabnet | distilbert | efficientnet | null",
    "created_at": "ISO 8601 timestamp"
}
```

---

## 7. patch_log — STORAGE + EXACT SCHEMA (THE RESEARCH DATASET)

Every Dissect patch attempt — success OR failure — must be recorded.
Never truncate, overwrite, or skip an entry. This is the paper's dataset.

### Storage Strategy — Race Condition Protection

**DO NOT** append directly to `research/patch_log.jsonl` from agent code.
Concurrent jobs writing to the same flat JSON file will corrupt it (interleaved writes,
partial JSON, broken array structure). This would destroy the research dataset.

**The correct write path (implemented in `agents/dissect/patch_log.py`):**

```
Dissect generates patch entry (dict)
        │
        ▼
Redis RPUSH "patch_log_queue" (atomic, thread-safe, handles concurrency)
        │
        ▼
patch_log_writer.py (single-threaded background process, owned by SWE Lead)
Reads from "patch_log_queue" with BLPOP (blocking pop, one entry at a time)
        │
        ▼
Appends to research/patch_log.jsonl with file lock (filelock — cross-platform, works on Windows + Linux)
```

This means:
- `agents/dissect/patch_log.py` only does `RPUSH` to Redis — never file I/O
- `orchestrator/patch_log_writer.py` is the only process that writes the file
- File is opened in append mode: `open(path, 'a')` — never 'w'
- Each entry is written as a single JSON line (JSONL format), not as a JSON array
- Post-experiment: `research/convert_jsonl_to_json.py` converts JSONL → JSON array
  for paper submission and ChromaDB ingestion

**⚠️ The patch_log is JSONL (one JSON object per line), NOT a JSON array.**
Do not write `[` or `]` wrappers. Do not read it with `json.load()`.
Read it with: `[json.loads(line) for line in open(path)]`

Add to directory structure:
- `orchestrator/patch_log_writer.py` — SWE Lead owns this file
- `research/convert_jsonl_to_json.py` — AI Lead owns this file
Add to Redis keys:
- `patch_log_queue` — list, global (not job-scoped), RPUSH by Dissect, BLPOP by writer

### patch_log Entry Schema

```json
{"patch_id": "uuid4-string", "job_id": "uuid4-string", "timestamp": "ISO 8601", "exception_type": "ValueError", "exception_message": "exact message string", "error_taxonomy_category": "shape_mismatch | sparse_matrix | oom | cuda_oom | missing_column | dtype_mismatch | convergence_failure | import_error | nan_propagation | checkpoint_corruption | novel_error", "taxonomy_match_method": "regex | llm_classification", "repair_strategy_used": "string description of strategy", "retrieved_similar_patches": [{"patch_id": "uuid4", "similarity_score": 0.87}], "diff_applied": "unified diff string", "lines_changed": 4, "sandbox_test_result": "pass | fail", "patch_outcome": "success | rollback | escalated", "confidence_score": 0.91, "attempt_number": 1, "resume_from_checkpoint": "path string | null"}
```

Each entry is one line. No newlines within an entry. No trailing comma. No array wrapper.

---

## 8. DISSECT ERROR TAXONOMY — ALL KNOWN CATEGORIES

Defined in `agents/dissect/taxonomy.py`.
This is the AI Lead's (Mohamed's) primary ownership domain.
Do not add or modify categories without updating this section.

| Category Key | Exception Type | Example Message | Repair Strategy |
|---|---|---|---|
| `shape_mismatch` | ValueError | "X has 45 features, model expects 40" | Detect dropped columns; re-align feature list; regenerate encoder |
| `sparse_matrix` | TypeError | "SMOTE does not support sparse matrices" | Convert to dense before SMOTE; or replace SMOTE with class_weight |
| `oom` | MemoryError | "cannot allocate array" | Reduce batch size 50%; switch to chunked loading; flag if still OOM |
| `cuda_oom` | RuntimeError | "CUDA out of memory" | Halve batch size; enable gradient checkpointing; clear GPU cache |
| `missing_column` | KeyError | "'income_log' not found in DataFrame" | Detect missing derived column; add derivation step to preprocessing |
| `dtype_mismatch` | ValueError | "could not convert string to float" | Detect non-numeric column; add LabelEncoder or OrdinalEncoder |
| `convergence_failure` | ConvergenceWarning | "lbfgs failed to converge" | Increase max_iter; switch solver to saga; reduce regularisation |
| `import_error` | ModuleNotFoundError | "No module named 'lightgbm'" | Run pip install in container; retry |
| `nan_propagation` | ValueError | "Input contains NaN" | Detect NaN columns; median imputation for numeric; mode for categorical |
| `checkpoint_corruption` | UnpicklingError | "invalid load key" | Delete checkpoint; restart from epoch 0; increase save frequency |
| `novel_error` | Any | Does not match above | Use LLM backbone (Claude Sonnet via Anthropic API) with full context; log confidence score; escalate if confidence < 0.6 |

---

## 9. OBSERVABILITY PLAN — PROMETHEUS METRIC NAMES

All metrics are exposed at:
- `/metrics` on Harbor's serving endpoint (per-model prediction metrics)
- Internal metrics endpoint on the **orchestrator** (port 9090) via
  `prometheus_client.start_http_server(9090)` — started in `orchestrator/runtime.py`
  at orchestrator startup. This exposes all Furnace, Dissect, Arbiter, and Orchestrator
  counters/gauges/histograms to Prometheus scraping.

Names are final — do not invent new metric names without updating this section.

Use `prometheus-client` Python library. All metrics defined in `serving/metrics.py`
and imported by the relevant agent/module. Never define metrics inline in agent code.

```python
# serving/metrics.py — THE ONLY place Prometheus metric objects are instantiated

from prometheus_client import Counter, Gauge, Histogram

# ── Furnace metrics ──────────────────────────────────────────────────────────
furnace_epochs_total = Counter(
    "prometheus_furnace_epochs_total",
    "Total training epochs completed across all jobs",
    ["job_id", "model_type"]
)
furnace_train_loss = Gauge(
    "prometheus_furnace_train_loss",
    "Current training loss for active job",
    ["job_id"]
)
furnace_val_loss = Gauge(
    "prometheus_furnace_val_loss",
    "Current validation loss for active job",
    ["job_id"]
)
furnace_crashes_total = Counter(
    "prometheus_furnace_crashes_total",
    "Total training crashes encountered",
    ["job_id", "exception_type"]
)
furnace_training_duration_seconds = Histogram(
    "prometheus_furnace_training_duration_seconds",
    "Total wall-clock time for completed training runs",
    ["job_id", "model_type"],
    buckets=[60, 300, 600, 1200, 1800, 3600]
)

# ── Dissect metrics ──────────────────────────────────────────────────────────
dissect_patches_attempted_total = Counter(
    "prometheus_dissect_patches_attempted_total",
    "Total patch attempts by Dissect",
    ["error_category", "attempt_number"]
)
dissect_patches_successful_total = Counter(
    "prometheus_dissect_patches_successful_total",
    "Total successful patches (sandbox passed)",
    ["error_category"]
)
dissect_patches_escalated_total = Counter(
    "prometheus_dissect_patches_escalated_total",
    "Total jobs escalated after all patch attempts failed",
    []
)
dissect_patch_confidence = Histogram(
    "prometheus_dissect_patch_confidence",
    "Distribution of Dissect confidence scores per patch",
    ["error_category"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)
dissect_patch_duration_seconds = Histogram(
    "prometheus_dissect_patch_duration_seconds",
    "Time from CRASH_EVENT received to RESUME_TRAINING published",
    [],
    buckets=[1, 5, 10, 30, 60, 120]
)

# ── Arbiter metrics ──────────────────────────────────────────────────────────
arbiter_decisions_total = Counter(
    "prometheus_arbiter_decisions_total",
    "Total evaluation decisions made",
    ["decision"]   # "pass", "retry", "escalate"
)
arbiter_primary_metric_value = Gauge(
    "prometheus_arbiter_primary_metric_value",
    "Primary metric value of last evaluated model",
    ["job_id", "metric_name"]
)

# ── Harbor / Serving metrics ─────────────────────────────────────────────────
harbor_prediction_requests_total = Counter(
    "prometheus_harbor_prediction_requests_total",
    "Total /predict requests served",
    ["job_id", "status_code"]
)
harbor_prediction_latency_seconds = Histogram(
    "prometheus_harbor_prediction_latency_seconds",
    "End-to-end prediction latency",
    ["job_id"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)
harbor_psi_score = Gauge(
    "prometheus_harbor_psi_score",
    "Current PSI drift score for live model",
    ["job_id"]
)
harbor_drift_alerts_total = Counter(
    "prometheus_harbor_drift_alerts_total",
    "Total PSI drift threshold breaches",
    ["job_id"]
)

# ── Orchestrator / Job metrics ────────────────────────────────────────────────
orchestrator_jobs_submitted_total = Counter(
    "prometheus_orchestrator_jobs_submitted_total",
    "Total jobs submitted to the queue",
    []
)
orchestrator_jobs_completed_total = Counter(
    "prometheus_orchestrator_jobs_completed_total",
    "Total jobs that reached ENDPOINT_LIVE",
    []
)
orchestrator_jobs_failed_total = Counter(
    "prometheus_orchestrator_jobs_failed_total",
    "Total jobs that ended in ESCALATE",
    ["source_agent"]
)
orchestrator_job_e2e_duration_seconds = Histogram(
    "prometheus_orchestrator_job_e2e_duration_seconds",
    "Total wall-clock time from job submission to ENDPOINT_LIVE",
    [],
    buckets=[60, 300, 600, 900, 1200, 1800, 3600]
)
```

Grafana dashboard definitions live in `infra/monitoring/grafana_dashboard.json`.
The dashboard must include panels for: training loss curves, Dissect patch success rate,
job e2e duration distribution, prediction latency P50/P95/P99, PSI drift score timeline.

Pin all versions in `requirements.txt`. Never use unpinned dependencies.

### LLM Layer
```
anthropic>=0.25.0          # Anthropic Python SDK — Claude Sonnet powers all agents
```
- Model: loaded from env var `ANTHROPIC_MODEL` — NEVER hardcoded in agent code
- Default value in `.env`: `claude-sonnet-4-6` (current as of 2026)
- When Anthropic releases a new model, update `.env` only — no code changes needed
- Fallback chain: if the configured model returns a 404 or model-not-found error,
  log a CRITICAL warning and halt — do NOT silently fall back to an older model,
  as different models have different tool-use behaviour that may break agent contracts
- Loaded from env: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- Rate limit strategy: exponential backoff (1s → 2s → 4s)
- Cache agent outputs in Redis to avoid re-calling on retry

### ML Training Libraries
```
lightgbm>=4.3.0
xgboost>=2.0.3
scikit-learn>=1.4.2
torch>=2.3.0
transformers>=4.41.0       # HuggingFace Transformers (DistilBERT, ViT)
optuna>=3.6.1
imbalanced-learn>=0.12.3   # SMOTE and variants
pandas>=2.2.2
numpy>=1.26.4,<2.0         # Pin below 2.0 — sentence-transformers/chromadb compat
```

### Infrastructure
```
redis>=5.0.4               # Redis Python client (Streams + pub/sub)
chromadb>=0.5.0            # Vector database for long-term memory
sentence-transformers>=3.0.1  # Embedding model for ChromaDB
fastapi>=0.111.0           # Model serving API
uvicorn>=0.30.0            # ASGI server for FastAPI
onnx>=1.16.0               # Model serialisation format
onnxruntime>=1.18.0        # ONNX inference runtime
onnxmltools>=1.12.0        # LightGBM/XGBoost → ONNX conversion
docker>=7.1.0              # Docker SDK for Python (container management)
filelock>=3.15.0           # Cross-platform file locking (replaces fcntl for Windows compat)
```

### Monitoring
```
prometheus-client>=0.20.0  # /metrics endpoint for Harbor's API
```

### Dev + Testing
```
pytest>=8.2.0
pytest-asyncio>=0.23.7
python-dotenv>=1.0.1
pydantic>=2.7.1
scipy>=1.13.0              # Mann-Whitney U test for research experiment
httpx>=0.27.0              # HTTP client for Harbor health checks
```

---

## 10. ENVIRONMENT VARIABLES

All loaded via `python-dotenv` from `.env` at repo root.
Never hardcode any of these values in code.

```bash
# LLM
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6   # Update this when upgrading models. Never hardcode.

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=                    # Empty for local dev

# ChromaDB
CHROMA_HOST=localhost
CHROMA_PORT=8000
CHROMA_COLLECTION_PATCH_MEMORY=patch_memory
CHROMA_COLLECTION_ARCH_MEMORY=architecture_memory
CHROMA_COLLECTION_TOOL_MEMORY=tool_memory

# Embedding model
EMBEDDING_MODEL=all-MiniLM-L6-v2  # sentence-transformers model name

# Docker
TRAINING_IMAGE_NAME=prometheus-training-base
SERVING_IMAGE_NAME=prometheus-serving
DOCKER_REGISTRY=                   # Empty for local dev; GCR URL for Phase 3

# Paths
SCRIPTS_DIR=./scripts
OUTPUTS_DIR=./outputs
DATA_DIR=./data
PATCH_LOG_PATH=./research/patch_log.jsonl

# Serving
SERVING_PORT=8080
PSI_CHECK_INTERVAL_SECONDS=3600    # Hourly drift check
PSI_WINDOW_SIZE=1000               # Last N inputs for PSI computation
PSI_THRESHOLD=0.2

# Research
BENCHMARK_PROBLEMS_PATH=./research/benchmark/problems.json

# Phase gates (set to "true" only when phase is complete)
PHASE_0_COMPLETE=false
PHASE_1_COMPLETE=false
PHASE_2_COMPLETE=false
PHASE_3_COMPLETE=false
```

---

## 11. ARCHITECTURE SELECTION LOGIC

Implemented in `agents/forge/decision_tree.py`.
This is the authoritative decision tree. Forge must follow this exactly.

```
Input: mission_brief.json

if modality == "tabular":
    if num_rows < 1_000_000:
        if class_imbalance_ratio > 1:20:
            model = LightGBM
            imbalance_strategy = SMOTE or focal_loss
        elif class_imbalance_ratio > 1:5:
            model = LightGBM
            imbalance_strategy = class_weight
        else:
            model = LightGBM
            imbalance_strategy = none
    else:  # > 1M rows or complex interactions
        model = TabNet
elif modality == "text":
    if task_type == "classification":
        model = DistilBERT (fine-tuned)
    else:
        model = DistilBERT (generative head — future)
elif modality == "image":
    if task_type == "classification":
        model = EfficientNet-B0  # scale to B4 based on dataset size
    elif task_type == "detection":
        model = EfficientNet-B0 + detection head  # future

FALLBACK: if LightGBM produces poor results after 2 Optuna trials → switch to XGBoost
```

---

## 12. MEMORY ARCHITECTURE

### Short-Term: Redis
- **Type:** In-memory key-value + Streams
- **Lifetime:** Job duration + TTL (24 hours on ephemeral data)
- **Used for:** Job state, agent communication (pub/sub via Streams), checkpoint pointers
- **Key naming convention:**
  - `job:{job_id}:mission_brief` — mission_brief.json contents
  - `job:{job_id}:search_space` — Optuna search space config
  - `job:{job_id}:status` — current job status string
  - `job:{job_id}:checkpoint` — path to last valid checkpoint
  - `job:{job_id}:crash_count` — number of crashes this job

**⚠️ KNOWN GAP — Multi-Tenancy (Phase 0–2 Research Only):**
The current Redis key schema (`job:{job_id}:*`) uses job-level isolation only.
There is NO tenant-level isolation, no per-user rate limiting, and no auth layer.
This is intentional and acceptable for the graduation research environment (single user,
local Redis, no external traffic). For the commercial SaaS product, before Phase 4
production deployment, the following must be added:
- Key namespace: change to `tenant:{tenant_id}:job:{job_id}:*`
- Auth: API key validation middleware in the orchestrator's job submission endpoint
- Rate limiting: per-tenant job concurrency limit enforced before job enqueue
- Redis ACLs: per-tenant Redis user with key-pattern access restrictions
Do not implement these during Phases 0–2. Flag this section when beginning Phase 3.

### Long-Term: ChromaDB
- **Type:** Vector database (cosine similarity search)
- **Lifetime:** Permanent across jobs — this is the moat
- **Three collections:**
  - `patch_memory`: error description + patch text → vectors. Dissect queries this
    for K-nearest similar past errors before generating a new patch.
  - `architecture_memory`: architecture decision + outcome (final AUC, success/fail).
    Forge queries this to improve selection over time.
  - `tool_memory`: Python tool docstrings as vectors. Agents retrieve tools by
    semantic description.
- **Embedding model:** `all-MiniLM-L6-v2` via sentence-transformers
- **K for KNN retrieval:** K=3 (retrieve 3 most similar past patches/architectures)

---

## 13. CONCURRENCY MODEL — EXACT EXECUTION ORDER

This section is authoritative. When writing orchestrator or agent code, follow this exactly.

### 13.1 Agent Execution — Sequential vs Parallel

Agents are NOT all launched at startup. The orchestrator launches each agent when its
trigger event arrives. The execution order per job is strictly sequential between phases,
with ONE exception: Furnace and Dissect run concurrently during the training phase.

```
Job Submitted
      │
      ▼
  [Scout]          ← Runs alone. Blocking. Must complete before Forge starts.
      │ MISSION_BRIEF_READY
      ▼
  [Forge]          ← Runs alone. Blocking. Must complete before Furnace starts.
      │ TRAINING_SCRIPT_READY
      ▼
  [Furnace] ──────────────────────────────────────────────┐
      │                                                    │ (concurrent)
      │ CRASH_EVENT (conditional)                         │
      ▼                                                    │
  [Dissect] ── RESUME_TRAINING ──────────────────────────►│
      │                                                    │
      │ ESCALATE (if 3 failures) ──────────────► [Orchestrator marks job FAILED]
      │                                                    │
      │                              TRAINING_COMPLETE ◄──┘
      ▼
  [Arbiter]        ← Runs alone. Blocking. Must complete before Harbor starts.
      │ EVALUATION_PASS
      ▼
  [Harbor]         ← Runs alone. Then monitors indefinitely (drift loop).
      │ ENDPOINT_LIVE
      ▼
  Job Complete
```

Rules:
- Scout → Forge → (Furnace ‖ Dissect) → Arbiter → Harbor is the invariant order
- The orchestrator MUST NOT start Arbiter until it receives TRAINING_COMPLETE
- The orchestrator MUST NOT start Harbor until it receives EVALUATION_PASS
- EVALUATION_RETRY loops back to Forge only — Scout is NOT re-run on retry
- DRIFT_ALERT loops back to Scout — full pipeline re-runs with fresh data
- Multiple jobs from different users run as separate parallel pipelines, each with
  their own isolated Redis key namespace (`job:{job_id}:*`)

### 13.2 Consumer Group Design — Furnace ↔ Dissect Loop

This is the most complex interaction in the system. Read carefully.

Redis Streams consumer groups used:
```
Stream name         Consumer group          Consumers
─────────────────────────────────────────────────────────
furnace_feed        frontend_consumers      Next.js SSE feed reader
furnace_output      arbiter_consumers       Arbiter (one consumer)
furnace_crash       dissect_consumers       Dissect (one consumer)
dissect_output      furnace_consumers       Furnace (one consumer)
                    orchestrator_consumers  Orchestrator (monitors ESCALATE)
arbiter_output      harbor_consumers        Harbor (one consumer)
                    orchestrator_consumers  Orchestrator (monitors all decisions)
harbor_output       orchestrator_consumers  Orchestrator (monitors ENDPOINT_LIVE)
                    scout_consumers         Scout (monitors DRIFT_ALERT → new cycle)
```

Consumer group rules:
- Each stream has exactly one primary consumer per consumer group
- Consumer groups are created at job start by the orchestrator, not by the agents
- Agents use `XREADGROUP` with `BLOCK=0` (blocking read, waits indefinitely)
- After processing a message, agents ACK with `XACK` immediately
- Unacked messages are reclaimed after 30 seconds by the orchestrator health monitor
- If an agent crashes mid-processing, the orchestrator reclaims the pending message
  and restarts the agent from that message

### 13.3 Furnace ↔ Dissect Crash-Recovery Sequence Diagram

```
Furnace                  Redis Streams              Dissect
   │                          │                        │
   │── launch container ──────│                        │
   │── epoch 1 complete ─────►│ furnace_feed           │
   │── epoch 2 complete ─────►│ furnace_feed           │
   │                          │                        │
   │  [CRASH at epoch 3]      │                        │
   │                          │                        │
   │── save last checkpoint ──│                        │
   │── publish CRASH_EVENT ──►│ furnace_crash          │
   │── enter WAIT state ──────│                        │
   │   (blocks on RESUME)     │                        │
   │                          │◄── XREADGROUP ─────────│
   │                          │                        │── parse stack trace
   │                          │                        │── classify error
   │                          │                        │── query patch_memory (K=3)
   │                          │                        │── generate diff
   │                          │                        │── apply patch to script
   │                          │                        │── run sandbox test
   │                          │                        │
   │                          │   [Sandbox PASS]       │
   │                          │                        │── write patch_log entry
   │                          │                        │── publish RESUME_TRAINING
   │                          │◄───────────────────────│ dissect_output
   │◄── XREADGROUP ───────────│                        │
   │                          │                        │
   │── reload patched script  │                        │
   │── restore checkpoint ────│                        │
   │── resume from epoch 3 ──►│ furnace_feed           │
   │── epoch 4 complete ─────►│ furnace_feed           │
   │── training complete ─────►│ furnace_output        │
   │                          │                        │
   │                    [Sandbox FAIL — attempt 2]     │
   │                          │                        │── rollback patch
   │                          │                        │── try next strategy
   │                          │                        │── write patch_log (outcome=rollback)
   │                          │                        │── publish RESUME_TRAINING (attempt 2)
   │                          │                        │
   │                    [All 3 attempts failed]        │
   │                          │                        │── write patch_log (outcome=escalated)
   │                          │                        │── publish ESCALATE
   │◄── Orchestrator reads ESCALATE, marks job FAILED  │
   │── Furnace receives ESCALATE signal from Orch.     │
   │── Furnace kills container, releases resources     │
```

Invariants in this loop:
- Furnace is in WAIT state from the moment it publishes CRASH_EVENT until it
  receives RESUME_TRAINING or the orchestrator sends a KILL signal
- Dissect never publishes RESUME_TRAINING without first writing to patch_log
- The crash_attempt_number in CRASH_EVENT increments on each failure: 1, 2, 3
- On attempt 3 failure, Dissect publishes ESCALATE — never a 4th RESUME_TRAINING
- Furnace ONLY exits WAIT state on RESUME_TRAINING or orchestrator KILL — never on timeout

---

## 14. BUILD PHASES — CURRENT STATUS + GATES

### Phase 0 — Foundation (5 working days)
**Goal:** All 4 infrastructure components run independently and communicate via Redis.

Deliverables:
- [ ] Redis running locally with test producer/consumer (verify with `redis-cli ping`)
- [ ] Docker container that runs a hello-world training script
- [ ] Claude API tool-use hello world (one agent calls one tool and returns structured JSON)
- [ ] ChromaDB running with test collection (insert + retrieve one vector)
- [ ] GitHub repo, CI pipeline (GitHub Actions), branch strategy documented
- [ ] `.env.example` committed, `.env` in `.gitignore`
- [ ] All dependencies installed and `requirements.txt` pinned

**Gate to pass:** All 4 infrastructure components run independently AND communicate via Redis.
Do not start Phase 1 until this gate passes.

### Phase 1 — Scout + Forge + Furnace (6 working days)
**Goal:** Titanic dataset → trained LightGBM model, no error recovery, no human intervention.

Deliverables:
- [ ] Scout parses 3 dataset types and writes correct mission_brief.json
- [ ] Forge selects LightGBM + writes correct training_script.py for 5 test cases
- [ ] Furnace runs training, publishes live metrics to Redis Streams
- [ ] `tests/integration/test_titanic_e2e.py` passes with val AUC > 0.82

**Gate to pass:** Titanic problem completes without human intervention, val AUC > 0.82.
This test must stay green for the rest of the project.

### Phase 2 — Dissect + Arbiter + Harbor (5 working days)
**Goal:** Full pipeline including error recovery on 3 Kaggle datasets.

Deliverables:
- [ ] Dissect error taxonomy v1 (minimum 10 categories from taxonomy.py)
- [ ] Dissect successfully patches 5 deliberately injected errors (in `tests/fixtures/injected_errors/`)
- [ ] Arbiter computes full evaluation suite and makes correct PASS/RETRY decision
- [ ] Harbor deploys model to local Docker Compose serving stack with working /predict endpoint
- [ ] `tests/integration/test_three_kaggle_e2e.py` passes

**Gate to pass:** 3/3 Kaggle datasets complete with < 2 human interventions each.
Harbor endpoint serves correct predictions.

### Phase 3 — ChromaDB Memory + Orchestrator Hardening (5 working days)
**Goal:** ChromaDB memory working, Dissect learning from history, full pipeline bulletproof.

Deliverables:
- [ ] ChromaDB `patch_memory` collection: Dissect stores and retrieves similar past patches
- [ ] ChromaDB `architecture_memory` collection: Forge improves selection over time
- [ ] ChromaDB `tool_memory` collection: semantic tool retrieval working
- [ ] Orchestrator v2: concurrent Furnace ↔ Dissect loop fully wired
- [ ] ESCALATE → JOB_FAILED full handling: diagnostic report written, container killed
- [ ] `tests/integration/test_three_kaggle_e2e.py` passes on all 3 Kaggle datasets
- [ ] All pytest tests green

**Gate to pass:** All pytest green. 3/3 Kaggle datasets complete. Dissect successfully
uses past patch history from ChromaDB (K=3 retrieval demonstrated in logs).

### Phase 4 — Research Experiment + Paper (5 working days)
**Goal:** Research results ready for paper submission.

Deliverables:
- [ ] Next.js live feed frontend (SSE from Redis → browser)
- [ ] GKE deployment for Harbor (Phase 4 only, not before)
- [ ] PSI drift monitor live
- [ ] 50-problem benchmark run: 3 conditions (manual, no Dissect, with Dissect)
- [ ] Paper draft submitted to advisor
- [ ] Demo video for graduation presentation
- [ ] `research/patch_log.jsonl` populated with real experimental data

**Gate to pass:** Research experiment shows statistically significant reduction in human
interventions (Mann-Whitney U test, p < 0.05). Paper accepted by advisor.

---

## 15. CODING STANDARDS

### Python
- Python 3.11+
- Type hints on every function signature — no exceptions
- Pydantic models for all data structures that cross agent boundaries
- All agent tool functions must have a docstring describing: what it does, its parameters,
  its return type, and what Redis keys or files it reads/writes
- `async` / `await` for all I/O: Redis calls, Anthropic API calls, Docker SDK calls,
  ChromaDB calls
- Every tool function is independently unit-testable — no side effects hidden in
  module-level code

### Error Handling
- Every Anthropic API call wrapped in try/except with exponential backoff
- Every Docker SDK call wrapped in try/except — container failures must not crash the
  orchestrator
- Every Redis call wrapped in try/except — Redis outage must not crash the system silently
- All exceptions logged with job_id, agent name, and full traceback before re-raising

### CI/CD Pipeline

The CI pipeline runs on every push and PR via GitHub Actions. Defined in `.github/workflows/ci.yml`:

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
      chromadb:
        image: chromadb/chroma:0.5.0
        ports: ["8000:8000"]
        env: { ALLOW_RESET: "true" }

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install -r requirements.txt
      - run: |
          cp .env.example .env
          echo "ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}" >> .env
      - run: pytest tests/ -v --tb=short -x
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - run: |
          python3 -c "
          import ast, sys
          files = ['agents/scout/tools.py', 'agents/llm_client.py', 'bus/publisher.py']
          for f in files:
              try:
                  ast.parse(open(f).read())
                  print(f'{f}: OK')
              except SyntaxError as e:
                  print(f'{f}: SYNTAX ERROR — {e}')
                  sys.exit(1)
          "
        name: Syntax check
```

Branch protection requirements:
- PRs require passing CI before merge
- No direct commits to `main`
- Secrets (ANTHROPIC_API_KEY) stored in GitHub Secrets, never in code
- Redis and ChromaDB run as CI services (Docker containers), not full Docker Compose

### Pre-commit Hooks

Create `.pre-commit-config.yaml` at repo root:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ["--maxkb=500"]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix, --line-length=100]
      - id: ruff-format
        args: [--line-length=100]
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        args: [--ignore-missing-imports, --python-version=3.11]
        additional_dependencies: [pydantic]
```

Install with: `pip install pre-commit && pre-commit install`

### Logging Configuration

All agents use structured logging via Python's `logging` module with a consistent format:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Per-module loggers:
logger = logging.getLogger(__name__)

# All log lines must include job_id and agent_name context:
logger.info(f"[job={job_id}] Training complete | val_loss={val_loss:.4f}")
logger.error(f"[job={job_id}] Crash detected | exception={exc_type}: {exc_msg}")
```

Rules:
- Use `logging.getLogger(__name__)` per module — never `logging.root`
- Always include `job_id` in every log line
- ERROR and CRITICAL include the full traceback
- WARNING for recoverable issues (retry attempts, missing optional data)
- INFO for state transitions (agent started, event published, step complete)
- DEBUG for tool I/O (LLM responses, Redis payloads) — noisy, disabled in production
- Never log API keys, full Anthropic responses, or raw dataset values
- Log files written to `outputs/{job_id}/agent.log` by the orchestrator

### Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants and event types: `UPPER_SNAKE_CASE`
- Redis keys: `{entity}:{id}:{field}` (e.g., `job:{job_id}:mission_brief`)
- ChromaDB collection names: `snake_case` (e.g., `patch_memory`)

### Git
- Branch naming: `{phase}/{agent-or-component}/{short-description}`
  e.g., `phase1/scout/modality-detection` or `phase0/bus/redis-streams-setup`
- Commit messages: `[AGENT/COMPONENT] Short description`
  e.g., `[Scout] Add image modality detection` or `[Bus] Implement CRASH_EVENT publisher`
- No direct commits to `main`. All changes via PR.
- PRs require passing CI (pytest) before merge.
- Never commit `.env`, model checkpoints, or dataset files.
- Create `.github/CODEOWNERS` to enforce Section 4 ownership (solo build → all @mohamed):
  ```
  * @mohamed
  ```

---

## 16. INTEGRATION CHECKPOINTS

Every two weeks, run the end-to-end integration test on the Titanic dataset.
Test passes only if the full pipeline completes without a human manually intervening.

Integration test lives in: `tests/integration/test_titanic_e2e.py`

The test verifies:
1. Scout produces a valid mission_brief.json with all required fields
2. Forge produces a runnable training_script.py (no syntax errors)
3. Furnace runs training and publishes at least one EPOCH_COMPLETE event
4. Arbiter produces eval_report.json with AUC > 0.82
5. Harbor produces a local serving endpoint that responds to /predict with valid output
6. All events in the correct order appear in Redis Streams

If any step fails, do not merge any other PRs until it is fixed.

---

## 17. WEEKLY RHYTHM

Monday: 15-min kickoff. Each person states the single deliverable they will complete.
Wednesday: 30-min check-in. Flag blockers, adjust scope if needed.
Friday: 45-min demo. Every deliverable is demonstrated live. No demo = not done.

This is non-negotiable. "I was working on it" is not a Friday deliverable.

---

## 18. WHAT TO DO WHEN YOU ARE UNSURE

If you (Claude Code) are unsure about any of the following, STOP and ask before writing code:

- Which agent should own a piece of logic you're about to write
- Whether a new Redis key or event type is needed
- Whether mission_brief.json needs a new field
- Whether a new dependency needs to be added to requirements.txt
- Whether something should be in short-term (Redis) or long-term (ChromaDB) memory
- Whether a file path matches the directory structure in Section 2
- Whether GKE deployment should be triggered (answer: not before Phase 3)

When in doubt, the answer is always: follow the schemas in Sections 5, 6, and 7 exactly,
and do not invent new fields or event types. Check Section 9 before defining any new
Prometheus metric. Check Section 13 before writing any concurrency or consumer group logic.

---

## 19. RESEARCH EXPERIMENT — DO NOT MODIFY

The research experiment comparing:
- Condition A: Human ML engineer (manual baseline)
- Condition B: Prometheus Swarm WITHOUT Dissect
- Condition C: Prometheus Swarm WITH Dissect (full system)

Measured on 50 ML problems. Metrics: patch success rate, human interventions per deployment,
time to successful deployment, patch acceptance rate vs. patch history size.

Statistical test: Mann-Whitney U test (non-parametric, does not assume normality).
Required for publication at MSR / ASE 2026.

The `research/patch_log.jsonl` is the dataset for this experiment.
Never truncate it. Never edit past entries. Only append via Redis RPUSH → patch_log_writer.
See Section 7 for the exact write path and schema.

Target conferences: MSR 2026 (acceptance rate ~25%), ASE 2026 (acceptance rate ~22%).

---

## 20. THE STARTUP CONTEXT

Prometheus Swarm is the architectural foundation for a commercial product.

Business model tiers:
- Starter: $99/month — 5 deployments/month
- Professional: $499/month — 20 deployments/month
- Team: $2,000/month — 100 deployments/month, audit log export
- Enterprise: $10k-$50k/month — private deployment, SLA, compliance

The competitive moat: every job run adds to patch_memory and architecture_memory in
ChromaDB. The system improves with usage. A competitor cannot catch up without running
the same number of jobs.

This connects to Nexora (nexoraintel.com) — the existing production RAG SaaS.
Prometheus Swarm is the next Nexora product: ML-as-a-service.

Every architectural decision made during the graduation project is a production decision.
Build as if this will serve paying customers. Because it will.

---

## 21. COMMERCIALIZATION READINESS

These items are NOT implemented during Phases 0–2 (graduation research). They are
architectural requirements for the commercial product and must be designed-for even
if not implemented yet.

### 21.1 Shadow Mode
- Before allowing full auto-execution for paying customers, the system must support
  a **Shadow Mode**: the pipeline runs end-to-end, but Harbor does NOT deploy the model
  automatically. Instead, the endpoint is staged and the user receives a notification
  to review and approve deployment.
- Shadow Mode is toggled per-tenant via environment variable `SHADOW_MODE=true`.
- Logged as `deployment_mode: "shadow"` in the job record.

### 21.2 Kill Switches
- **Job-level kill switch:** `POST /api/jobs/{job_id}/cancel` → sets
  `job:{job_id}:status = CANCELLED`, sends KILL to Furnace container.
- **System-level kill switch:** `POST /api/system/pause` → stops accepting new jobs,
  lets in-flight jobs complete. `POST /api/system/halt` → force-kills all containers.
- Both kill switches are orchestrator-level, not agent-level.

### 21.3 Cost Tracking
- Every Anthropic API call must log `input_tokens`, `output_tokens`, and estimated
  USD cost to Redis key `job:{job_id}:api_cost`.
- Orchestrator aggregates per-job cost at job completion.
- This feeds the pricing model: cost + margin = price per deployment.

### 21.4 Governance & Audit Trail
- Every agent action (LLM call, tool call, event published) is logged to
  `outputs/{job_id}/audit_log.jsonl` with timestamp, agent name, action type,
  and input/output summary.
- Audit log is exportable via API for Enterprise tier compliance.

### 21.5 Key Metrics for Product-Market Fit
- **Time-to-Value:** Time from job submission to ENDPOINT_LIVE (or ESCALATE).
  Target: < 30 minutes for tabular, < 2 hours for text/image.
- **Automation Rate:** `1 - (escalated_jobs / total_jobs)`. Target: > 85%.
- **Intervention Rate:** Human interventions per 100 jobs. Target: < 5.

### 21.6 Open-Source Dataset Strategy
- After the paper is accepted, release `research/patch_log.jsonl` as an open-source
  dataset on HuggingFace Datasets Hub.
- Anonymise all file paths and job IDs before release.
- This establishes Prometheus Swarm as a research benchmark and attracts community
  contributions to the error taxonomy.

### 21.7 Differentiation from Amazon Auto2ML
- Auto2ML (Amazon, 2025) automates model selection but does NOT handle runtime crash
  recovery. Prometheus Swarm's Dissect agent is a novel contribution.
- The paper's framing: "Auto2ML stops at architecture selection. We close the loop
  with autonomous failure recovery."
- In commercial positioning: "The only ML-as-a-service that fixes its own crashes."

---

## 22. WINDOWS DEVELOPMENT NOTES

Mohamed's primary development machine runs **Windows 11**. All scripts and commands
must work cross-platform. When a Linux-only tool is referenced, provide the Windows
alternative.

### 22.1 Python Virtual Environment
```bash
# Linux/macOS:
source .venv/bin/activate

# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Windows CMD:
.\.venv\Scripts\activate.bat
```

### 22.2 File Locking
- **Do NOT use `fcntl`** — it does not exist on Windows.
- Use `filelock` (pip package) for cross-platform file locking.
- `patch_log_writer.py` uses `from filelock import FileLock` instead of `import fcntl`.

### 22.3 Docker Volume Mounts
- Docker Desktop on Windows uses Windows-style paths for bind mounts.
- The Docker SDK for Python handles path translation automatically.
- If using `docker-compose.yml`, use relative paths (`./data:/app/data`) which work
  on both platforms.

### 22.4 Shell Commands
| Linux/macOS | Windows PowerShell |
|---|---|
| `source .venv/bin/activate` | `.\.venv\Scripts\Activate.ps1` |
| `touch file.txt` | `New-Item file.txt -ItemType File` |
| `mkdir -p path/to/dir` | `New-Item -Path path\to\dir -ItemType Directory -Force` |
| `curl http://...` | `Invoke-WebRequest http://...` or install `curl` via winget |
| `export VAR=value` | `$env:VAR = "value"` |
| `python3` | `python` (on Windows, `python3` may not be aliased) |
| `kill <pid>` | `Stop-Process -Id <pid>` |

### 22.5 Path Handling in Code
- Always use `pathlib.Path` for file operations — never string concatenation with `/`.
- Always use `os.path.abspath()` for paths passed to Docker SDK.
- Never use `\\` literal backslashes in Python code — `pathlib` handles this.

### 22.6 Windows asyncio Event Loop Workaround
Python's default `ProactorEventLoop` on Windows does not support subprocess + `asyncio` in all cases.
If you encounter `NotImplementedError` when using `asyncio` subprocess calls alongside Redis or Docker,
add this at the top of your entry point (e.g., `orchestrator/runtime.py`):

```python
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

This switches to the `SelectorEventLoop`, which Windows supports natively and handles socket I/O without issues.
Only needed for the orchestrator entry point — individual agent processes using pure async Redis calls work fine
with the default loop.

---

*End of CLAUDE.md — Prometheus Swarm v1.2*
*Last updated: 2026-06-29 | Mohamed Mosad Ghonaim | Alamein International University | Nexora Lab*
*Any modification to this file must be reviewed by the AI Lead before merging.*