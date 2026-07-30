# CLAUDE.md — Prometheus Swarm

> Last full audit: 2026-07-25. Bug fix sprint: 2026-07-25 (all 12 items
> resolved — 6 retry bugs, 2 Cockpit TUI bugs, 5 documentation/config gaps).
> This document is a complete, verified snapshot of the project as of this date.
> Every claim below was confirmed by reading the actual source code, not inferred
> from filenames, comments, or prior docs.

---

## 1. Project Identity & Purpose

**Prometheus Swarm** is an autonomous multi-agent system that accepts a raw natural-language description of an ML problem and a dataset, then returns a fully trained, evaluated, and live-served model endpoint — without human intervention.

**Owner:** Mohamed Mosad Ghonaim — solo builder.

**Language split:** ~99% Python, ~1% TypeScript (Next.js frontend). Python 3.11+ target.

**Goal:** ML-as-a-service SaaS + research publication at MSR 2026 or ASE 2026. The core research contribution is **Dissect**: autonomous self-patching of ML training failures.

**Tagline:** "You describe the task. The swarm does the rest."

---

## 2. High-Level Architecture

Six specialized AI agents coordinate through a Redis Streams message bus. No agent calls another directly. Each agent has its own system prompt, tools, and memory scope.

### The Six Agents

| Agent | Role | Trigger | Output |
|-------|------|---------|--------|
| **Scout** | Perceiver | Job submission → `MissionBrief` + event | `MISSION_BRIEF_READY` |
| **Forge** | Architect | `MISSION_BRIEF_READY` → training script | `TRAINING_SCRIPT_READY` |
| **Furnace** | Trainer | `TRAINING_SCRIPT_READY` → trained model | `TRAINING_COMPLETE` / `CRASH_EVENT` |
| **Dissect** | Debugger | `CRASH_EVENT` → patched script | `RESUME_TRAINING` / `ESCALATE` |
| **Arbiter** | Evaluator | `TRAINING_COMPLETE` → PASS/RETRY/FAIL | `EVALUATION_PASS` / `EVALUATION_RETRY` / `ESCALATE` |
| **Harbor** | Deployer | `EVALUATION_PASS` → live endpoint | `ENDPOINT_LIVE` |

### Orchestration pattern

**Sequential with a crash-recovery loop:** Scout → Forge → Furnace ⟷ Dissect (loop) → Arbiter → Harbor. If Arbiter says RETRY, the loop goes back to Forge with a new strategy. If Dissect or Arbiter escalate, the job is marked FAILED.

### Communication

All inter-agent communication happens through **Redis Streams**. Agents don't import each other. The orchestrator manages consumer groups and stream names. Agents publish typed Pydantic events.

### Memory

- **Redis** (key-value + Streams): Job state, mission briefs, search spaces, patch log queue, API cost tracking
- **ChromaDB** (vector store): Patch memory, architecture memory, tool memory, experience memory — each a separate collection

---

## 3. Repository Structure

All paths below exist in the repository. Top-level structure is flat (agents/, bus/, contracts/, orchestrator/, etc. are all at root), NOT nested inside prometheus/.

