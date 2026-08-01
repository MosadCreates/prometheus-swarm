# CLAUDE.md — Prometheus Swarm

> Last full audit: 2026-08-01. Every claim below was verified by reading the
> actual source code, not inferred from filenames, comments, or prior docs.
> Notable corrections vs. the previous snapshot: the orchestrator directory is
> spelled `orchestrator` (correct); the CLI registers 15 commands with **zero**
> redirect stubs; tests total 82 files (unit tests are flat under `tests/unit/`);
> `research/benchmark/problems.json` contains 10 problems; the Dissect taxonomy
> defines 24 categories; there is no `Makefile`, no top-level `UI/` directory,
> and no `deploy_update_app.py`.

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

All paths below exist in the repository. Top-level structure is flat (agents/, bus/, contracts/, orchestrator/, etc. are all at root), NOT nested inside prometheus/. Line counts are from `wc -l` on 2026-08-01.

```
prometheus-swarm/
│
├── .env / .env.example        ← Environment config (gitignored)
├── .gitignore
├── .pre-commit-config.yaml    ← Pre-commit hooks (ruff, black, bandit)
├── AUDIT.md                   ← Bug fix sprint doc (July 2026)
├── CLAUDE.md                  ← THIS FILE
├── PLAN.md                    ← Full build plan (historical build steps)
├── Prometheus_CLI_UX_Design_Book.md  ← CLI design spec (~34-page spec)
├── Prometheus_CLI_Implementation_Master_Prompt.md  ← CLI implementation guide
├── RESULTS_SCHEMA.md          ← Benchmark result schema specification
├── README.md                  ← Project README
├── docker-compose.yml         ← Redis + ChromaDB + optional orchestrator (profile "full")
├── Dockerfile                 ← Main app Dockerfile
├── pyproject.toml             ← Metadata, entry point: prometheus = prometheus.main:cli
├── requirements.txt           ← Fully pinned dependencies (56 lines)
├── start.ps1                  ← Windows Docker startup script
├── uv.lock                    ← UV lock file
│
├── agents/                    ← ⭐ Six AI agent implementations
│   ├── __init__.py
│   ├── base.py (128)          ← BaseAgent ABC: agent_name, run(), call_llm()
│   ├── llm_client.py (167)    ← get_llm_response() — Anthropic Claude wrapper
│   │
│   ├── scout/                 ← Perceiver (4 files, ~1813 lines total)
│   │   ├── agent.py (470)     ← ScoutAgent.run(): detect modality, run EDA, build MissionBrief
│   │   ├── tools.py (606)     ← detect_modality(), run_eda(), infer_task_type(), etc.
│   │   ├── reasoning.py (675) ← Pure deterministic reasoning engine (no LLM): 10 reason_*() functions
│   │   ├── prompts.py (62)    ← SCOUT_SYSTEM_PROMPT
│   │
│   ├── forge/                 ← Architect (12 files + 10 templates, ~4979 lines)
│   │   ├── agent.py (610)     ← ForgeAgent.run(): architecture selection, multi-strategy script gen
│   │   ├── tools.py (1362)    ← write_training_script(), define_optuna_space(), 5 f-string generators
│   │   ├── decision_tree.py   ← select_architecture(): heuristic decision tree
│   │   ├── planner.py (531)   ← create_plan(): EngineeringPlan from Scout brief
│   │   ├── template_renderer.py (384) ← Jinja2 rendering + ast.parse validation
│   │   ├── confidence_router.py (49) ← template/cache/llm strategy selector
│   │   ├── confidence_classifier.py  ← Confidence classification model
│   │   ├── static_prevention.py (574) ← apply_static_prevention() text transformations
│   │   ├── prevention.py (527)       ← Redis-backed error prevention rules
│   │   ├── script_fingerprint.py (202) ← SHA-256 script fingerprinting
│   │   ├── quality_feedback.py (865)  ← Redis-backed error statistics per architecture
│   │   ├── registry.py (287)   ← ArchitectureRegistry — single source of truth
│   │   └── templates/          ← 10 .jinja files (lightgbm, xgboost, tabnet, distilbert, efficientnet)
│   │
│   ├── furnace/               ← Trainer (3 files, ~1085 lines)
│   │   ├── agent.py (1024)    ← FurnaceAgent.run(): Docker/process management, crash handling
│   │   ├── tools.py (50)      ← launch_training_container(), monitor_loss()
│   │   └── prompts.py (11)    ← FURNACE_SYSTEM_PROMPT
│   │
│   ├── dissect/               ← Debugger (16 files, ~5229 lines)
│   │   ├── agent.py (986)     ← DissectAgent.handle_crash(): 5-level cascade
│   │   ├── routing.py (676)   ← run_cascade(): 5-level cascade router
│   │   ├── taxonomy.py (552)  ← 24 error categories (TaxonomyEntry, classify_error)
│   │   ├── rules.py (685)     ← Level 0 deterministic repair functions (10 fix_*())
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
│   │   └── prompts.py (78)    ← DISSECT_SYSTEM_PROMPT
│   │
│   ├── arbiter/               ← Evaluator (9 files, ~1780 lines)
│   │   ├── agent.py (497)     ← ArbiterAgent.on_training_complete()
│   │   ├── decision.py (77)   ← make_decision(): PASS/RETRY/FAIL logic
│   │   ├── evaluator.py (256) ← load_checkpoint_data(), evaluate()
│   │   ├── controller.py (291)← build_constraints_from_brief(), evaluate_and_decide()
│   │   ├── tools.py (184)     ← compute_classification/regression_metrics()
│   │   ├── report.py (330)    ← save_evaluation_report(), save_evaluation_plots()
│   │   ├── ui.py (121)        ← Rich console rendering
│   │   └── prompts.py (24)    ← ARBITER_SYSTEM_PROMPT
│   │
│   └── harbor/                ← Deployer (5 files, ~2337 lines)
│       ├── agent.py (504)     ← HarborAgent.on_evaluation_pass()
│       ├── tools.py (723)     ← serialize_to_onnx(), generate_fastapi_app(), deploy_local_compose()
│       ├── serving_template.py (355) ← FastAPI serving template
│       ├── artifact_validator.py (731) ← verify_deployment(): 6-phase validation
│       └── prompts.py (24)    ← HARBOR_SYSTEM_PROMPT
│
├── prometheus/                ← CLI application package
│   ├── __main__.py            ← Entry: from prometheus.main import cli; cli()
│   ├── main.py (310)          ← click.Group with 15 commands (10 noun + 5 system) + REPL
│   ├── repl.py (391)          ← Interactive REPL mode
│   │
│   ├── cli/                   ← All CLI command implementations (28 .py files)
│   │   ├── __init__.py (31)   ← Re-exports 15 CLI entry points
│   │   ├── mission/           ← Mission command group (1722-line __init__.py + 4 support files)
│   │   │   ├── __init__.py    ← @click.group 'mission' with 9 subcommands: new, list, status, logs, watch, resume, cancel, report, replay
│   │   │   ├── session.py     ← MissionSession dataclass + singleton tracker
│   │   │   ├── state_logger.py ← log_mission_state()
│   │   │   ├── ui.py (710)    ← Rich live-updating UI for all 6 agent phases
│   │   │   └── ui_harbor.py   ← Harbor-specific completion UI
│   │   ├── agent.py (373)     ← @click.group 'agent' (list, inspect, trace)
│   │   ├── benchmark.py       ← @click.group 'benchmark' (NOT registered in main.py)
│   │   ├── config.py          ← @click.group 'config' (list, set, check, edit, show)
│   │   ├── daemon.py          ← @click.command 'daemon' (start, stop, status, restart, logs)
│   │   ├── deploy.py          ← @click.group 'deploy' (NOT registered in main.py)
│   │   ├── evaluate.py (562)  ← @click.group 'evaluate' with 10 subcommands: run, compare, report, visualize, list, failures, calibration, summary, wins, stats
│   │   ├── explain.py         ← @click.command 'explain' (NOT registered in main.py)
│   │   ├── init.py            ← @click.command 'init' — first-run wizard
│   │   ├── job.py             ← @click.group 'job' (NOT registered in main.py)
│   │   ├── logs.py            ← @click.group 'logs' (NOT registered in main.py)
│   │   ├── memory.py          ← @click.group 'memory' (stats, search)
│   │   ├── model.py           ← @click.group 'model' (list, show, export)
│   │   ├── output.py (171)    ← Three-mode output contract (interactive/plain/json) — legacy twin of utils/output.py
│   │   ├── planner.py (558)   ← @click.group 'planner' (inspect, dry-run, validate, stats, explain, prediction-error)
│   │   ├── plugin.py          ← @click.group 'plugin' (install, remove, list)
│   │   ├── profile.py         ← @click.group 'profile' (NOT registered in main.py)
│   │   ├── provider.py        ← @click.group 'provider' (add, list, current)
│   │   ├── replay.py          ← @click.command 'replay' (NOT registered in main.py)
│   │   ├── report.py          ← @click.command 'report' (NOT registered in main.py)
│   │   ├── reproduce.py       ← @click.group 'reproduce' (NOT registered in main.py)
│   │   ├── solve.py           ← @click.command 'solve' (NOT registered in main.py)
│   │   ├── swarm.py           ← @click.group 'swarm' (NOT registered in main.py)
│   │   ├── system.py          ← help_cmd, doctor_cmd, version_cmd
│   │   ├── tool.py            ← @click.group 'tool' (NOT registered in main.py)
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
│   ├── registry/              ← Command registry (4 files, 1089-line _build())
│   │   └── registry.py (1089) ← Static command metadata catalog (~100 commands, 15 categories)
│   └── utils/                 ← Utilities (9 files)
│       ├── commands.py        ← AliasedGroup: Click with aliases + fuzzy suggestion
│       ├── compat.py          ← check_python, check_os, check_deps
│       ├── exit_codes.py      ← ExitCode IntEnum
│       ├── log.py             ← setup_logging()
│       ├── output.py (171)    ← Three-mode output contract — byte-identical to cli/output.py; mission group imports this
│       ├── slugs.py           ← Human-friendly slug generation
│       ├── telemetry.py       ← Command execution telemetry
│       └── docs_gen.py        ← Command docs generator
│
│   └── ui/                    ← UI rendering (not the Cockpit TUI)
│       ├── cockpit/           ← Textual TUI application (4 files)
│       │   ├── app.py (1028)  ← CockpitApp: live TUI dashboard
│       │   ├── widgets.py (2099) ← 11 widget types + log_search_started() + show_filter_input()
│       │   ├── consumer.py (131) ← Read-only Redis consumer
│       │   └── trace_replay.py ← Saved trace replay
│       ├── components/        ← Reusable Rich components
│       ├── renderers/         ← Output format renderers (incl. renderer_from_ctx)
│       ├── stream/            ← Streaming renderer
│       │   └── renderer.py (1133) ← Scroll-forward stream renderer: noise filter, paced reveal (0.15s), unique consumer names, per-message error isolation
│       ├── claude/            ← Splash + startup animation
│       ├── *.py               ← Scout UI, Forge UI, Furnace UI, tables, theme, console, input, splash
│
├── bus/                       ← Redis Streams message bus
│   ├── events.py (70)         ← 11 event type constants + 14 stream names + 9 consumer group names
│   ├── agent_events.py (237)  ← emit_agent_event(), AgentEventTracker, thinking-delta + subaction emitters
│   ├── publisher.py (51)      ← publish(): XADD to stream
│   ├── consumer.py (102)      ← consume_one(), consume_loop(), ensure_consumer_group()
│   └── checkpoint.py          ← Stream checkpointing
│
├── contracts/                 ← Domain models + typed event schemas + state machine
│   ├── domain.py (532)        ← SCHEMA_VERSION_V1, MissionBrief/MissionSpecification/CrashEvent
│   ├── events.py (260)        ← 19 typed EventPayload subclasses (Pydantic v2)
│   ├── state.py (426)         ← MissionPhase enum (21 values), transition matrix, MissionState
│   ├── errors.py              ← Domain error types
│   └── protocols.py           ← Protocol classes
│
├── orchestrator/              ← Job orchestration
│   ├── runtime.py (1199)      ← Main orchestration loop — OrchestratorRuntime.run() spawns 7 _consume_* coroutines
│   ├── job_runner.py (417)    ← run_job(): sequential in-process driver, returns JobResult
│   ├── job_queue.py (138)     ← Job queue
│   ├── health_monitor.py (113)← Agent health monitoring (heartbeat, restart)
│   ├── mission_report.py (1029)← Mission report generation
│   ├── patch_log_writer.py (50)← BLPOP from Redis → JSONL file
│   ├── reproducibility.py (292)← Git/config/data fingerprints for reproducibility
│   └── trace_persister.py (116)← Event trace persistence
│
├── runtime/                   ← Retry engine + execution helpers
│   ├── models.py (599)        ← Result, Context, Error types, MissionState (duplicate of contracts/state.py)
│   ├── paths.py               ← Path resolution
│   ├── retry_engine.py (295)  ← Retry execution engine
│   ├── retry_orchestrator.py (861) ← Orchestrated retry logic
│   ├── retry_strategy.py (286)← Retry strategy definitions
│   ├── retry_state.py         ← Retry state tracking
│   ├── capability_registry.py ← Agent capability registry
│   ├── ui_retry.py            ← UI retry integration
│   └── retry_log.py           ← Retry logging
│
├── shared/                    ← Shared utilities
│   ├── __init__.py
│   ├── metrics.py (389)       ← Prometheus metric definitions
│   └── health_monitor.py (112)← Health monitoring
│   (NOTE: shared/config.py and shared/logging.py do NOT exist — config lives in prometheus/core/config.py)
│
├── memory/                    ← Memory layer (Redis + ChromaDB)
│   ├── redis_client.py        ← Singleton async Redis client
│   ├── chroma_client.py       ← ChromaDB connection + collection helpers
│   ├── schemas.py             ← Memory record schemas
│   ├── embeddings.py          ← Embedding generation
│   ├── reasoning_models.py    ← Reasoning models
│   └── collections/           ← 4 collections: patch_memory, architecture_memory, tool_memory, experience_memory
│
├── evaluation/                ← Evaluation framework
│   ├── __init__.py            ← Dynamic feature-flag config via __getattr__ delegation
│   ├── benchmark_validation.py (248)
│   ├── stress_injector.py (260)
│   ├── perf_logger.py
│   ├── reproducibility.py
│   └── config.py              ← Feature-flag toggles
│
├── training/                  ← Training environment
│   ├── docker_manager.py (325)← Container lifecycle
│   ├── checkpoint_manager.py (44) ← Checkpoint save/restore
│   ├── label_normalizer.py (149) ← Deterministic label encoding across retries
│   └── base_training_image/   ← Dockerfile for training containers (lightgbm, xgboost, optuna, torch, transformers, pytorch-tabnet)
│
├── serving/                   ← Model serving
│   ├── onnx_runtime.py (47)   ← ONNX model loading and inference
│   ├── drift_monitor.py (93)  ← PSI-based drift detection
│   ├── metrics.py (75)        ← Prometheus metrics for serving
│   └── docker/                ← Serving container Dockerfile (fastapi, uvicorn, onnxruntime, prometheus-client)
│
├── learning/                  ← Execution outcome + planner feedback models
│   ├── execution_outcome.py
│   └── planner_feedback.py
│
├── figures/                   ← Paper figures (fig_architecture_*, fig_calibration_*, etc.)
│
├── experiments/               ← Experiment artifacts (gitignored)
│
├── tests/                     ← ⭐ Test suite (82 test files)
│   ├── __init__.py
│   ├── unit/                  ← 64 test files (FAST, flat — no per-agent subdirs)
│   │   ├── test_scout_tools.py, test_forge_decision_tree.py, test_dissect_taxonomy.py
│   │   ├── test_arbiter_metrics.py, test_bus_events.py, test_state_machine.py
│   │   ├── test_cockpit_*.py (5 files), test_validation_*.py (8 files), test_planner_*.py
│   │   ├── test_retry_orchestration.py, test_reliability.py, test_renderer_state.py
│   │   └── ... (all 64 flat)
│   ├── integration/           ← 12 files (Redis required; some Docker)
│   │   ├── test_titanic_e2e.py, test_three_kaggle_e2e.py
│   │   ├── test_furnace_dissect_loop.py, test_dissect_sandbox_docker.py
│   │   ├── test_harbor_serving.py, test_bus_e2e.py, test_job_runner.py, etc.
│   ├── services/              ← 5 files (agent, compat, profile, provider, workspace service tests)
│   ├── validators/            ← 1 file (test_registry.py)
│   ├── cli/                   ← conftest.py with mocked CLI services (no test files)
│   ├── research/              ← patch_log.jsonl only (no test files)
│   └── fixtures/              ← Test data (titanic.csv, 5 injected_error scripts, fuzz datasets)
│
├── research/                  ← Research experiment framework (15 .py files)
│   ├── benchmark/             ← problems.json (10 problems), baseline_v1.json, results/
│   ├── campaigns/             ← 15 campaign directories (pilot-v1, smoke-v2, verify-v3, etc.)
│   ├── validation/            ← Experiment tracking (models, runner, tracker, metrics, statistics)
│   ├── engineering/           ← Engineering dashboard
│   ├── run_benchmark.py (904) ← Main benchmark runner: Conditions A/B/C
│   ├── run_campaign.py (445)  ← Campaign runner (N runs, learning curves)
│   ├── run_ablation.py (579)  ← Ablation: 7 configs, all problems
│   ├── statistical_analysis.py (245) ← Mann-Whitney U + McNemar + Cohen's h
│   └── ... (analyze_ablation.py, analyze_campaign.py, compare_baselines.py, etc.)
│
├── scripts/                   ← Operational scripts + generated training scripts
│   ├── run_titanic_e2e.py, run_churn_e2e.py, publish_titanic.py, reset_titanic.py
│   ├── build-training-image.ps1, check_streams.py, check_stream_events.py, list_jobs.py
│   └── training_script_*.py    ← Generated scripts (gitignored)
│
├── outputs/                   ← Job outputs (models, checkpoints, reports, logs) — gitignored
├── data/                      ← Dataset files (CSVs gitignored)
├── docs/                      ← Documentation
│   ├── ADR/                   ← Architecture Decision Records
│   ├── ARCHITECTURE.md        ← Architecture overview
│   ├── CONVENTIONS.md         ← Coding conventions
│   ├── commands/              ← Generated CLI command docs
│   └── ERROR_TAXONOMY.md      ← Error taxonomy reference
├── frontend/                  ← Next.js dashboard (18 page.tsx routes)
│   ├── package.json           ← Next.js 14, React 18, Tailwind, Supabase, React Query
│   └── src/app/               ← Routes: dashboard, datasets, deployments, drift, feed, jobs/[id], missions, models, projects, settings, submit, training, login/register, etc.
├── infra/                     ← Infrastructure configs
│   ├── kubernetes/            ← serving deployment + LoadBalancer
│   ├── monitoring/            ← prometheus.yml, grafana_dashboard.json
│   └── helm/                  ← empty (only .gitkeep)
├── .claude/                   ← Claude Code settings (gitignored)
└── .github/workflows/         ← ci.yml (ruff + pytest on "main") + quality.yml (uv matrix on "master")
```

---

## 4. Core Concepts & Terminology (Glossary)

### Mission
A top-level workflow that takes a problem description + dataset through all 6 agents to a deployed endpoint. Created via `mission new`. Each mission gets a UUID `job_id` and an optional human-readable slug (e.g. "swift-falcon").

### Agent
One of six autonomous AI workers that perform a specific phase of the ML pipeline. Each agent runs in its own process, reads from Redis Streams, writes to Redis + ChromaDB, and publishes events.

### Canonical Mission Phases (21 values)
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

### Typed Events (19 types)
Defined in `contracts/events.py` as Pydantic `EventPayload` subclasses: `MissionBriefReadyEvent`, `TrainingScriptReadyEvent`, `EpochCompleteEvent`, `TrainingCompleteEvent`, `CrashEventPayload`, `ResumeTrainingEvent`, `EscalateEvent`, `EvaluationPassEvent`, `EvaluationRetryEvent`, `EvaluationFailedEvent`, `JobFailedEvent`, `EndpointLiveEvent`, `PlanCreatedEvent`, `PlanCompletedEvent`, `PlanFailedEvent`, `DriftAlertEvent`, `ThinkingDeltaEvent`, `SubactionProgressEvent`, `AgentEventPayload`.

### Stream Names (14 stream names)
Defined in `bus/events.py`: 11 primary streams in `ALL_EVENT_STREAMS` — `scout_output`, `forge_output`, `furnace_feed`, `furnace_output`, `furnace_crash`, `dissect_output`, `arbiter_output`, `harbor_output`, `orchestrator_output`, `planner_output`, `agent_events` — plus auxiliary `agent_thinking`, `thinking_delta`, `subaction_progress`. 9 consumer groups: `forge_consumers`, `furnace_consumers`, `dissect_consumers`, `arbiter_consumers`, `harbor_consumers`, `frontend_consumers`, `orchestrator_consumers`, `scout_consumers`, `cockpit_consumers`.