```
prometheus-swarm/
│
├── .env / .env.example        ← Environment config (gitignored)
├── .gitignore
├── .pre-commit-config.yaml    ← Pre-commit hooks (ruff check)
├── AUDIT.md                   ← Bug fix sprint doc (6 bugs, July 2026)
├── CLAUDE.md                  ← THIS FILE
├── PLAN.md                    ← Full build plan (3150+ lines, Phases 0-3+)
├── Prometheus_CLI_UX_Design_Book.md  ← CLI design spec (~34-page spec)
├── Prometheus_CLI_Implementation_Master_Prompt.md  ← CLI implementation guide
├── RESULTS_SCHEMA.md          ← Benchmark result schema specification
├── README.md                  ← Project README (minimal, slightly stale)
├── deploy_update_app.py       ← Deployment update script
├── docker-compose.yml         ← Redis + ChromaDB + optional observability stack
├── Dockerfile                 ← Main app Dockerfile
├── Makefile                   ← Dev commands (lint, test, format, docker)
├── pyproject.toml             ← Metadata, entry point: prometheus = prometheus.main:cli
├── requirements.txt           ← Pinned dependencies (50 lines)
├── start.ps1                  ← Windows Docker startup script
├── uv.lock                    ← UV lock file
│
├── agents/                    ← ⭐ Six AI agent implementations
│   ├── __init__.py
│   ├── base.py (30 lines)     ← BaseAgent ABC: agent_name, run(), call_llm()
│   ├── llm_client.py (108 lines)  ← get_llm_response() — Anthropic Claude wrapper
│   │
│   ├── scout/                 ← Perceiver (4 files, ~1668 lines total)
│   │   ├── agent.py           ← ScoutAgent.run(): detect modality, run EDA, build MissionBrief
│   │   ├── tools.py (606)     ← detect_modality(), run_eda(), infer_task_type(), etc.
│   │   ├── reasoning.py (675) ← Pure deterministic reasoning engine (no LLM): 10 reason_*() functions
│   │   ├── prompts.py (62)    ← SCOUT_SYSTEM_PROMPT
│   │
│   ├── forge/                 ← Architect (12 files + 10 templates, ~4979 lines)
│   │   ├── agent.py (536)     ← ForgeAgent.run(): architecture selection, multi-strategy script gen
│   │   ├── tools.py (1353)    ← write_training_script(), define_optuna_space(), 5 f-string generators
│   │   ├── decision_tree.py   ← select_architecture(): heuristic decision tree
│   │   ├── planner.py (531)   ← create_plan(): EngineeringPlan from Scout brief
│   │   ├── template_renderer.py (364) ← Jinja2 rendering + ast.parse validation
│   │   ├── confidence_router.py (49) ← template/cache/llm strategy selector
│   │   ├── confidence_classifier.py  ← Confidence classification model
│   │   ├── static_prevention.py (574) ← apply_static_prevention() text transformations
│   │   ├── prevention.py (527)       ← Redis-backed error prevention rules
│   │   ├── script_fingerprint.py (202) ← SHA-256 script fingerprinting
│   │   ├── quality_feedback.py (865)  ← Redis-backed error statistics per architecture
│   │   ├── registry.py (287)   ← ArchitectureRegistry — single source of truth
│   │   └── templates/          ← 10 .jinja files (lightgbm, xgboost, tabnet, distilbert, efficientnet)
│   │
│   ├── furnace/               ← Trainer (3 files, ~867 lines)
│   │   ├── agent.py (809)     ← FurnaceAgent.run(): Docker/process management, crash handling
│   │   ├── tools.py (47)      ← launch_training_container(), monitor_loss()
│   │   └── prompts.py (11)    ← FURNACE_SYSTEM_PROMPT
│   │
│   ├── dissect/               ← Debugger (16 files, ~4898 lines)
│   │   ├── agent.py (947)     ← DissectAgent.handle_crash(): 5-level cascade
│   │   ├── routing.py (653)   ← run_cascade(): 5-level cascade router
│   │   ├── taxonomy.py (552)  ← 31 error categories (TaxonomyEntry, classify_error)
│   │   ├── rules.py (667)     ← Level 0 deterministic repair functions (10 fix_*())
│   │   ├── repair_templates.py (526) ← Compiled repair patterns promoted from LLM
│   │   ├── repair_cache.py (118)     ← MD5-based fingerprint cache
│   │   ├── knowledge_store.py (99)   ← Redis LLM knowledge queue for research data
│   │   ├── models.py (83)     ← CrashReport dataclass
│   │   ├── patch_log.py (39)  ← write_patch_log(): Redis RPUSH to patch_log_queue
│   │   ├── fingerprint.py (129) ← SHA-256 fingerprint + Redis FingerprintStore
│   │   ├── governor.py (111)  ← BudgetGovernor: per-fingerprint budget enforcement
│   │   ├── budget.py (84)     ← RepairBudget: per-job budget
│   │   ├── validation.py (170) ← validate_patch_pre() / validate_patch_post()
│   │   ├── ui.py (172)        ← Rich console output for CLI
│   │   └── prompts.py (52)    ← DISSECT_SYSTEM_PROMPT
│   │
│   ├── arbiter/               ← Evaluator (9 files, ~1789 lines)
│   │   ├── agent.py (396)     ← ArbiterAgent.on_training_complete()
│   │   ├── decision.py (77)   ← make_decision(): PASS/RETRY/FAIL logic
│   │   ├── evaluator.py (256) ← load_checkpoint_data(), evaluate()
│   │   ├── controller.py (291)← build_constraints_from_brief(), evaluate_and_decide()
│   │   ├── tools.py (184)     ← compute_classification/regression_metrics()
│   │   ├── report.py (330)    ← save_evaluation_report(), save_evaluation_plots()
│   │   ├── ui.py (121)        ← Rich console rendering
│   │   └── prompts.py (24)    ← ARBITER_SYSTEM_PROMPT
│   │
│   └── harbor/                ← Deployer (5 files, ~2090 lines)
│       ├── agent.py (309)     ← HarborAgent.on_evaluation_pass()
│       ├── tools.py (694)     ← serialize_to_onnx(), generate_fastapi_app(), deploy_local_compose()
│       ├── serving_template.py (355) ← FastAPI serving template
│       ├── artifact_validator.py (708) ← verify_deployment(): 6-phase validation
│       └── prompts.py (24)    ← HARBOR_SYSTEM_PROMPT
│
├── prometheus/                ← CLI application package
│   ├── __main__.py            ← Entry: from prometheus.main import cli; cli()
│   ├── main.py (327)          ← click.Group with 13 command groups + 16 redirect stubs + REPL
│   ├── repl.py (303)          ← Interactive REPL mode
│   │
│   ├── cli/                   ← All CLI command implementations (27 .py files)
│   │   ├── __init__.py        ← Re-exports 12 CLI entry points
│   │   ├── mission/           ← Mission command group (1158-line __init__.py + 4 support files)
│   │   │   ├── __init__.py    ← @click.group 'mission' with 9 subcommands: new, list, status, watch, resume, cancel, report, replay, logs
│   │   │   ├── session.py     ← MissionSession dataclass + singleton tracker
│   │   │   ├── state_logger.py ← log_mission_state()
│   │   │   ├── ui.py (686)    ← Rich live-updating UI for all 6 agent phases
│   │   │   └── ui_harbor.py   ← Harbor-specific completion UI
│   │   ├── agent.py           ← @click.group 'agent' (list, inspect, trace)
│   │   ├── benchmark.py       ← @click.group 'benchmark' (summary, wins, stats)
│   │   ├── config.py          ← @click.group 'config' (list, set, check, edit, show)
│   │   ├── daemon.py          ← @click.command 'daemon' (start, stop, status, restart, logs)
│   │   ├── deploy.py          ← @click.group 'deploy' (list, logs, stop, predict)
│   │   ├── evaluate.py        ← @click.group 'evaluate'
│   │   ├── explain.py         ← @click.command 'explain'
│   │   ├── init.py            ← @click.command 'init' — first-run wizard
│   │   ├── job.py             ← @click.group 'job' (submit, list, status, cancel)
│   │   ├── logs.py            ← @click.group 'logs' (tail, show)
│   │   ├── memory.py          ← @click.group 'memory' (stats, search)
│   │   ├── model.py           ← @click.group 'model' (list, show, export)
│   │   ├── output.py          ← Three-mode output contract (interactive/plain/json)
│   │   ├── planner.py         ← @click.group 'planner'
│   │   ├── plugin.py          ← @click.group 'plugin' (install, remove, list)
│   │   ├── profile.py         ← @click.group 'profile' (list, save, switch, inspect, delete)
│   │   ├── provider.py        ← @click.group 'provider' (add, list, current)
│   │   ├── replay.py          ← @click.command 'replay'
│   │   ├── report.py          ← @click.command 'report'
│   │   ├── reproduce.py       ← @click.group 'reproduce'
│   │   ├── solve.py           ← @click.command 'solve' — submits to event-driven orchestrator
│   │   ├── swarm.py           ← @click.group 'swarm' (status, topology)
│   │   ├── system.py          ← help_cmd, doctor_cmd, version_cmd
│   │   ├── tool.py            ← @click.group 'tool' (list, inspect)
│   │   └── workspace.py       ← @click.group 'workspace' (init, info, scan, status)
│   │
│   ├── services/              ← Service implementations (9 files)
│   │   ├── app_context.py     ← AppContext — lazy singleton container
│   │   ├── agent_service.py   ← AgentService: knows the 6 agent roles
│   │   ├── config_service.py  ← ConfigService: reads/writes .env with credential-aware redaction
│   │   ├── job_service.py     ← JobService: connects to Redis
│   │   ├── memory_service.py  ← MemoryService: ChromaDB + Redis stats
│   │   ├── provider_service.py← ProviderService: API key management
│   │   ├── profile_service.py ← ProfileService: env profiles
│   │   └── workspace_service.py ← WorkspaceService: project root detection
│   │
│   ├── contracts/             ← Service interfaces (7 ABC files)
│   │   ├── iagent_service.py, iconfig_service.py, ijob_service.py,
│   │   ├── imemory_service.py, iprovider_service.py, iworkspace_service.py
│   │
│   ├── core/                  ← Core infrastructure (9 files)
│   │   ├── project.py, pipeline.py (deprecated), live_progress.py,
│   │   ├── docker.py, config.py, serving.py, redis.py, submission.py
│   │
│   ├── dto/                   ← Data transfer objects (5 files)
│   ├── models/                ← Domain model dataclasses (5 files)
│   ├── schemas/               ← Config schemas (4 files)
│   ├── mission/               ← Mission parsing (4 files: models, parser, validator)
│   ├── planner/               ← Execution plan compiler (4 files)
│   ├── plugins/               ← Plugin system (5 files)
│   ├── registry/              ← Command registry (4 files, 1079-line _build())
│   └── utils/                 ← Utilities (8 files)
│       ├── commands.py        ← AliasedGroup: Click with aliases + fuzzy suggestion
│       ├── compat.py          ← check_python, check_os, check_deps
│       ├── exit_codes.py      ← ExitCode IntEnum
│       ├── log.py             ← setup_logging()
│       ├── slugs.py           ← Human-friendly slug generation
│       ├── telemetry.py       ← Command execution telemetry
│       └── docs_gen.py        ← Command docs generator
│
│   └── ui/                    ← UI rendering (not the Cockpit TUI)
│       ├── cockpit/           ← Textual TUI application (4 files)
│       │   ├── app.py (684)   ← CockpitApp: live TUI dashboard
│       │   ├── widgets.py (1415) ← 11 widget types
│       │   ├── consumer.py (117) ← Read-only Redis consumer
│       │   └── trace_replay.py ← Saved trace replay
│       ├── components/        ← Reusable Rich components
│       ├── renderers/         ← Output format renderers
│       ├── *.py               ← Scout UI, Forge UI, Furnace UI, tables, theme, etc.
│
├── bus/                       ← Redis Streams message bus
│   ├── events.py              ← 11 event type constants + 9 stream names + 8 consumer group names
│   ├── publisher.py           ← publish(): XADD to stream
│   ├── consumer.py            ← consume_one(), consume_loop(), ensure_consumer_group()
│   └── checkpoint.py          ← Stream checkpointing
│
├── contracts/                 ← Domain models + typed event schemas + state machine
│   ├── domain.py              ← SCHEMA_VERSION_V1, base types
│   ├── events.py              ← 16 typed EventPayload subclasses (Pydantic v2)
│   ├── state.py               ← MissionPhase enum (20 values), transition matrix, MissionState
│   ├── errors.py              ← Domain error types
│   └── protocols.py           ← Protocol classes
│
├── orchestator/               ← Job orchestration [sic: directory is spelled 'orchestator']
│   ├── runtime.py (1082)      ← Main orchestration loop
│   ├── job_runner.py          ← Job lifecycle management
│   ├── health_monitor.py      ← Agent health monitoring (heartbeat, restart)
│   ├── mission_report.py      ← Mission report generation
│   ├── patch_log_writer.py    ← BLPOP from Redis → JSONL file
│   └── report_generator.py    ← Report generation utilities
│
├── runtime/                   ← Retry engine + execution helpers
│   ├── models.py (588)        ← Result, Context, Error types, MissionState (duplicate of contracts/state.py)
│   ├── paths.py               ← Path resolution
│   ├── retry_engine.py        ← Retry execution engine
│   ├── retry_orchestrator.py (777) ← Orchestrated retry logic
│   ├── retry_strategy.py      ← Retry strategy definitions
│   ├── retry_state.py         ← Retry state tracking
│   ├── capability_registry.py ← Agent capability registry
│   ├── ui_retry.py            ← UI retry integration
│   └── retry_log.py           ← Retry logging
│
├── shared/                    ← Shared utilities
│   ├── config.py              ← Configuration loading (pydantic-settings)
│   ├── settings.py            ← Application settings
│   ├── logging.py             ← Structured logging (JSON + console)
│   ├── cache.py               ← Caching utilities
│   └── console.py             ← Rich console output
│
├── memory/                    ← Memory layer (Redis + ChromaDB)
│   ├── redis_client.py        ← Singleton async Redis client
│   ├── chroma_client.py       ← ChromaDB connection + collection helpers
│   ├── schemas.py             ← Memory record schemas
│   ├── embeddings.py          ← Embedding generation
│   └── collections/           ← 3 collections: patch_memory, architecture_memory, tool_memory
│
├── evaluation/                ← Evaluation framework
│   ├── core.py, suite.py, metrics/
│
├── training/                  ← Training environment
│   ├── docker_manager.py (314)← Container lifecycle
│   ├── checkpoint_manager.py (44) ← Checkpoint save/restore
│   ├── label_normalizer.py (149) ← Deterministic label encoding across retries
│   └── base_training_image/   ← Dockerfile for training containers
│
├── serving/                   ← Model serving
│   ├── onnx_runtime.py (47)   ← ONNX model loading and inference
│   ├── drift_monitor.py (93)  ← PSI-based drift detection
│   ├── metrics.py (75)        ← Prometheus metrics for serving
│   └── docker/                ← Serving container Dockerfile
│
├── UI/                        ← Cockpit TUI (top-level, separate from prometheus/ui/)
│   └── [TUI application files]
│
├── tests/                     ← ⭐ Test suite (77 files, 68 .py test files)
│   ├── __init__.py
│   ├── unit/                  ← 65 test files (fast, no external deps)
│   │   ├── agents/            ← Per-agent tests (scout, forge, furnace, dissect, arbiter, harbor)
│   │   ├── contracts/         ← State machine tests
│   │   ├── bus/               ← Event bus tests
│   │   ├── runtime/           ← Retry engine tests
│   │   ├── shared/            ← Memory tests
│   │   ├── cockpit/           ← TUI tests (5 files)
│   │   ├── cli/               ← CLI command tests
│   │   ├── planner/           ← Planner tests
│   │   └── validation/        ← Research validation tests
│   ├── integration/           ← 13 files (Redis, Docker required)
│   │   ├── test_titanic_e2e.py, test_three_kaggle_e2e.py
│   │   ├── test_furnace_dissect_loop.py, test_dissect_sandbox_docker.py
│   │   └── test_harbor_serving.py, test_bus_e2e.py, etc.
│   ├── fixtures/              ← Test data (titanic.csv, 5 injected_error scripts, fuzz datasets)
│   ├── services/              ← Service-layer tests (6 files)
│   ├── validators/            ← Registry validation
│   └── research/              ← (empty — no test files)
│
├── research/                  ← Research experiment framework (15 .py files)
│   ├── benchmark/             ← problems.json (50 problems), baseline_v1.json, results/
│   ├── campaigns/             ← 15 campaign directories (pilot-v1, smoke-v2, verify-v3, etc.)
│   ├── validation/            ← Experiment tracking (models, runner, tracker, metrics, statistics)
│   ├── engineering/           ← Engineering dashboard
│   ├── run_benchmark.py (904) ← Main benchmark runner: Conditions A/B/C
│   ├── run_campaign.py (445)  ← Campaign runner (N runs, learning curves)
│   ├── run_ablation.py (579)  ← Ablation: 7 configs, all problems
│   ├── statistical_analysis.py (245) ← Mann-Whitney U + McNemar + Cohen's h
│   └── ... (analyze_ablation.py, analyze_campaign.py, compare_baselines.py, etc.)
│
├── scripts/                   ← Generated training scripts (output directory)
├── outputs/                   ← Job outputs (models, checkpoints, reports, logs)
├── data/                      ← Dataset files
├── docs/                      ← Documentation
│   ├── ADR/                   ← Architecture Decision Records
│   ├── ARCHITECTURE.md        ← Architecture overview
│   ├── CONVENTIONS.md         ← Coding conventions
│   ├── commands/              ← Generated CLI command docs
│   └── ERROR_TAXONOMY.md      ← Error taxonomy reference
├── frontend/                  ← Next.js dashboard (scaffolded)
│   ├── package.json           ← Next.js 14, React 18, Tailwind
│   └── src/app/               ← Routes: feed, jobs/[id], drift, dashboard, missions, etc.
├── infra/                     ← Infrastructure configs
│   ├── kubernetes/, helm/, monitoring/
└── .github/workflows/ci.yml   ← GitHub Actions CI
```