### Dissect Cascade (5 levels)
1. **Level 0 — Deterministic Rules** (`rules.py`): 10 regex-based repair functions
2. **Level 1 — Compiled Templates** (`repair_templates.py`): Pre-compiled repair patterns
3. **Level 2 — Repair Cache** (`repair_cache.py`): MD5-based fingerprint cache
4. **Level 3 — Patch Memory** (`knowledge_store.py`): ChromaDB semantic search
5. **Level 4 — LLM Reasoning**: Full LLM call with error context

### Cockpit
The live TUI dashboard (`prometheus/ui/cockpit/app.py`). Textual-based, shows real-time agent status, thinking tokens, logs, and event timeline. Launched via `prometheus` or as standalone.

### CLI Command Nouns (10 groups + 5 system commands)
Noun groups: `mission`, `agent`, `workspace`, `model`, `provider`, `config`, `plugin`, `evaluate`, `memory`, `planner`. System commands: `init`, `doctor`, `version`, `help`, `daemon`. There are **no redirect stubs** — the old `benchmark`, `deploy`, `job`, `logs`, `swarm`, `tool`, etc. command files still exist on disk but are **not registered** in `main.py`.

### Retry Engine
The `runtime/` package: orchestrates retry attempts across agents. Key classes: `RetryOrchestrator`, `RetryContext`, `RetryState`, `CapabilityRegistry`. Supports 4 strategies: exponential backoff, immediate, graceful degradation, fallback.

---

## 5. CLI / TUI Specification vs. Actual Implementation

### CLI Entry Point
- **Spec:** `prometheus` (console_scripts) or `python -m prometheus`
- **Actual:** `prometheus/main.py` — click.Group with `AliasedGroup` and lazy `register_fn`. Falls back to REPL if no subcommand given in TTY.
- **Status:** ✅ Working

### Global Options (main.py:142-190)
`-C/--project-dir`, `-w/--workspace`, `--no-color`, `--high-contrast`, `--font-size {small,medium,large}`, `--debug`, `--format {interactive,plain,json}`, `--shell` (hidden), `--version`, `--help`.

### Aliases (main.py:124-139)
Noun-level short forms: `ws`→workspace, `ag`→agent, `cfg`→config, `prov`→provider, `mdl`→model, `plug`→plugin, `miss`→mission, `eval`→evaluate, `mem`→memory, `plan`→planner. Convenience shortcuts: `new`→`mission new`, `start`→`mission new`.

### Registered Commands (15 total)

| Command | Syntax | Flags | Actual Behavior | Status |
|---------|--------|-------|----------------|--------|
| **mission** | `mission <subcommand>` | `--file`, `--target`, etc. | 9 subcommands: new, list, status, logs, watch, resume, cancel, report, replay. `new` submits to orchestrator. `watch` shows live Rich UI. | ✅ Verified in `cli/mission/__init__.py` (1722 lines) |
| **agent** | `agent list/inspect/trace` | None | Lists 6 agents, inspects details (+ tools list), traces job path. Uses `AgentService`. | ✅ Verified in `cli/agent.py` |
| **workspace** | `workspace init/info/scan/status` | None | Detects project root, scans files, reads pyproject.toml. | ✅ Verified in `cli/workspace.py` |
| **model** | `model list/show/export` | None | Scans outputs/ for eval reports, displays metrics, exports ONNX/pickle. | ✅ Verified in `cli/model.py` |
| **provider** | `provider add/list/current` | None | Manages LLM provider API keys in .env. | ✅ Verified in `cli/provider.py` |
| **config** | `config list/set/check/edit/show` | None | Reads/writes .env with credential redaction. | ✅ Verified in `cli/config.py` |
| **plugin** | `plugin install/remove/list` | None | Manages PluginRegistry. | ✅ Verified in `cli/plugin.py` |
| **evaluate** | `evaluate <subcommand>` | None | 10 subcommands: run, compare, report, visualize, list, failures, calibration, summary, wins, stats. Aggregates benchmark result JSONs. | ✅ Verified in `cli/evaluate.py` |
| **memory** | `memory stats/search` | None | ChromaDB + Redis queries via MemoryService. | ✅ Verified in `cli/memory.py` |
| **planner** | `planner <subcommand>` | None | 6 subcommands: inspect, dry-run, validate, stats, explain, prediction-error. Reads ExecutionPlan / engineering_plan from Redis. | ✅ Verified in `cli/planner.py` |
| **init** | `init` | None | First-run wizard: provider setup, API key, workspace init | ✅ Verified in `cli/init.py` |
| **doctor** | `doctor` | None | Runs prerequisite checks (Docker, Redis, Python, .env) | ✅ Verified in `cli/system.py` |
| **version** | `version` | None | Prints `0.1.0` | ✅ Verified in `cli/system.py` |
| **help** | `help` | None | Shows categorized command reference | ✅ Verified in `cli/system.py` |
| **daemon** | `daemon start/stop/status/restart/logs` | None | PID-based subprocess orchestration | ✅ Verified in `cli/daemon.py` |