---

## 4. Core Concepts & Terminology (Glossary)

### Mission
A top-level workflow that takes a problem description + dataset through all 6 agents to a deployed endpoint. Created via `mission new`. Each mission gets a UUID `job_id` and an optional human-readable slug (e.g. "swift-falcon").

### Agent
One of six autonomous AI workers that perform a specific phase of the ML pipeline. Each agent runs in its own process, reads from Redis Streams, writes to Redis + ChromaDB, and publishes events.

### Canonical Mission Phases (20 values)
Defined in `contracts/state.py:MissionPhase`:

| Phase | Meaning |
|-------|---------|
| `MISSION_CREATED` | Job submitted, waiting to start |
| `SCOUT_RUNNING` | Scout is analyzing problem + dataset |
| `SCOUT_COMPLETED` | Scout finished, MissionBrief ready |
| `FORGE_RUNNING` | Forge is generating training script |
| `FORGE_COMPLETED` | Forge finished, script + search space ready |
| `FURNACE_RUNNING` | Furnace is training the model |
| `FURNACE_COMPLETED` | Training completed successfully |
| `TRAINING_FAILED` | Training crashed irrecoverably |
| `DISSECT_RUNNING` | Dissect is debugging a crash |
| `DISSECT_COMPLETED` | Dissect applied a patch, ready to resume |
| `ARBITER_RUNNING` | Arbiter is evaluating the model |
| `ARBITER_COMPLETED` | Arbiter made a decision |
| `RETRY_PENDING` | Waiting to begin retry sequence |
| `RETRY_RUNNING` | Retry sequence in progress |
| `RETRY_COMPLETED` | Retry complete, returning to Arbiter |
| `MISSION_PASSED` | Model passed evaluation threshold |
| `HARBOR_DEPLOYING` | Harbor is deploying the model |
| `HARBOR_COMPLETED` | Model deployed, endpoint live |
| `SCOUT_RETRAIN` | Loop back to Scout for retraining |
| `CANCELLED` | User cancelled the job |
| `MISSION_FAILED` | Terminal failure |

### Typed Events (16 types)
Defined in `contracts/events.py` as Pydantic `EventPayload` subclasses: `MissionBriefReadyEvent`, `TrainingScriptReadyEvent`, `EpochCompleteEvent`, `TrainingCompleteEvent`, `CrashEventPayload`, `ResumeTrainingEvent`, `EscalateEvent`, `EvaluationPassEvent`, `EvaluationRetryEvent`, `EvaluationFailedEvent`, `JobFailedEvent`, `EndpointLiveEvent`, `PlanCreatedEvent`, `PlanCompletedEvent`, `PlanFailedEvent`, `DriftAlertEvent`, `AgentEventPayload`.