### Unregistered Command Files (not wired in main.py)
`benchmark`, `deploy`, `explain`, `job`, `logs`, `profile`, `replay`, `report`, `reproduce`, `solve`, `swarm`, `tool` — these `.py` files still exist under `prometheus/cli/` but are **no longer registered** as commands. The 16 redirect stubs that CLAUDE.md previously documented were deleted from `main.py`.

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
| **Search functionality** | `log_search_started()` implemented (widgets.py:1680) + search modal on LogScreen | ✅ Fixed |
| **Filter functionality** | `show_filter_input()` implemented (widgets.py:1686) + filter-by-state modal on LogScreen | ✅ Fixed |

### Dissect Cascade Levels

| Level | Module | Actual Behavior | Status |
|-------|--------|----------------|--------|
| **L0 — Deterministic Rules** | `rules.py` (685 lines) | 10 fix_*() functions: fix_name_error, fix_import_error, fix_dtype_mismatch, fix_shape_mismatch, fix_nan_handling, etc. Each returns patched code or None. | ✅ Working |
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
  - L0: Match error against 24 taxonomy categories via regex → apply fix_*() rule
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

### Two Orchestrator Drivers (verified)

1. **`orchestrator/job_runner.py` (417 lines)** — sequential in-process driver: Scout→Forge→Furnace (with concurrent `dissect_listener` on `furnace_crash`)→Arbiter→Harbor (on PASS). Outcome read via `xrevrange`. Persists `MissionState`. Returns `JobResult`.
2. **`orchestrator/runtime.py` (1199 lines)** — event-driven `OrchestratorRuntime.run()`: sole consumer on all 7 agent streams via 7 `_consume_*` coroutines + `_heartbeat_loop`. Launches agents as libraries; only Furnace self-reads `dissect_output`.

---

## 7. Current Implementation Status

| Component | Status | Evidence |
|-----------|--------|----------|
| **6 Agent cores** (agent.py) | ✅ Working | All have real implementations with Redis I/O, event publishing, Prometheus metrics. None are stubs. Total: ~16,000 lines across 54 files. |
| **Contracts** (domain, events, state) | ✅ Working | Pydantic v2 models, 19 typed events, 21-state machine with transition matrix |
| **Event bus** (publisher, consumer) | ✅ Working | Redis Streams with consumer groups, checkpointing, typed events, agent_events emitters |
| **Orchestrator** (runtime + job_runner) | ✅ Working | Event-driven `OrchestratorRuntime` (1199 lines) + sequential `run_job()` driver, parallel Furnace↔Dissect crash recovery |
| **CLI** (10 noun groups + 5 system) | ✅ Working | click-based with AliasedGroup, aliases, fuzzy suggestions, zero redirect stubs, REPL fallback |
| **Cockpit TUI** | ✅ Working | Textual app, 11 widget types, live Redis streams, trace replay. Search & filter fixed. |
| **LLM provider** (Anthropic) | ✅ Working | Full integration with retry, token tracking, cost logging |
| **Forge templates** (10 templates) | ✅ Working | Jinja2 rendering for all 5 architectures + task variants |
| **Dissect cascade** (5 levels) | ✅ Working | L0-L4 with deterministic rules, templates, cache, ChromaDB, LLM |
| **Retry engine** (runtime/) | ✅ Working | Orchestrator, 4 strategies, state tracking, capability registry |
| **Prometheus metrics** | ✅ Working | Counter/Gauge/Histogram for all agent categories |
| **Memory** (Redis + ChromaDB) | ✅ Working | 4 collections, embeddings, semantic search |
| **Research framework** | ✅ Working | Benchmark runner (10 problems, 3 conditions), ablation (7 configs), statistics (Mann-Whitney, McNemar, Cohen's h) |
| **Docker management** | ✅ Working | Container lifecycle, health checks, GPU support |
| **Script fingerprinting** | ✅ Working | SHA-256 dedup — skips training if identical script succeeded before |
| **Error prevention** (static + Redis) | ✅ Working | 5 static prevention transformations + Redis-backed PreventionRules |
| **Patch log writer** | ✅ Working | BLPOP from Redis → JSONL file with filelock |
| **Label normalizer** | ✅ Working | Training module for deterministic label encoding across retries |
| **Drift monitor** | ✅ Working | PSI-based, 3600s interval, 0.2 threshold |
| **Frontend (Next.js)** | 🟡 Partial | 18 routes exist (dashboard, jobs/[id], drift, missions, etc.), Redis client partial |
| **Tool memory** | 🟡 Partial | ChromaDB collection exists, semantic retrieval partially wired |
| **GKE/Kubernetes deployment** | ⚪ Planned | infra/kubernetes exists but configs are minimal |
| **OpenAI provider** | ⚪ Planned | Base class exists, no integration |
| **Built-in plugins** | 🔴 Stubbed | Plugin system exists, builtin/ directory is empty |

---

## 8. Known Issues, Bugs & Open Hypotheses

### Resolved (as of 2026-08-01)

| # | Bug | File | Status |
|---|-----|------|--------|
| A | **No LabelEncoder in tabular training scripts** | `agents/forge/templates/*.jinja` | ✅ Fixed — LabelEncoder already present in all 4 templates + 3 f-string generators |
| B | **TabNet proposed but pytorch-tabnet not installed** | `training/base_training_image/Dockerfile` | ✅ Fixed — `pytorch-tabnet==4.1.0` in Dockerfile |
| C | **`state.imbalance_strategy` not updated after crash** | `runtime/retry_orchestrator.py` | ✅ Fixed |
| D | **`best_metric` stays 0.0** | `runtime/models.py:368` | ✅ Fixed — unconditional `metric_value > best_metric` check |
| E | **Same as Bug C — after success too** | `runtime/retry_orchestrator.py` | ✅ Fixed |
| F | **`wait_for_dissect=False` hardcoded during retry** | `runtime/retry_orchestrator.py` | ✅ Fixed — concurrent Furnace + Dissect handler tasks |
| 1 | Cockpit `search` fails | `prometheus/ui/cockpit/widgets.py` | ✅ Fixed — `log_search_started()` implemented (line 1680) |
| 2 | Cockpit `filter` fails | `prometheus/ui/cockpit/widgets.py` | ✅ Fixed — `show_filter_input()` implemented (line 1686) |
| 5 | Dissect prompt only lists 11 categories | `agents/dissect/prompts.py` | ✅ Fixed — prompt lists all 24 categories |
| 7 | pyproject.toml dependencies incomplete | `pyproject.toml` | ✅ Fixed — full ML/infra set added |

### Active Issues (verified 2026-08-01)

| # | Issue | File | Severity |
|---|-------|------|----------|
| 3 | ~~Directory misspelled `orchestator`~~ | ~~orchestator/~~ | ✅ Resolved — the directory is spelled `orchestrator` (correct). The prior doc claim was stale. Only residue: a docstring in `tests/integration/test_orchestrator_escalate.py`. |
| 4 | **Duplicate MissionState definitions** — `contracts/state.py` (Pydantic) vs `runtime/models.py` (dataclass) both define MissionState. runtime/models.py admits the duplication ("keep these fields in sync"). Only the contracts version is imported by orchestrator code. | `runtime/models.py` vs `contracts/state.py` | 🟡 Divergence risk — kept in sync manually |
| 6 | **PLAN.md is 3150+ lines of historical build steps** | `PLAN.md` | 🟡 Awareness — build log, not design doc |
| 8 | **README.md test count is wrong** — README claims "All 47 tests pass"; actual: 82 test files (64 unit, 12 integration, 5 services, 1 validators) | `README.md` | 🟡 Low — stale doc (being fixed) |
| 9 | **README.md phase status is wrong** — claims Phase 3 "In progress" and Phase 4 "Not started" — actual state is beyond Phase 3.5 with research campaigns complete | `README.md` | 🟡 Low — stale doc (being fixed) |
| 10 | **No Makefile exists** — CLAUDE.md and README reference `make lint/test/typecheck/...` but no `Makefile` is in the repo. Use the documented pip/pytest commands directly. | repo root | 🟡 Low — doc references must not rely on `make` |
| 11 | **CI branch inconsistency** — `.github/workflows/ci.yml` triggers on `main`; `.github/workflows/quality.yml` triggers on `master`. | `.github/workflows/` | 🟡 Low — quality.yml may never fire |
| 12 | **REPL help is stale** — `prometheus/repl.py` (~line 32) still lists the 16 "redirect stubs" that no longer exist in `main.py`. | `prometheus/repl.py` | 🟡 Low — cosmetic |
| 13 | **pyproject.toml still missing 5 runtime deps** — `joblib`, `pygments`, `pyyaml`, `packaging`, `pynput` exist only in requirements.txt (pinned 2026-07-27), not in pyproject.toml | `pyproject.toml` | 🟢 Reconciled — requirements.txt is the authoritative install path |

### Previously Documented Items — Now Corrected

| Old Claim | Actual (2026-08-01) |
|-----------|---------------------|
| Directory spelled `orchestator` (missing 'r') | Directory is `orchestrator` (correct) |
| 13 command groups + 16 redirect stubs | 15 registered commands (10 noun + 5 system), 0 redirects |
| 20 MissionPhase values | 21 values (verified enum in contracts/state.py) |
| 16 typed events | 19 EventPayload subclasses (incl. ThinkingDelta, SubactionProgress, AgentEvent) |
| 11 streams / 8 consumer groups | 14 stream names / 9 consumer groups |
| 31 error taxonomy categories | 24 categories (verified TaxonomyEntry list) |
| `shared/config.py` + `shared/logging.py` exist | Do NOT exist — config moved to `prometheus/core/config.py` |
| problems.json = 50 problems | 10 problems |
| 77 test files (CLAUDE.md) / "47 tests pass" (README) | 82 test files |
| `Makefile`, `deploy_update_app.py`, top-level `UI/` exist | None of these exist |
| `main.py` 327 lines, `mission/__init__.py` 1158 lines | 310 and 1722 |

---

## 9. Pending Design Decisions

| Question | Options | Current Leaning | Tradeoffs |
|----------|---------|-----------------|-----------|
| **Default orchestrator: sequential vs event-driven?** | A) Sequential `job_runner.py` (in-process) vs B) Event-driven `orchestrator/runtime.py` (Redis Streams, async) | Both implemented; B is the current path | A is simpler, B is more robust for crash recovery |
| **Training container: Docker vs local subprocess?** | Docker (isolated, portable) vs local subprocess (faster, simpler) | Docker — current implementation uses Docker for training | Docker adds latency but is required for sandbox testing and isolation |
| **MissionState canonical location?** | `contracts/state.py` or `runtime/models.py` | `contracts/state.py` — canonical Pydantic version; runtime keeps a synced dataclass | Dual representation maintained for different serialization needs |
| **OpenAI provider integration?** | Full implementation or defer | Deferred — Anthropic is the only active provider | OpenAI support would broaden accessibility |
| **Frontend priority?** | Complete Next.js dashboard or leave as scaffolded | Currently scaffolded — focus is on CLI/TUI | Web dashboard would improve accessibility but is not needed for research |