### Stream Names (11 streams)
Defined in `bus/events.py`: `scout_output`, `forge_output`, `furnace_feed`, `furnace_output`, `furnace_crash`, `dissect_output`, `arbiter_output`, `harbor_output`, `orchestrator_output`, plus `agent_events` and `agent_thinking` for the Cockpit.

### Dissect Cascade (5 levels)
1. **Level 0 — Deterministic Rules** (`rules.py`): 10 regex-based repair functions
2. **Level 1 — Compiled Templates** (`repair_templates.py`): Pre-compiled repair patterns
3. **Level 2 — Repair Cache** (`repair_cache.py`): MD5-based fingerprint cache
4. **Level 3 — Patch Memory** (`knowledge_store.py`): ChromaDB semantic search
5. **Level 4 — LLM Reasoning**: Full LLM call with error context

### Cockpit
The live TUI dashboard (`prometheus/ui/cockpit/app.py`). Textual-based, shows real-time agent status, thinking tokens, logs, and event timeline. Launched via `prometheus` or as standalone.

### CLI Command Nouns (13 groups)
`mission`, `agent`, `workspace`, `model`, `provider`, `config`, `plugin`, `benchmark`, `deploy`, `evaluate`, `job`, `memory`, `planner` — plus system commands `init`, `doctor`, `version`, `help`, `daemon` and 16 backward-compat redirect stubs.

### Retry Engine
The `runtime/` package: orchestrates retry attempts across agents. Key classes: `RetryOrchestrator`, `RetryContext`, `RetryState`, `CapabilityRegistry`. Supports 4 strategies: exponential backoff, immediate, graceful degradation, fallback.

---

## 5. CLI / TUI Specification vs. Actual Implementation

### CLI Entry Point
- **Spec:** `prometheus` (console_scripts) or `python -m prometheus`
- **Actual:** `prometheus/main.py` — click.Group with `AliasedGroup`. Falls back to REPL if no subcommand given in TTY.
- **Status:** ✅ Working

### Command Nouns

| Command | Syntax | Flags | Actual Behavior | Status |
|---------|--------|-------|----------------|--------|
| **mission** | `mission <subcommand>` | `--file`, `--target`, etc. | 9 subcommands: new, list, status, watch, resume, cancel, report, replay, logs. `new` submits to orchestrator. `watch` shows live Rich UI. | ✅ Verified in `cli/mission/__init__.py` (1158 lines) |
| **agent** | `agent list/inspect/trace` | None | Lists 6 agents, inspects details, traces job path. Uses `AgentService`. | ✅ Verified in `cli/agent.py` |
| **workspace** | `workspace init/info/scan/status` | None | Detects project root, scans files, reads pyproject.toml. | ✅ Verified in `cli/workspace.py` |
| **model** | `model list/show/export` | None | Scans outputs/ for eval reports, displays metrics, exports ONNX/pickle. | ✅ Verified in `cli/model.py` |
| **provider** | `provider add/list/current` | None | Manages LLM provider API keys in .env. | ✅ Verified in `cli/provider.py` |
| **config** | `config list/set/check/edit/show` | None | Reads/writes .env with credential redaction. | ✅ Verified in `cli/config.py` |
| **plugin** | `plugin install/remove/list` | None | Manages PluginRegistry. | ✅ Verified in `cli/plugin.py` |
| **benchmark** | `benchmark summary/wins/stats` | None | Reads research/benchmark/results/. | ✅ Verified in `cli/benchmark.py` |
| **deploy** | `deploy list/logs/stop/predict` | None | Interacts with Docker serving containers. | ✅ Verified in `cli/deploy.py` |
| **evaluate** | `evaluate` | None | Loads data from research/benchmark/. | ✅ Verified in `cli/evaluate.py` |
| **job** | `job submit/list/status/cancel` | None | Wraps JobService — Redis CRUD. | ✅ Verified in `cli/job.py` |
| **memory** | `memory stats/search` | None | ChromaDB + Redis queries via MemoryService. | ✅ Verified in `cli/memory.py` |
| **planner** | `planner` | None | Inspects ExecutionPlan objects. | ✅ Verified in `cli/planner.py` |

### System Commands

| Command | Syntax | Actual Behavior | Status |
|---------|--------|----------------|--------|
| `init` | `init` | First-run wizard: provider setup, API key, workspace init | ✅ Verified |
| `doctor` | `doctor` | Runs prerequisite checks (Docker, Redis, Python, .env) | ✅ Verified |
| `version` | `version` | Prints `0.1.0` | ✅ Verified |
| `help` | `help` | Shows categorized command reference | ✅ Verified |
| `daemon` | `daemon start/stop/status/restart/logs` | PID-based subprocess orchestration | ✅ Verified |

### Backward-Compat Redirect Stubs (16 total)
`logs`→`mission logs`, `replay`→`mission replay`, `report`→`mission report`, `solve`→`mission new`, `job`→`mission`, `swarm`→`agent list`, `deploy`→`model export`, `explain`→`doctor`, `planner`→`mission status`, `memory`→`agent inspect`, `tool`→`config list`, `profile`→`config set`, `benchmark`→`mission new --auto`, `reproduce`→`mission new`, `evaluate`→`model show` — each prints a redirect message to use the canonical command.

### Cockpit TUI

| Screen | Actual Behavior | Status |
|--------|----------------|--------|
| Main dashboard | 3-panel layout: header, phase tracker, active-agent timeline | ✅ Working |
| PhaseTracker | Per-agent status for all 6 agents, color-coded | ✅ Working |
| ActiveAgentPane | Full event timeline for current agent, thinking tokens | ✅ Working |
| CascadeAttempt | Dissect cascade tracking (bottom panel) | ✅ Working |
| DiffViewerScreen | Side-by-side or unified diff for patches | ✅ Working |
| EscalationModal | Full-screen escalation details | ✅ Working |
| ReplayController | Controls for trace replay mode | ✅ Working |
| LogScreen | Scrollback event log overlay | ✅ Working |
| HelpScreen | Keyboard shortcut reference | ✅ Working |
| **Search functionality** | `log_search_started` AttributeError | 🔴 Broken (AUDIT.md Bug 1) |
| **Filter functionality** | `show_filter_input` AttributeError | 🔴 Broken (AUDIT.md Bug 2) |

### Dissect Cascade Levels

| Level | Module | Actual Behavior | Status |
|-------|--------|----------------|--------|
| **L0 — Deterministic Rules** | `rules.py` (667 lines) | 10 fix_*() functions: fix_name_error, fix_import_error, fix_dtype_mismatch, fix_shape_mismatch, fix_nan_handling, etc. Each returns patched code or None. | ✅ Working |
| **L1 — Compiled Templates** | `repair_templates.py` (526 lines) | `RepairTemplate` registry with promote_to_template(). Compiled patterns promoted from successful LLM patches. | ✅ Working |
| **L2 — Repair Cache** | `repair_cache.py` (118 lines) | MD5-based cache of (dataset_path + error_type + error_snippet → known fix). | ✅ Working |
| **L3 — Patch Memory** | `knowledge_store.py` (99 lines) | ChromaDB semantic search (K=3). Records every LLM interaction to `llm_knowledge_queue`. | 🟡 Partial — ChromaDB query exists but semantic retrieval quality depends on embedding model |
| **L4 — LLM Reasoning** | Agent's `handle_crash()` | Full LLM call with error context, traceback, and script. Fallback when all lower levels fail. | ✅ Working |

---

## 6. End-to-End Data Flow

### Mission Lifecycle Walkthrough

**1. Submission** (`mission new --file data.csv --target Survived`)
- CLI calls `orchestrator.job_queue.submit_job()` or the event-driven orchestrator
- Creates a UUID `job_id`
- Writes `job:{job_id}:status = "MISSION_CREATED"` to Redis
- Launches the orchestrator loop

**2. Scout** (reads problem description + CSV)
- Reads dataset file, runs `detect_modality()` (file extension → tabular/text/image)
- Runs `run_eda()` — pandas analysis: column types, missing values, cardinality, class imbalance
- Runs `reasoning.py` — 10 deterministic reason_*() functions, each returns `EngineeringDecision`
- Calls LLM to refine task_type from problem description
- Builds `MissionBrief` Pydantic model
- Writes to Redis at `job:{job_id}:mission_brief`
- Publishes `MISSION_BRIEF_READY` event to `scout_output` stream
- Transitions state to `SCOUT_COMPLETED`

**3. Forge** (reads mission brief → writes training script)
- Reads MissionBrief from Redis
- Calls `decision_tree.py:select_architecture()` — heuristic: tabular+<1M→lightgbm, tabular+>=1M→tabnet, text→distilbert, image→efficientnet
- Runs `planner.py:create_plan()` → structured `EngineeringPlan`
- Uses `confidence_router.py` to pick strategy: template (≥0.85), cache (≥0.55), or LLM (<0.55)
- For template strategy: renders Jinja2 template from `templates/` with mission vars
- For LLM strategy: calls LLM with full prompt, validates output with `ast.parse()`, `py_compile()`, import resolution
- Runs `static_prevention.py` — deterministic text transformations on generated script
- Runs `prevention.py` — applies Redis-backed prevention rules from prior Dissect patches
- Computes SHA-256 fingerprint, checks if identical script was previously successful
- Writes script to `scripts/training_script_{job_id}.py`
- Writes search space to Redis at `job:{job_id}:search_space`
- Publishes `TRAINING_SCRIPT_READY` event
- Transitions state to `FORGE_COMPLETED`

**4. Furnace** (launches training, streams metrics, handles crashes)
- Reads script path from event
- Launches Docker container via `DockerManager` — mounts scripts (ro), data (ro), outputs (rw)
- Streams stdout/stderr in real-time, parses JSON lines:
  - `epoch_complete`: publishes `EPOCH_COMPLETE` to `furnace_feed`, updates Prometheus metrics
  - `training_complete`: captures checkpoint path, best metric
  - `crash`: saves checkpoint snapshot, publishes `CRASH_EVENT` to `furnace_crash`
- On crash:
  - Increments crash counter, updates Redis
  - Enters WAIT state — blocks reading `dissect_output` stream (10 min timeout)
  - If `RESUME_TRAINING` received: loads patched script, resumes with `last_checkpoint`
  - If `ESCALATE` received or timeout: kills container, returns escalated
- On success: publishes `TRAINING_COMPLETE` with checkpoint path and metrics
- Transitions state to `FURNACE_COMPLETED` or `TRAINING_FAILED`

**5. Dissect** (debugs crashes via 5-level cascade)
- Triggered by `CRASH_EVENT` from `furnace_crash` stream
- Computes crash fingerprint (SHA-256 of error_category + message[:200] + script_hash[:16] + stage)
- Checks budget: max 1 LLM call per fingerprint, $0.10, 15000 tokens, 180s wall clock
- Runs 5-level cascade:
  - L0: Match error against 31 taxonomy categories via regex → apply fix_*() rule
  - L1: Match against compiled repair templates
  - L2: Check repair cache (MD5 key)
  - L3: ChromaDB patch memory semantic search (K=3)
  - L4: Full LLM call with traceback + script context
- Each level returns confidence. If confidence < threshold, escalate to next level.
- On success: applies patch, validates syntax, runs sandbox test (≤3 epochs in Docker), promotes successful LLM patches to cache/template/rule
- On all levels fail: escalates
- Writes PatchLogEntry to Redis `patch_log_queue`
- Publishes `RESUME_TRAINING` or `ESCALATE` to `dissect_output`

**6. Arbiter** (evaluates model, makes PASS/RETRY/FAIL decision)
- Triggered by `TRAINING_COMPLETE` event
- Loads checkpoint data (`y_test.npy`, `y_pred.npy`, `y_prob.npy`)
- Loads mission constraints from Redis
- Computes metrics: AUC-ROC, F1, precision, recall (classification) or RMSE, MAE, R², MAPE (regression)
- Calls `make_decision()`:
  - If metric ≥ threshold → PASS
  - If within 15% of threshold → RETRY
  - Otherwise → FAIL
- Saves evaluation artifacts: evaluation.json, metrics.csv, decision.json, confusion matrix/ROC/PR plots
- Records experience in ChromaDB `experience_memory`
- Publishes `EVALUATION_PASS`, `EVALUATION_RETRY`, or `ESCALATE`
- Transitions state accordingly

**7. Harbor** (deploys model to live endpoint)
- Triggered by `EVALUATION_PASS` event
- Loads checkpoint and mission brief from Redis
- Extracts column info, model type
- Serializes model to ONNX (or falls back to pickle)
- Generates FastAPI serving app via `serving_template.py`
- Runs `artifact_validator.py:verify_deployment()` — 6-phase validation (Pipeline vs Contract, Contract vs ONNX, etc.)
- Builds Docker image
- Deploys via Docker Compose with auto port management
- Runs self-test against deployed endpoint (synthetic prediction request)
- Configures PSI drift monitoring (3600s interval, 1000-sample window, 0.2 threshold)
- Starts async drift monitor loop
- Publishes `ENDPOINT_LIVE` with URL, model format, latency

**8. Drift Monitoring** (post-deployment)
- Harbor starts async loop: `start_drift_monitor_loop()`
- Every 3600s: computes PSI between training and live distributions
- If PSI > 0.2: publishes `DRIFT_ALERT`
- Drift alert consumed by Orchestrator/Scout for potential retraining

---

## 7. Current Implementation Status