---

## 10. Design History & Rationale

### Key Architectural Decisions

- **Redis Streams over Kafka:** Single-node research deployment. Redis is simpler, requires no ZooKeeper, and is already used for job state. The bus layer has 5 files totaling ~600 lines.
- **ChromaDB over Pinecone:** Self-hosted research deployment. No API costs, no data leaves the local machine. Latency is higher but acceptable for research workloads.
- **Jinja2 templates over programmatic script generation:** Templates are debuggable — you can read the actual template file and see exactly what will be generated. This was critical during development when Forge's LLM-generated scripts were unreliable.
- **Textual TUI over web dashboard:** Real-time operational visibility during development. The Cockpit shows thinking tokens, cascade decomposition, and live metrics — information density that's harder to achieve in a web UI.
- **click over argparse:** Developer experience. click's declarative command groups, automatic help generation, and plugin-friendly design made it the right choice for 10+ command nouns.
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
- **Total files: 82 `test_*.py` files** (64 unit + 12 integration + 5 services + 1 validators). Verified by counting `test_*.py` on 2026-08-01. The README's "All 47 tests pass" and any "77 test files" claim are stale.

### Test Distribution (verified 2026-08-01)

| Directory | Count | Notes |
|-----------|-------|-------|
| `tests/unit/` | 64 files | **Flat** — no per-agent subdirectories. Includes scout, forge, furnace, dissect, arbiter, harbor tests, 5 Cockpit tests, 8 validation tests, planner, retry, reliability, renderer_state, mission output contracts, mission logs trace fidelity, etc. |
| `tests/integration/` | 12 files | Require Redis (aioredis at localhost:6379); some require Docker. Titanic/3-Kaggle E2E, furnace-dissect loop, dissect sandbox, harbor serving, bus E2E, job_runner, orchestrator escalate, orchestrator titanic, scenarios, trace_persister. |
| `tests/services/` | 5 files | agent_service, compat, profile_service, provider_service, workspace_service |
| `tests/validators/` | 1 file | test_registry.py |
| `tests/cli/` | 0 test files | Only `conftest.py` with mocked CLI services (MagicMock + CliRunner) |
| `tests/research/` | 0 test files | Only `patch_log.jsonl` data |
| `tests/fixtures/` | — | titanic.csv, 13 fuzz CSVs, 5 injected_errors, golden phase7 JSONs |

### Key Coverage Observations

- **All 6 agents** have dedicated tests (in the flat `tests/unit/`)
- **Dissect** has 5 injected-error test fixtures for real crash testing
- **Cockpit TUI** has 5 test files (live Redis, cascade, replay, full mission, pilot)
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
8. Add tests in `tests/unit/` (flat) and `tests/integration/`
9. Add agent-specific Prometheus metrics in `serving/metrics.py`

### How to Add a New CLI Command
1. Create file in `prometheus/cli/<name>.py` with `@click.group` or `@click.command`
2. Export from `prometheus/cli/__init__.py`
3. Register in `prometheus/main.py:_register_commands()` (`cli.add_command(...)`)
4. Add `Command` entry to `prometheus/registry/registry.py:_build()` (1089-line function)
5. Do NOT add a redirect stub — the redirect mechanism was removed

### Test Structure Convention
- Test files live **flat** in `tests/unit/` (e.g., `agents/scout/tools.py` → `tests/unit/test_scout_tools.py`)
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

> **Note:** There is no `Makefile` in this repository. Use the pip/pytest/uv commands directly. The `make lint/test/...` commands in older docs no longer apply.