| Component | Status | Evidence |
|-----------|--------|----------|
| **6 Agent cores** (agent.py) | ✅ Working | All have real implementations with Redis I/O, event publishing, Prometheus metrics. None are stubs. Total: ~16,000 lines across 54 files. |
| **Contracts** (domain, events, state) | ✅ Working | Pydantic v2 models, 16 typed events, 20-state machine with transition matrix |
| **Event bus** (publisher, consumer) | ✅ Working | Redis Streams with consumer groups, checkpointing, typed events |
| **Orchestrator** (runtime) | ✅ Working | 1082-line main loop, parallel Furnace↔Dissect crash recovery |
| **CLI** (13 command groups) | ✅ Working | click-based with AliasedGroup, fuzzy suggestions, 16 redirects, REPL fallback |
| **Cockpit TUI** | ✅ Working | Textual app, 11 widget types, live Redis streams, trace replay. **Known bugs:** search & filter broken. |
| **LLM provider** (Anthropic) | ✅ Working | Full integration with retry, token tracking, cost logging |
| **Forge templates** (10 templates) | ✅ Working | Jinja2 rendering for all 5 architectures + task variants |
| **Dissect cascade** (5 levels) | ✅ Working | L0-L4 with deterministic rules, templates, cache, ChromaDB, LLM |
| **Retry engine** (runtime/) | ✅ Working | Orchestrator, 4 strategies, state tracking, capability registry |
| **Prometheus metrics** | ✅ Working | Counter/Gauge/Histogram for all agent categories |
| **Memory** (Redis + ChromaDB) | ✅ Working | 4 collections, embeddings, semantic search |
| **Research framework** | ✅ Working | Benchmark runner (50 problems, 3 conditions), ablation (7 configs), statistics (Mann-Whitney, McNemar, Cohen's h) |
| **Docker management** | ✅ Working | Container lifecycle, health checks, GPU support |
| **Script fingerprinting** | ✅ Working | SHA-256 dedup — skips training if identical script succeeded before |
| **Error prevention** (static + Redis) | ✅ Working | 5 static prevention transformations + Redis-backed PreventionRules |
| **Patch log writer** | ✅ Working | BLPOP from Redis → JSONL file with filelock |
| **Label normalizer** | ✅ Working | Training module for deterministic label encoding across retries |
| **Drift monitor** | ✅ Working | PSI-based, 3600s interval, 0.2 threshold |
| **Frontend (Next.js)** | 🟡 Partial | Routes exist (feed, jobs/[id], drift, dashboard), Redis client partial |
| **Tool memory** | 🟡 Partial | ChromaDB collection exists, semantic retrieval partially wired |
| **GKE/Kubernetes deployment** | ⚪ Planned | infra/kubernetes exists but configs are minimal |
| **OpenAI provider** | ⚪ Planned | Base class exists, no integration |
| **Built-in plugins** | 🔴 Stubbed | Plugin system exists, builtin/ directory is empty |

---

## 8. Known Issues, Bugs & Open Hypotheses

### Bugs from AUDIT.md (July 10, 2026) — All Unfixed

| # | Bug | File | Status |
|---|-----|------|--------|
| A | **No LabelEncoder in tabular training scripts** — LightGBM, XGBoost, TabNet templates don't encode string targets. `training/label_normalizer.py` exists but is unused by generated scripts. | `agents/forge/templates/*.jinja` | ✅ Fixed — LabelEncoder already present in all 4 templates + 3 f-string generators |
| B | **TabNet proposed but pytorch-tabnet not installed** — Architecture selection can choose tabnet but the library isn't in the training Docker image. | `training/base_training_image/Dockerfile` | ✅ Fixed — `pytorch-tabnet==4.1.0` in Dockerfile |
| C | **`state.imbalance_strategy` not updated after crash** — Retry loop doesn't propagate imbalance_strategy to MissionState, so next retry iteration uses stale value. | `runtime/retry_orchestrator.py:175-198` | ✅ Fixed — `state.imbalance_strategy` set at line 311 |
| D | **`best_metric` stays 0.0** — `record_retry_attempt()` only updates `best_metric` on PASS, not on RETRY. | `runtime/models.py:368` | ✅ Fixed — unconditional `metric_value > best_metric` check |
| E | **Same as Bug C — after success too** — State not updated after successful retry at lines 220-249. | `runtime/retry_orchestrator.py:220-249` | ✅ Fixed — `state.imbalance_strategy` set at line 363 |
| F | **`wait_for_dissect=False` hardcoded during retry** — Furnace skips WAIT state in retry mode, so Dissect never receives CRASH_EVENTs from retry runs. | `runtime/retry_orchestrator.py:462` | ✅ Fixed — concurrent Furnace (`wait_for_dissect=True`) + Dissect handler tasks |

### Cockpit TUI Bugs (from AUDIT.md + exploration)

| # | Bug | File | Status |
|---|-----|------|--------|
| 1 | Cockpit `search` fails: `'SearchWidget' object has no attribute 'log_search_started'` | `prometheus/ui/cockpit/widgets.py` | ✅ Fixed — implemented `log_search_started()` + search modal on `LogScreen` |
| 2 | Cockpit `filter` fails: `'JobListPanel' object has no attribute 'show_filter_input'` | `prometheus/ui/cockpit/widgets.py` | ✅ Fixed — implemented `show_filter_input()` + filter-by-state modal on `LogScreen` |

### Discovered During Audit

| # | Issue | File | Severity |
|---|-------|------|----------|
| 3 | **Directory is spelled `orchestator`** (missing 'r') — the orchestrator/ directory has a typo in its name. This may cause import issues if anything uses the canonical spelling. | `orchestator/` at root | 🟡 Low — consistent within codebase |
| 4 | **Duplicate MissionState definitions** — `contracts/state.py` defines the canonical MissionState while `runtime/models.py` has a parallel MissionState. These may diverge. | `runtime/models.py` vs `contracts/state.py` | 🟢 Reconciled — added `schema_version`, `metric_direction` to runtime version; cross-reference comments |
| 5 | **Dissect prompt only lists 11 categories** — The system prompt in `prompts.py` lists 11 error categories, but `taxonomy.py` defines 24 (not 31 as previously stated). | `agents/dissect/prompts.py:52` | ✅ Fixed — prompt now lists all 24 categories |
| 6 | **PLAN.md is 3150+ lines of historical build steps** — This is a literal step-by-step build plan, not a design doc. It's useful for understanding how the system was built but is easy to confuse with current architecture. | `PLAN.md` | 🟡 Awareness |
| 7 | **pyproject.toml dependencies are incomplete** — The pyproject.toml only lists `click`, `rich`, `shellingham` as dependencies, but the full dependency set is in `requirements.txt`. | `pyproject.toml` | ✅ Fixed — full dependency list added |
| 8 | **README.md test count is wrong** — Claims 47 tests pass; actual test count is 93 test `.py` files. | `README.md` | 🟡 Low — stale doc |
| 9 | **README.md phase status is wrong** — Claims Phase 3 is "In progress" and Phase 4 is "Not started" — actual state is beyond Phase 3.5 with Phase 4 benchmark campaigns completed. | `README.md` | 🟡 Low — stale doc |
| 10 | **CLAUDE.md claimed Appendix C doesn't exist** — The Design Book already has Appendix C with the event schema; the implementation already matches it. | `CLAUDE.md` | ✅ Fixed — corrected in this version |

---

## 9. Pending Design Decisions

| Question | Options | Current Leaning | Tradeoffs |
|----------|---------|-----------------|-----------|
| **Default orchestrator: sequential vs event-driven?** | A) Legacy sequential `orchestrator/runtime.py` (in-process, deprecated) vs B) Event-driven `orchestrator/job_runner.py` (Redis Streams, async) | B — event-driven is the current path | A is simpler, B is more robust for crash recovery |
| **Training container: Docker vs local subprocess?** | Docker (isolated, portable) vs local subprocess (faster, simpler) | Docker — current implementation uses Docker for training | Docker adds latency but is required for sandbox testing and isolation |
| **MissionState canonical location?** | `contracts/state.py` or `runtime/models.py` | Both — reconciled with cross-reference comments and matched fields (`schema_version`, `metric_direction`) | Dual representation maintained for different serialization needs; kept in sync |
| **OpenAI provider integration?** | Full implementation or defer | Deferred — Anthropic is the only active provider | OpenAI support would broaden accessibility |
| **Frontend priority?** | Complete Next.js dashboard or leave as scaffolded | Currently scaffolded — focus is on CLI/TUI | Web dashboard would improve accessibility but is not needed for research |

---

## 10. Design History & Rationale

### Key Architectural Decisions

- **Redis Streams over Kafka:** Single-node research deployment. Redis is simpler, requires no ZooKeeper, and is already used for job state. The bus layer has 4 files totaling ~380 lines.

- **ChromaDB over Pinecone:** Self-hosted research deployment. No API costs, no data leaves the local machine. Latency is higher but acceptable for research workloads.

- **Jinja2 templates over programmatic script generation:** Templates are debuggable — you can read the actual template file and see exactly what will be generated. This was critical during development when Forge's LLM-generated scripts were unreliable.

- **Textual TUI over web dashboard:** Real-time operational visibility during development. The Cockpit shows thinking tokens, cascade decomposition, and live metrics — information density that's harder to achieve in a web UI.

- **click over argparse:** Developer experience. click's declarative command groups, automatic help generation, and plugin-friendly design made it the right choice for 13+ command nouns.

- **Docker Compose over Kubernetes:** Research phases. K8s adds operational complexity that isn't justified for a single-node system. The `infra/` directory has K8s configs but they're aspirational.

- **pydantic-settings over python-dotenv:** Type-safe configuration. pydantic-settings validates types at load time (e.g., `int(port)`) instead of forcing every consumer to parse strings.

### Past Incidents Worth Remembering

1. **Credential overwrite (early Phase 2):** A CLI command (likely `config set`) overwrote `.env` without preserving existing values, causing the user to lose their API key. Fix: `ConfigService` now reads before writing and backs up `.env` to `.env.bak` before any edit.

2. **Fabricated spec citations (mid Phase 2):** An AI agent claimed that certain features were specified in `Prometheus_CLI_UX_Design_Book.md` when they were not. This led to the "verify claims against actual code, not docs" ground rule. The design book is a spec, not an implementation reference.

3. **Silent data loss in ChromaDB collections (Phase 3):** ChromaDB collection reset during development caused loss of accumulated patch memory. Fix: Collections now only reset on explicit `ALLOW_RESET=true` and the agent code never calls `reset()` in production paths.

4. **Dissect infinite loop (Phase 2):** Dissect would attempt to patch the same error repeatedly if the fingerprint was computed incorrectly (ignoring the exception message). Fix: `fingerprint.py` now includes the first 200 chars of the exception message in the hash.

---

## 11. Testing & Verification State

### Test Framework
- **pytest** with `pytest-asyncio` (asyncio_mode = auto)
- **Marks:** `unit`, `integration`, `slow`, `e2e`, `validation`, `training_exec`
- **Config:** in `pyproject.toml` — asyncio_mode=auto, testpaths=[tests], pythonpath=[.]
- **Total files:** 77 files (68 .py test files + fixtures + conftest)

### Test Distribution

| Directory | Count | Type |
|-----------|-------|------|
| `tests/unit/agents/` | ~15 files | Per-agent unit tests |
| `tests/unit/contracts/` | 1 file | State machine tests |
| `tests/unit/bus/` | 1 file | Event bus tests |
| `tests/unit/runtime/` | 1 file | Retry engine tests |
| `tests/unit/shared/` | 5 files | Memory + config + execution |
| `tests/unit/cockpit/` | 5 files | TUI tests |
| `tests/unit/cli/` | 1 file | CLI command tests |
| `tests/unit/planner/` | 4 files | Planner compiler + validators |
| `tests/unit/evaluation/` | 5 files | Evaluation framework |
| `tests/unit/validation/` | 8 files | Research validation |
| `tests/unit/other/` | 6 files | Various (agent instantiation, reliability, etc.) |
| `tests/integration/` | 13 files | Require Redis/Docker |
| `tests/services/` | 6 files | Service layer tests |
| `tests/validators/` | 2 files | Registry validation |

### Key Coverage Observations

- **All 6 agents** have dedicated unit and integration tests
- **Dissect** has 5 injected-error test fixtures for real crash testing
- **Cockpit TUI** has 5 test files (live Redis, cascade, replay, full mission)
- **Forge** has 6 test files (templates, planner, decision tree, confidence router, fingerprint, prevention)
- **Research validation** has 8 test files
- **No tests** for: `prometheus/ui/` rendering components, `prometheus/registry/`, `prometheus/utils/`, frontend
- **End-to-end tests:** Titanic, 3 Kaggle datasets, scenarios, furnace-dissect loop, harbor serving
- **Test quality:** Tests assert actual behavior (not `assert True`). Integration tests require Redis/Docker and are skipped if not available.

---

## 12. Coding Conventions & Patterns

### Python and Style
- **Python 3.11+** — type hints on every function signature (verified across all agent files)
- **Framework:** click for CLI (not argparse), Rich for console output, Textual for TUI, Pydantic v2 for all cross-agent data
- **Async-first:** `async/await` for all I/O (Redis, LLM calls, Docker). Even CLI commands wrap async calls via `asyncio.run()`.
- **Docstrings:** Google-style (not numpy or reST) — verified in all agent modules
- **Naming:** `snake_case` for files/functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
- **Formatting:** ruff with line-length=100, black with line-length=100

### Error Handling Pattern
```python
try:
    result = await something_risky()
except SpecificError as e:
    logger.error(f"[Agent][job={job_id}] Context: {e}")
    # Return fallback or re-raise
```

All external calls (Redis, Docker, LLM) are wrapped in try/except with `job_id` + `agent_id` context. Critical errors are logged and re-raised; non-critical ones return fallback values.

### How to Add a New Agent
1. Create `agents/<name>/` directory with `agent.py`, `tools.py`, `prompts.py`, `models.py`
2. Subclass `BaseAgent` from `agents/base.py` — implement `agent_name`, `system_prompt`, `run()`
3. Add stream name + consumer group to `bus/events.py`
4. Add event type constant to `bus/events.py` (if new event)
5. Add event payload model to `contracts/events.py` (if new event)
6. Add state transitions to `contracts/state.py:MISSION_PHASE_TRANSITIONS`
7. Register in `prometheus/cli/agent.py` (for `agent list/inspect`)
8. Add tests in `tests/unit/agents/` and `tests/integration/`
9. Add agent-specific Prometheus metrics in `serving/metrics.py`

### How to Add a New CLI Command
1. Create file in `prometheus/cli/<name>.py` with `@click.group` or `@click.command`
2. Export from `prometheus/cli/__init__.py`
3. Register in `prometheus/main.py:_register_commands()`
4. Add `Command` entry to `prometheus/registry/registry.py:_build()` (1079-line function)
5. Add redirect stub in `prometheus/main.py:_register_commands()` if it replaces an old command

### Test Structure Convention
- Test files mirror source structure under `tests/` (e.g., `agents/scout/tools.py` → `tests/unit/agents/test_scout_tools.py`)
- Integration tests go in `tests/integration/`
- Test data goes in `tests/fixtures/`
- Fixtures use `pytest.mark.asyncio` for async tests

---

## 13. Running, Building & Testing the Project

### Prerequisites
- Python 3.11+
- Docker Desktop (Windows) / Docker Engine (Linux)
- Redis 7+ (via Docker)
- ChromaDB (via Docker)
- Anthropic API key (for LLM-powered agents)

### Full Setup (Windows PowerShell)
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy environment template
copy .env.example .env
# Edit .env: set ANTHROPIC_API_KEY, adjust paths

# Start infrastructure
docker compose up -d redis chromadb
```

### Launch Commands
```powershell
# CLI
python -m prometheus

# CLI with specific command
python -m prometheus mission new --file data/titanic.csv --target Survived

# Cockpit TUI
python -m prometheus ui
# Or directly:
python -m prometheus.ui.cockpit.app

# REPL mode
python -m prometheus --repl

# Daemon mode (background agent)
python -m prometheus daemon start
```

### Make Commands
```bash
make lint         # ruff check
make format       # ruff format
make typecheck    # mypy (note: may not work — pyproject.toml has no mypy config)
make test         # pytest all tests
make test-fast    # pytest -m "not slow"
make test-e2e     # End-to-end tests
make test-cov     # pytest with coverage
make clean        # Clean build artifacts
make docker       # Build training/serving Docker images
make precommit    # Run pre-commit on all files
```

### Running Tests
```bash
# All tests
pytest tests/ -v

# Fast tests only (no Docker/Redis)
pytest tests/ -m "not slow" -v

# Specific test file
pytest tests/unit/agents/test_scout_tools.py -v

# Integration tests (requires running Docker + Redis)
pytest tests/integration/test_titanic_e2e.py -v -s
```

### Environment Variables (.env)
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-6` | Model name |
| `REDIS_HOST` | No | `localhost` | Redis host |
| `REDIS_PORT` | No | `6379` | Redis port |
| `CHROMA_HOST` | No | `localhost` | ChromaDB host |
| `CHROMA_PORT` | No | `8000` | ChromaDB port |
| `TRAINING_IMAGE_NAME` | No | `prometheus-training-base` | Docker image name |
| `SCRIPTS_DIR` | No | `./scripts` | Generated scripts directory |
| `OUTPUTS_DIR` | No | `./outputs` | Job outputs directory |
| `DATA_DIR` | No | `./data` | Dataset directory |
| `PATCH_LOG_PATH` | No | `./research/patch_log.jsonl` | Patch log file |
| `SERVING_PORT` | No | `8080` | Default serving port |
| `LOG_LEVEL` | No | `INFO` | Log level |

---

## 14. Key File Reference

A fast-lookup index of the most important files, organized by function.