### Running Tests
```bash
# All tests
pytest tests/ -v

# Fast tests only (no Docker/Redis)
pytest tests/ -m "not slow" -v

# Specific test file
pytest tests/unit/test_scout_tools.py -v

# Integration tests (requires running Docker + Redis)
pytest tests/integration/test_titanic_e2e.py -v -s
```

### Linting & Formatting
```bash
# Ruff lint
ruff check .

# Ruff format check
ruff format --check .

# Pre-commit hooks (ruff, ruff-format, black, bandit, generic hooks)
pre-commit run --all-files
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
| `prometheus/main.py` | click.Group bootstrap, 15 commands + REPL |
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
| `agents/dissect/taxonomy.py` | 24 error category taxonomy |
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
| `contracts/domain.py` | SCHEMA_VERSION_V1, base types, MissionBrief/MissionSpecification/CrashEvent |
| `contracts/events.py` | 19 typed EventPayload Pydantic models |
| `contracts/state.py` | MissionPhase (21 values), transition matrix, MissionState |
| `bus/events.py` | Stream names, consumer groups, event type constants |
| `bus/agent_events.py` | Thinking-delta + subaction emitters, AgentEventTracker |
| `bus/publisher.py` | publish() — XADD to Redis Streams |
| `bus/consumer.py` | consume_one(), consume_loop() — XREADGROUP with ACK |
| `bus/checkpoint.py` | Stream checkpointing |

### Orchestration
| File | Purpose |
|------|---------|
| `orchestrator/runtime.py` | Event-driven orchestration loop (1199 lines) |
| `orchestrator/job_runner.py` | Sequential in-process job lifecycle (417 lines) |
| `orchestrator/health_monitor.py` | Agent health monitoring (heartbeat, restart) |
| `orchestrator/patch_log_writer.py` | BLPOP from Redis → JSONL file |
| `orchestrator/reproducibility.py` | Git/config/data fingerprints |
| `runtime/retry_orchestrator.py` | Orchestrated retry logic (861 lines) |
| `runtime/retry_strategy.py` | 4 retry strategies |
| `runtime/models.py` | Result, Context, Error types + duplicate MissionState |

### CLI
| File | Purpose |
|------|---------|
| `prometheus/cli/mission/__init__.py` | Mission command (1722 lines) — the main user-facing command |
| `prometheus/cli/mission/ui.py` | Rich live-updating UI for all 6 agent phases (710 lines) |
| `prometheus/cli/agent.py` | Agent management commands |
| `prometheus/cli/config.py` | Configuration management commands |
| `prometheus/utils/output.py` | Three-mode output contract (interactive/plain/json) — the twin of cli/output.py that mission imports |
| `prometheus/registry/registry.py` | 1089-line command catalog (~100 commands) |

### Cockpit TUI
| File | Purpose |
|------|---------|
| `prometheus/ui/cockpit/app.py` | CockpitApp: Textual live dashboard (1028 lines) |
| `prometheus/ui/cockpit/widgets.py` | 11 widget types + search/filter modals (2099 lines) |
| `prometheus/ui/cockpit/consumer.py` | Read-only Redis consumer for agent events |
| `prometheus/ui/stream/renderer.py` | Scroll-forward streaming renderer (1133 lines) |

### Infrastructure
| File | Purpose |
|------|---------|
| `memory/redis_client.py` | Singleton async Redis client |
| `memory/chroma_client.py` | ChromaDB connection helpers |
| `training/docker_manager.py` | Docker container lifecycle (325 lines) |
| `training/checkpoint_manager.py` | Checkpoint save/restore (44 lines) |
| `training/label_normalizer.py` | Deterministic label encoding (149 lines) |
| `serving/onnx_runtime.py` | ONNX inference runtime (47 lines) |
| `serving/drift_monitor.py` | PSI-based drift detection (93 lines) |
| `serving/metrics.py` | Prometheus metric definitions (75 lines) |
| `shared/metrics.py` | Prometheus metric definitions (389 lines) |

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

This section lists everything that was not fully confirmed during this audit.

1. **Actual test pass rate.** Counted 82 test files but did not run `pytest` to confirm pass rate. The README claims "47 tests pass" which is contradicted by the 82-file count. The actual number may be different.

2. **`runtime/models.py` vs `contracts/state.py` duplication.** Both define `MissionState`. The `contracts/` version is the canonical one; `runtime/models.py` documents that fields must stay in sync. Not diffed field-by-field.

3. **ChromaDB integration test.** Confirmed `chroma_client.py` and collection modules exist but did not run an end-to-end ChromaDB query test to verify the semantic search pipeline works end-to-end.

4. **OpenAI provider.** `agents/openai_provider.py` does not exist at the expected path. The provider code lives in `prometheus/providers/` and the OpenAI provider there is base-class-only. Full integration status is unverified.

5. **Memory collection count.** Confirmed `patch_memory`, `architecture_memory`, `tool_memory`, and `experience_memory` collection modules exist. Semantic retrieval quality unverified.

6. **CI green status.** `.github/workflows/ci.yml` is substantive (ruff + pytest with Redis service + deploy-check) but the last run's green/red status was not verified. `quality.yml` triggers on `master` while `ci.yml` uses `main` — a live inconsistency.

7. **All 10 benchmark problems.** Confirmed `research/benchmark/problems.json` has 10 problems (each with id/dataset/task_type/modality/evaluation_metric/difficulty/expected_architecture). Did not run them.

8. **Frontend build status.** The Next.js frontend has 18 page.tsx routes. Did not verify it currently builds or runs.

9. **Furnace subprocess vs Docker.** `furnace/agent.py` has both `_launch_and_monitor_docker` and `_launch_and_monitor_subprocess`. Which is the default path in production was not fully traced.

10. **`src/` directory.** A `src/` directory exists at the top level but is gitignored ("External / unrelated code"). Its contents (assistant, bootstrap, bridge, buddy, cli, commands, components, constants, context, coordinator, ...) appear unrelated to the main pipeline.