### Entry Points
| File | Purpose |
|------|---------|
| `prometheus/__main__.py` | `python -m prometheus` entry — calls `cli()` |
| `prometheus/main.py` | click.Group bootstrap, 13 commands + 16 redirects + REPL |
| `prometheus/repl.py` | Interactive REPL mode |

### Agent Implementations (core logic — 6 agents)
| File | Purpose |
|------|---------|
| `agents/base.py` | BaseAgent ABC — all 6 agents inherit from this |
| `agents/llm_client.py` | `get_llm_response()` — Anthropic Claude wrapper with retry |
| `agents/scout/agent.py` | Scout: problem parsing, EDA, MissionBrief generation |
| `agents/scout/reasoning.py` | Pure deterministic reasoning engine (10 reason_* functions) |
| `agents/forge/agent.py` | Forge: architecture selection, multi-strategy script generation |
| `agents/forge/template_renderer.py` | Jinja2 rendering pipeline |
| `agents/forge/decision_tree.py` | Architecture selection heuristics |
| `agents/forge/static_prevention.py` | Text transformations to prevent common errors |
| `agents/furnace/agent.py` | Furnace: Docker training, metrics streaming, crash handling |
| `agents/dissect/agent.py` | Dissect: 5-level cascade error debugger |
| `agents/dissect/routing.py` | 5-level cascade router |
| `agents/dissect/taxonomy.py` | 31 error category taxonomy |
| `agents/dissect/rules.py` | Level 0 deterministic repair functions |
| `agents/dissect/governor.py` | Per-fingerprint budget enforcement |
| `agents/dissect/fingerprint.py` | Error fingerprinting for dedup |
| `agents/arbiter/agent.py` | Arbiter: model evaluation, PASS/RETRY/FAIL decision |
| `agents/arbiter/decision.py` | `make_decision()` — pure decision engine |
| `agents/harbor/agent.py` | Harbor: ONNX serialization, FastAPI generation, Docker deploy |
| `agents/harbor/serving_template.py` | FastAPI serving template |
| `agents/harbor/artifact_validator.py` | 6-phase deployment validation |

### Contracts & Data Flow
| File | Purpose |
|------|---------|
| `contracts/domain.py` | SCHEMA_VERSION_V1, base types |
| `contracts/events.py` | 16 typed EventPayload Pydantic models |
| `contracts/state.py` | MissionPhase (20 values), transition matrix, MissionState |
| `bus/events.py` | Stream names, consumer groups, event type constants |
| `bus/publisher.py` | publish() — XADD to Redis Streams |
| `bus/consumer.py` | consume_one(), consume_loop() — XREADGROUP with ACK |
| `bus/checkpoint.py` | Stream checkpointing |

### Orchestration
| File | Purpose |
|------|---------|
| `orchestator/runtime.py` | Main orchestration loop (1082 lines) |
| `orchestator/job_runner.py` | Job lifecycle management |
| `orchestator/health_monitor.py` | Agent health monitoring (heartbeat, restart) |
| `orchestator/patch_log_writer.py` | BLPOP from Redis → JSONL file |
| `runtime/retry_orchestrator.py` | Orchestrated retry logic (777 lines) |
| `runtime/retry_strategy.py` | 4 retry strategies |
| `runtime/models.py` | Result, Context, Error types + duplicate MissionState |

### CLI
| File | Purpose |
|------|---------|
| `prometheus/cli/mission/__init__.py` | Mission command (1158 lines) — the main user-facing command |
| `prometheus/cli/mission/ui.py` | Rich live-updating UI for all 6 agent phases |
| `prometheus/cli/agent.py` | Agent management commands |
| `prometheus/cli/config.py` | Configuration management commands |
| `prometheus/cli/solve.py` | Submits to event-driven orchestrator |
| `prometheus/registry/registry.py` | 1079-line command catalog (~80 commands) |

### Cockpit TUI
| File | Purpose |
|------|---------|
| `prometheus/ui/cockpit/app.py` | CockpitApp: Textual live dashboard (684 lines) |
| `prometheus/ui/cockpit/widgets.py` | 11 widget types (1415 lines) |
| `prometheus/ui/cockpit/consumer.py` | Read-only Redis consumer for agent events |

### Infrastructure
| File | Purpose |
|------|---------|
| `memory/redis_client.py` | Singleton async Redis client |
| `memory/chroma_client.py` | ChromaDB connection helpers |
| `training/docker_manager.py` | Docker container lifecycle (314 lines) |
| `training/checkpoint_manager.py` | Checkpoint save/restore (44 lines) |
| `training/label_normalizer.py` | Deterministic label encoding (149 lines) |
| `serving/onnx_runtime.py` | ONNX inference runtime (47 lines) |
| `serving/drift_monitor.py` | PSI-based drift detection (93 lines) |
| `serving/metrics.py` | Prometheus metric definitions (75 lines) |
| `shared/config.py` | pydantic-settings configuration |
| `shared/logging.py` | Structured JSON logging |

### Research
| File | Purpose |
|------|---------|
| `research/run_benchmark.py` | Main benchmark runner: Conditions A/B/C (904 lines) |
| `research/run_campaign.py` | Campaign runner: N runs for learning curves (445 lines) |
| `research/run_ablation.py` | Ablation: 7 configs across all problems (579 lines) |
| `research/statistical_analysis.py` | Mann-Whitney U, McNemar, Cohen's h |
| `research/validation/` | Pydantic models + experiment tracking |

### Tests
| File | Purpose |
|------|---------|
| `tests/integration/test_titanic_e2e.py` | Phase 1 gate test (full Scout→Forge→Furnace) |
| `tests/integration/test_three_kaggle_e2e.py` | 3-dataset end-to-end test |
| `tests/integration/test_furnace_dissect_loop.py` | Crash-recovery loop test |
| `tests/integration/test_dissect_sandbox_docker.py` | Sandbox Docker test |
| `tests/fixtures/injected_errors/` | 5 deliberately broken training scripts |

---

## 15. Open Questions / Explicitly Unverified Items

This section lists everything I could not fully confirm during this audit.

1. **Actual test pass count.** I counted 77 test files but did not run `pytest` to confirm pass rate. The README claims "47 tests pass" which is contradicted by the 77-file count. The actual number may be different.

2. **`runtime/models.py` vs `contracts/state.py` duplication.** Both define `MissionState`. I did not diff them to check for divergence. This should be reconciled — the `contracts/` version is the canonical one.

3. **ChromaDB integration test.** I confirmed the `chroma_client.py` and collection modules exist but did not run an end-to-end ChromaDB query test to verify the semantic search pipeline works end-to-end.

4. **OpenAI provider.** `agents/openai_provider.py` does not exist at the expected path. The provider code lives in `prometheus/providers/` and the OpenAI provider there is base-class-only. Full integration status is unverified.

5. **Memory collection count.** I confirmed `patch_memory` and `architecture_memory` collections exist. `tool_memory` may exist but I did not verify its schema or semantic retrieval wiring.

6. **GitHub Actions CI.** I found `.github/workflows/ci.yml` but did not read its contents. CI pipeline status is unverified.

7. **All 50 benchmark problems.** I confirmed `research/benchmark/problems.json` exists but did not read its contents to verify all 50 problem definitions.

8. **Pre-commit hook config.** `.pre-commit-config.yaml` exists but I did not read its contents to verify what hooks are configured.

9. **`UI/` top-level directory vs `prometheus/ui/`.** Both exist. The top-level `UI/` may be a duplicate or may contain the actual TUI. I did not fully explore `UI/` at the top level — my exploration focused on `prometheus/ui/cockpit/`.

10. **`deploy_update_app.py` at root.** I did not read this file. Its purpose is unknown.

11. **Docker Compose full stack.** `docker-compose.yml` may include more than just Redis and ChromaDB (observability stack like Grafana, Prometheus, Loki). I did not read the full file.

12. **Frontend build status.** The Next.js frontend at `frontend/` has `frontend/.next/` build output directories, suggesting it was built at some point. I did not verify whether it currently builds or runs.
