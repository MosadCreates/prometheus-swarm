# CLAUDE.md — Prometheus Swarm

> Last full audit: **2026-09-15**. Every claim below was re-verified by reading
> the actual source (complete 5-part deep read: agents/, bus+contracts+
> orchestrator+runtime, CLI/UI, infra/memory/training/serving,
> research/tests/skills/frontend), not inferred from filenames or prior docs.
> Major corrections vs. the 2026-08-01 snapshot: the CLI now registers **19
> commands** (skill, deploy, profile, docs added; the old orphan command files
> were deleted); the command registry is **generated from the live click tree**
> (~81 entries, no static catalog); tests total **97 files** (79 unit);
> runtime LLM calls happen **only inside Dissect**; several documented "fixes"
> (label_normalizer wiring, ChromaDB ALLOW_RESET guard) were never actually
> wired — see §8.

---

## 1. Project Identity & Purpose

**Prometheus Swarm** is an autonomous multi-agent system that accepts a raw natural-language description of an ML problem and a dataset, then returns a fully trained, evaluated, and live-served model endpoint — without human intervention.

**Owner:** Mohamed Mosad Ghonaim — solo builder.

**Language split:** ~99% Python, ~1% TypeScript (Next.js frontend). Python 3.11+ target.

**Goal:** ML-as-a-service SaaS + research publication at MSR 2026 or ASE 2026. The core research contribution is **Dissect**: autonomous self-patching of ML training failures.

**Tagline:** "You describe the task. The swarm does the rest."

**Honest framing of the "agents":** despite six agent classes with system prompts, only **Dissect Level 4** (and its taxonomy fallback labeling) ever calls the Anthropic API at runtime. Scout, Forge, Furnace, Arbiter, and Harbor are deterministic pipelines wrapped in agent-shaped classes. This is a design strength for reproducibility — document it as such in the paper.

---

## 2. High-Level Architecture

Six specialized agents coordinate through a **Redis Streams** message bus. No agent imports another. Each agent has its own system prompt (mostly documentation-shaped — see §1), tools, and memory scope.

### The Six Agents

| Agent | Role | Trigger | Output |
|-------|------|---------|--------|
| **Scout** | Perceiver | job hash → `MissionBrief` + `MissionSpecification` | `MISSION_BRIEF_READY` |
| **Forge** | Architect | `MISSION_BRIEF_READY` → training script | `TRAINING_SCRIPT_READY` |
| **Furnace** | Trainer | `TRAINING_SCRIPT_READY` → trained model | `TRAINING_COMPLETE` / `CRASH_EVENT` |
| **Dissect** | Debugger | `CRASH_EVENT` → patched script | `RESUME_TRAINING` / `ESCALATE` |
| **Arbiter** | Evaluator | `TRAINING_COMPLETE` → PASS/RETRY/FAIL | `EVALUATION_PASS` / `EVALUATION_RETRY` / `ESCALATE` |
| **Harbor** | Deployer | `EVALUATION_PASS` → live endpoint | `ENDPOINT_LIVE` |

### Orchestration pattern

**Sequential with a crash-recovery loop:** Scout → Forge → Furnace ⟷ Dissect (loop) → Arbiter → Harbor. Two drivers exist and their semantics **diverge** (§6, §8): event-driven `OrchestratorRuntime` (runtime.py) and sequential `run_job()` (job_runner.py, used by `mission new --block`, the benchmark, and ablations).

### Communication

All inter-agent communication via **Redis Streams** (`bus/`) with typed Pydantic events (`contracts/events.py`) plus Redis KV for state. Orchestrator owns consumer groups and state transitions; agents are launched **in-process as libraries** by runtime.py's consumer coroutines.

### Memory

- **Redis** (KV + Streams): `job:{job_id}:*` keys (mission_state, mission_brief, mission_spec, search_space, engineering_plan, api_cost, crash_count, reproducibility, execution_outcome, …), `patch_log_queue` (list), `forge:prevention_rules`, `forge:script_fp:*`, `forge:error_stats*`, `skill:{name}:{agent}:stats`, `orch:heartbeat`.
- **ChromaDB** (vector store, `memory/collections/`): 4 collections — `patch_memory`, `architecture_memory`, `tool_memory`, `experience_memory`. Embeddings: SentenceTransformer `all-MiniLM-L6-v2` (graceful no-op if unavailable).

---

## 3. Repository Structure

Flat top-level layout (agents/, bus/, contracts/, orchestrator/, … at root). Line counts verified 2026-09-15.

```
prometheus-swarm/
├── .env / .env.example        ← Environment config (gitignored)
├── .pre-commit-config.yaml    ← ruff + black + bandit hooks
├── AUDIT.md · PLAN.md         ← Historical sprint/build docs (PLAN.md is a build log, not a design doc)
├── Prometheus_CLI_UX_Design_Book.md / ..._Master_Prompt.md  ← CLI specs (spec, not implementation reference)
├── RESULTS_SCHEMA.md          ← Benchmark result schema (patch-log entries now carry fields beyond it: llm_used_for_repair, cascade_level, …)
├── docker-compose.yml         ← redis 7.2 + chromadb 0.5.0 + orchestrator (profile "full"; ⚠ see §8 ALLOW_RESET, docker.sock mount)
├── Dockerfile · start.ps1     ← App image; Windows dev bootstrap (infra → orchestrator job → frontend)
├── requirements.txt           ← Authoritative pinned deps (pyproject drift exists — §8)
├── pyproject.toml · uv.lock
│
├── agents/                    ← ⭐ Six AI agents (~17k lines)
│   ├── base.py                ← BaseAgent ABC: own RedisClient, SkillRegistry.for_agent, call_llm + _log_api_cost ($3/$15 per 1M)
│   ├── llm_client.py          ← AsyncAnthropic wrapper; ANTHROPIC_MODEL default claude-sonnet-4-6; 4096 max_tokens, 300s, 3 retries
│   ├── skills/                ← ⭐ Installable skill platform (base/context/manifest/loader/registry/installer/signing/subprocess_runner)
│   ├── scout/                 ← agent.py 470 · tools.py ~600 · reasoning.py (10 pure reason_* functions) · prompts.py
│   ├── forge/                 ← agent.py · tools.py 1359 (5 f-string script generators, define_optuna_space)
│   │                            decision_tree.py · planner.py · template_renderer.py · registry.py (validate_all at import)
│   │                            confidence_router.py (0.85/0.55 thresholds) · static_prevention.py · prevention.py
│   │                            script_fingerprint.py (forge:script_fp:*) · quality_feedback.py (forge:error_stats*)
│   │   └── templates/         ← 9 Jinja2 StrictUndefined templates (lgbm/xgb × binary/multi/reg, tabnet, distilbert/efficientnet × binary/multi)
│   ├── furnace/               ← agent.py 1130 (Docker default, subprocess fallback, 10-min dissect wait) · tools.py (legacy)
│   ├── dissect/               ← agent.py 1147 · routing.py 676 (cascade) · taxonomy.py 552 (24 categories) · rules.py 685 (18 RULES)
│   │   ├── skills/            ← 6 bundled Dissect skills (crash_localizer, error_signature_extractor, taxonomy_expander,
│   │   │                        cascade_stats, patch_assertion_generator, rule_generalizer)
│   │   ├── repair_templates.py · repair_cache.py (md5, separate scheme) · knowledge_store.py (Redis llm queue)
│   │   ├── fingerprint.py (sha256 + FingerprintStore) · governor.py (per-fingerprint budget) · budget.py (per-job budget)
│   │   ├── validation.py (validate_patch_pre/post) · patch_log.py (RPUSH patch_log_queue only) · models.py · ui.py · prompts.py
│   ├── arbiter/               ← agent.py · decision.py (PASS/RETRY/FAIL, 15% window) · evaluator.py · controller.py (legacy path)
│   │   └── tools.py · report.py · ui.py · prompts.py
│   └── harbor/                ← agent.py 581 · tools.py (ONNX/TorchScript/pickle chain, FastAPI gen, compose+GKE deploy, drift loop)
│       └── serving_template.py · artifact_validator.py (pre-deploy gate) · prompts.py
│
├── prometheus/                ← CLI application package
│   ├── __main__.py · main.py (319)   ← AliasedGroup; 19 registered commands; splash --help; REPL fallback
│   ├── repl.py                        ← natural-language path (unknown word → `mission new <text>`), `:shortcuts`, `!n` history
│   ├── cli/
│   │   ├── mission/__init__.py (1751) ← 9 subcommands: new list status logs watch resume cancel report replay
│   │   │     session.py (DEAD — MissionSession never used) · state_logger.py (live; imported by 4 agents + retry) · ui.py (mostly orphaned)
│   │   ├── skill.py · deploy.py · profile.py     ← newly registered command groups
│   │   ├── agent.py · config.py · daemon.py · evaluate.py · init.py · memory.py · model.py
│   │   ├── planner.py · plugin.py · provider.py · system.py (init/doctor/version/help/docs) · workspace.py
│   │   ├── output.py                  ← ⚠ DEAD twin of utils/output.py (mission imports utils version)
│   │   └── (benchmark/explain/job/logs/replay/report/reproduce/solve/swarm/tool: DELETED from disk)
│   ├── services/            ← AppContext (lazy props) + agent/config/job/memory/provider/profile/skill/workspace services
│   │                          ⚠ memory_service.py permanently broken (imports nonexistent funcs, swallowed ImportError)
│   ├── contracts/           ← 6 thin ABCs (ProfileService/SkillService/PluginRegistry implement none)
│   ├── core/                ← config.py (doctor prereqs only) · redis.py (CliRedis 2nd wrapper) · docker.py (serving containers)
│   │   live_progress.py (⚠ BROKEN: status/phase key mismatch; unused) · pipeline.py (⚠ DEPRECATED but still routed via
│   │   submission.py→JobService.submit, trains use_docker=False) · serving.py (9-line predict client) · project.py
│   ├── dto/ · models/ · schemas/ (⚠ schemas/ has zero importers — dead 4th config surface)
│   ├── mission/ · planner/ · plugins/ (builtin/ EMPTY)
│   ├── registry/            ← registry.py (69 lines) — _build() delegates to generate.build_from_cli(): walks the LIVE
│   │                          click tree → ~81 Command entries; search.py (fuzzy ladder, threshold .45); no static catalog
│   ├── utils/               ← commands.py (AliasedGroup + fuzzy 0.4) · output.py (live 3-mode contract) · exit_codes.py
│   │   telemetry.py (~/.prometheus/telemetry/commands.ndjson) · log.py · slugs.py (adjective-noun-4hex) · compat.py · docs_gen.py
│   └── ui/
│       ├── cockpit/         ← Textual TUI: app.py (~1030) + widgets.py (~2100, search/filter modals FIXED) + consumer.py + trace_replay.py
│       ├── stream/renderer.py (~1194) ← the DEFAULT live UI (Claude-style stream renderer; paced reveal 0.15s, badge rewrite, noise filter)
│       ├── claude/ (splash, unified_live.run_quiet for piped mode) · components/ · renderers/ · *.py (Scout/Forge/Furnace panels — legacy)
│
├── bus/                     ← events.py (70: 24 event constants, 14 stream names, 9 groups) · publisher.py (XADD, no MAXLEN)
│   │                          consumer.py (ensure_consumer_group used; consume_one/loop nearly dead)
│   ├── agent_events.py      ← emit_agent_event / AgentEventTracker / emit_thinking_delta / emit_subaction_progress
│   └── (checkpoint.py does NOT exist)
├── contracts/               ← domain.py (532) · events.py (260: 19 payloads) · state.py (426: canonical 21-phase machine)
│                              (errors.py / protocols.py do NOT exist)
├── orchestrator/            ← runtime.py (1199, event-driven driver) · job_runner.py (sequential driver) · job_queue.py
│   health_monitor.py (⚠ DEAD — reclaim never wired) · mission_report.py (~1030) · patch_log_writer.py (BLPOP→JSONL+filelock)
│   reproducibility.py · trace_persister.py (10th consumer group "trace_persister")
├── runtime/                 ← retry_engine.py · retry_orchestrator.py (~860) · retry_strategy.py (4 escalation dimensions)
│   retry_state.py (legacy shim) · capability_registry.py · ui_retry.py · retry_log.py · paths.py (single path registry)
│   models.py (⚠ duplicate MissionState WITH REAL DRIFT vs contracts/state.py — §8)
├── memory/                  ← redis_client.py (async, NOT a singleton despite docstring) · chroma_client.py (singleton,
│   │                          ⚠ no ALLOW_RESET guard) · schemas.py · embeddings.py · reasoning_models.py
│   └── collections/         ← experience_memory · architecture_memory · patch_memory · tool_memory
├── training/                ← docker_manager.py (⚠ NO GPU support at all) · base_training_image/Dockerfile
│   checkpoint_manager.py (⚠ DEAD, zero importers) · label_normalizer.py (⚠ DEAD — "Bug 7 fix" never wired into Forge)
├── serving/                 ← drift_monitor.py (compute_psi used by Harbor; check_drift DEAD) · metrics.py (⚠ ENTIRELY DEAD)
│   │                          onnx_runtime.py (DEAD) · docker/Dockerfile (DEAD — Harbor generates its own)
├── shared/                  ← metrics.py (404: THE live metric registry, swarm_* prefix, /metrics :9090 started by runtime.py)
│   health_monitor.py (live) · (config.py / logging.py do NOT exist)
├── evaluation/              ← config.py (5 env flags read fresh) · stress_injector.py · benchmark_validation.py
│   perf_logger.py (PROFILE_MODE-gated) · reproducibility.py (CV≥0.05 check; test-only)
├── learning/                ← execution_outcome.py (⚠ meta dict never stored to Chroma) · planner_feedback.py
├── research/                ← run_benchmark.py (~900: conditions A/B/C) · run_campaign.py · run_ablation.py (7 configs)
│   statistical_analysis.py (reads DEPRECATED baseline_v1!) · analyze_*/compare_* · validation/ (ExperimentSet framework)
│   engineering/ · benchmark/problems.json (10 problems) · benchmark/baseline_v1.json (self-declared deprecated; v2 authoritative)
│   campaigns/ (15 dirs) · reports/
├── experiments/             ← ~270 ExperimentSet JSON dumps (git noise — modified on every research run)
├── figures/                 ← Paper figures (regenerated; large working-tree diff)
├── scripts/                 ← run_*_e2e.py, check_streams.py, publish_titanic.py, reset_titanic.py, clean_consumer_groups.py,
│   │                          build-training-image.ps1, …  ⚠ ~330 orphan training_script_*.py artifacts (cleanup failed historically)
├── tests/                   ← ⭐ 97 test files: 79 unit/ (flat) + 12 integration/ + 5 services/ + 1 validators/test_registry.py
│   │                          cli/conftest.py only; research/patch_log.jsonl; fixtures/ (⚠ titanic.csv DELETED — breaks 3 tests)
│   └── fixtures/{injected_errors/, fuzz/, skill_contexts/, golden_phase7_*.json}
├── frontend/                ← Next.js 14 App Router, 18 routes, 7 direct-Redis API routes, Supabase auth; 8 pages mock-only (demo-grade)
├── infra/                   ← kubernetes/ (Deployment+LoadBalancer, :latest image), helm/prometheus-serving/ (REAL chart 0.1.0),
│   │                          monitoring/ (prometheus.yml localhost targets, Grafana dashboard)
├── data/ · outputs/ · experiments/ (gitignored/mutable)
└── docs/                    ← ONLY SKILL_INSTALL_GUIDE.md + generated commands/ (ARCHITECTURE.md, ERROR_TAXONOMY.md, ADR/ do NOT exist)
```

---

## 4. Core Concepts & Terminology (Glossary)

### Mission
Top-level workflow: problem description + dataset → deployed endpoint. `mission new` creates a UUID `job_id` + deterministic slug (`adjective-noun-4hex`).

### Agent
One of six autonomous workers. Triggered by events, reads/writes Redis, publishes typed events, records `swarm_*` metrics and `emit_agent_event` UI events via `AgentEventTracker`.

### Canonical Mission Phases (21 values) — `contracts/state.py:MissionPhase`
`MISSION_CREATED → SCOUT_RUNNING → SCOUT_COMPLETED → FORGE_RUNNING → FORGE_COMPLETED → FURNACE_RUNNING → FURNACE_COMPLETED | TRAINING_FAILED`; `TRAINING_FAILED → DISSECT_RUNNING → DISSECT_COMPLETED → FURNACE_RUNNING` (crash-recovery loop) | `RETRY_PENDING`; `ARBITER_RUNNING → ARBITER_COMPLETED → {RETRY_PENDING, MISSION_PASSED, MISSION_FAILED}`; `RETRY_PENDING → RETRY_RUNNING → {FORGE_RUNNING, RETRY_COMPLETED}`; `RETRY_COMPLETED → ARBITER_RUNNING`; `MISSION_PASSED → {HARBOR_DEPLOYING → HARBOR_COMPLETED | SCOUT_RETRAIN}`; `SCOUT_RETRAIN → SCOUT_RUNNING`. Sinks: `CANCELLED`, `MISSION_FAILED`. Every state also allows CANCELLED. `validate_phase_transition` raises `ValueError` on illegal moves; `transition_and_save()` is the load→mutate→SET helper (⚠ non-atomic). `canonical_phase()` normalizes ~44 legacy status strings.

### Typed Events (19 payloads / 24 constants)
`contracts/events.py`: MissionBriefReady, TrainingScriptReady, EpochComplete, TrainingComplete, CrashEventPayload, ResumeTraining, Escalate, EvaluationPass/Retry/Failed, JobFailed, EndpointLive, PlanCreated/Completed/Failed, DriftAlert, ThinkingDelta, SubactionProgress, AgentEventPayload. `bus/events.py` additionally defines constants with **no payload class and no consumer** (EVALUATION_STARTED, ARCHITECTURE_EVALUATED, HUMAN_BASELINE_COMPLETE, PLAN_* are orphan constants — PLAN_* do have payloads).

### Streams (14) & Consumer Groups (10)
11 primary (`ALL_EVENT_STREAMS`): scout_output, forge_output, furnace_feed, furnace_output, furnace_crash, dissect_output, arbiter_output, harbor_output, orchestrator_output, planner_output, agent_events + auxiliary agent_thinking, thinking_delta, subaction_progress.
Groups: the 9 in bus/events.py + a 10th, `"trace_persister"` (defined in orchestrator/trace_persister.py). Group→stream wiring (runtime.py): scout_output→[orch,forge], forge_output→[orch,furnace], furnace_output→[orch,arbiter], furnace_crash→[orch,dissect], furnace_feed→[orch,frontend], dissect_output→[orch,forge], arbiter_output→[orch,harbor], harbor_output→[orch,scout], planner_output→[orch], agent_events→[orch,cockpit,trace_persister]. UI (stream renderer + Cockpit) consumes agent_events/agent_thinking/subaction_progress under `cockpit_consumers`.

### Dissect Cascade (5 repair levels + terminal/escalate sentinels)
Level −1 TERMINAL · 0 Deterministic Rules (`rules.RULES`, 18 categories wired) · 1 Compiled Templates (`repair_templates`, min_conf 0.6, ≥3 uses → Forge prevention rule) · 2 Repair Cache (`repair_cache`, md5 of `{dataset}::{type}::{msg[:200]}` — a second fingerprint scheme; replay ≥2 → generalized L1 template) · 3 Patch Memory (ChromaDB similarity ≥0.90 AND prior success) · 4 LLM Reasoning (cost-tracked; success → cache) · 5 ESCALATION. Start level = max(category level, budget bias {≤0→5, <.25→4, <.5→3}); `PREFERRED_STRATEGY_ORDER` reshuffles by crash hint. Any patch must pass `validate_patch_pre` (syntax, 1–50 added lines, critical patterns, dangerous-func AST scan) then `run_sandbox_test` (Docker `prometheus-training-base`, 60s — ⚠ timeout counts as PASS, §8).

### Cockpit
Textual TUI (`prometheus/ui/cockpit/`): MissionHeader + PhaseTracker + ActiveAgentPane + CascadeAttempt + MissionCompletionCard; live mode = read-only `CockpitConsumer` on agent_events; replay mode = `trace.jsonl` re-injection (pixel-identical). Escalation modal supports human-in-the-loop abort/skip/retry-with-hint/edit/export → publishes RESUME_TRAINING.

### CLI Command Surface (19 registered commands)
14 groups: `mission agent workspace model provider config plugin skill deploy profile evaluate memory planner daemon` + 5 leaves: `init doctor version help docs`. Aliases: ws ag cfg prov mdl plug miss eval mem plan dep prof (+skills→skill). The old orphan files (benchmark, explain, job, logs, replay, report, reproduce, solve, swarm, tool) are **deleted**. Registry is generated from the live tree — adding a click command + registering it in main.py is all that's needed; docs/commands regenerates via `prometheus docs`.

### Retry Engine (`runtime/`)
`retry_orchestrator.handle_evaluation_retry` → `RetryEngine.generate_strategy` → `retry_strategy.build_next_strategy*`. "4 strategies" = 4 monotonic escalation dimensions per attempt 1–4: architecture cycle (modality-aware), trials {20,40,60,80} (small-data floor, big-data +20), feature engineering {basic,interaction,advanced,advanced}, imbalance (ratio-driven class_weight/smote/focal). `MAX_RETRY_ATTEMPTS=4`. ⚠ Only wired via the sequential/CLI path — the event-driven orchestrator's retry transition is broken (§8).

---

## 5. CLI / TUI Specification vs. Actual Implementation

### Entry Point
`prometheus = prometheus.main:cli` (console_scripts) or `python -m prometheus`. At import: `os.chdir(project_root)` (⚠ every invocation redefines CWD), UTF-8 stdout, load_dotenv, Rich excepthook (Ctrl-C→130). Click auto-help disabled; custom eager `--help` renders animated splash. `--format interactive` iff TTY else plain. `AppContext.create()` wires lazy service props. No subcommand + TTY + configured → REPL; unconfigured → interactive wizard.

### Global Options
`-C/--project-dir`, `-w/--workspace`, `--no-color`, `--high-contrast`, `--font-size {small,medium,large}`, `--debug`, `--format {interactive,plain,json}`, hidden `--shell`, `--version`, `--help`.

### Registered Commands (verified in `main.py:_register_commands`)

| Command | Notes | Status |
|---------|-------|--------|
| **mission** | 9 subcommands. `new PROBLEM [--dataset/-d --target --budget --time-limit --watch/--no-watch --cockpit --auto --block --quiet]` (⚠ positional description, NOT `--file`). Fail-fast on missing dataset; auto-starts orchestrator daemon; `--block` runs job_runner in a worker thread w/ own event loop. status/logs/report read `outputs/*/trace.jsonl` first, Redis fallback. resume publishes RESUME_TRAINING (training phases) or reverts phases (pre-training). cancel kills container + CANCELLED + JOB_FAILED. `logs --follow` and `watch --agent` are accepted but ⚠ **no-ops**. | ✅ |
| **agent** | list/inspect/trace — static 6 roles + tools.py introspection; status hardcoded "idle". | ✅ |
| **workspace** | init/info/scan/status (project-root detection = CLAUDE.md marker or PROMETHEUS_HOME). | ✅ |
| **model** | list/show/export — scans outputs/ for eval reports. | ✅ |
| **provider** | add/list/current — `.env` management; `_SUPPORTED={anthropic,openai,local}` but OpenAI is config-only, no integration. | ✅ |
| **config** | list/set/check/edit/show — reads-before-writes `.env`, `.env.backup`, sk-ant overwrite guard. | ✅ |
| **plugin** | install/remove/list — ⚠ builtin/ dir empty; installs are import-time only, not persisted. | 🟡 |
| **skill** | install/list/info/verify/test/remove/update/create/trust/untrust/promote/check-orphans — 4-step gate (trust→structural→per-agent smoke), atomic install to `~/.prometheus/skills/`, evidence gate promotes at ≥10 consecutive OK. | ✅ |
| **deploy** | (was unregistered in 2026-08 docs) serving-container management via core/docker.py. | ✅ |
| **profile** | `~/.prometheus/profiles/*.env` + active_profile marker. | ✅ |
| **evaluate** | run/compare/report/visualize/list/failures/calibration/summary/wins/stats — aggregates benchmark JSONs. | ✅ |
| **memory** | stats/search — ⚠ **permanently blank**: MemoryService imports `get_collection_stats`/`search_memory`/`get_info` that don't exist; ImportError swallowed to `{}`. | 🔴 |
| **planner** | inspect/dry-run/validate/stats/explain/prediction-error — reads execution_plan/engineering_plan + planning hints. | ✅ |
| **init** | First-run wizard (provider, API key, workspace). | ✅ |
| **doctor** | Prereq checks (docker ping, redis ping, env placeholders, disk, deps). | ✅ |
| **version** | prints 0.1.0. | ✅ |
| **help** | categorized reference. | ✅ |
| **docs** | regenerates docs/commands from the live tree via utils/docs_gen (✓/✗ column always ✓ — vestigial). | ✅ |
| **daemon** | start/stop/status/restart/logs — PID-based; orchestrator lifecycle. | ✅ |

(Total: 14 groups (incl. daemon) + 5 leaves = **19 registered commands**, verified against `_register_commands()` add_command calls and asserted 1:1 by `tests/validators/test_registry.py` against the live tree.)

### Cockpit TUI
All screens working (dashboard, PhaseTracker, ActiveAgentPane, CascadeAttempt, DiffViewerScreen, EscalationModal, ReplayController, LogScreen w/ **search + filter implemented**, HelpScreen, Model/Agent/GoTo pickers). Keys: q/p/Ctrl-C detach (double-Ctrl-C confirm → JOB_FAILED), l log, t thinking, Ctrl-T tri-state, Tab cycle agent, Ctrl-O minimal, Ctrl-P model picker, d diff, `f` fingerprint = "coming soon" stub, ? help; replay Space/←/→/G.

### Dissect Cascade Levels — status

| Level | Module | Status |
|-------|--------|--------|
| L0 Rules | rules.py | ✅ 10 fix_* + registry wiring 18/24 categories (⚠ taxonomy claims level-0 for several without a rule; L0 just returns None) |
| L1 Templates | repair_templates.py | ✅ + safety validation (exec/eval/os/subprocess/pickle banned) |
| L2 Cache | repair_cache.py | ✅ but ⚠ separate md5 fingerprint scheme from fingerprint.py |
| L3 Memory | knowledge_store/patch_memory | 🟡 ChromaDB query wired; quality depends on embeddings; DISABLE_PATCH_MEMORY flag |
| L4 LLM | agent.py handle_crash | ✅ streaming, budget-governed, cost-recorded |

---

## 6. End-to-End Data Flow

**1. Submission** — `mission new "predict churn" --dataset data/churn.csv --target Churn`:
fail-fast dataset check → orchestrator auto-start if `orch:heartbeat` stale (daemon cmd, ≤90s wait; fallback `--block` in-process if daemon can't come up) → `orchestrator/job_queue.submit_job()`: uuid4 job_id, SET `job:{id}:meta` (QUEUED), `MissionState.create_or_load` (writes `:mission_state` + `:status`), `:crash_count=0`, best-effort `:reproducibility`, XADD MISSION_BRIEF_READY→scout_output. Then StreamRenderer (default), Cockpit (`--watch --cockpit`), or quiet/blocking modes.

**2. Scout** — `ScoutAgent.run()` reads job hash fields; `run_eda` (100-row sample) → `detect_modality`/`infer_task_type` → 10 pure `reason_*()` (leakage: id/time/|corr|>0.95; imbalance: ≤3 none, >5 class_weight, >20 smote, >3 focal; architecture: tabular<1M→lightgbm else tabnet, text→distilbert, image→efficientnet; validation strategy by size; experience-adjusted confidence ±0.05/−0.10, cap [0.40,0.98]). Writes `job:{id}:mission_brief` + `:mission_spec` (v2.0) (+ disk mirror), publishes MISSION_BRIEF_READY. Deterministic expected-metric rule: classification `max(0.55, 0.80 − 0.03·min(ratio,10))`, regression `std·0.85` — **identical formula lives in Arbiter too; keep them in sync**.

**3. Forge** — arch choice: retry_context > Scout decision > `decision_tree.select_architecture(use_memory=True)` (Chroma can override). `define_optuna_space` (lgbm 7 dims/xgb 6/tabnet 7/distilbert 5/efficientnet 5). `create_plan` → `job:{id}:engineering_plan`. `confidence_router`: conf ≥0.85→template, ≥0.55→cache, else "llm" — **which is actually a deterministic f-string generator; no LLM call**. `static_prevention` transforms + Redis `forge:prevention_rules`. SHA-256 fingerprint recorded (`forge:script_fp:{fp}`; ⚠ lookup scans the wrong pattern `fingerprint:*:meta` — §8). Script → `scripts/training_script_{job_id}.py`; search space → `job:{id}:search_space`; publishes TRAINING_SCRIPT_READY.

**4. Furnace** — `run(script_path, use_docker=True, wait_for_dissect=True, ...)`: launches `prometheus-train-{job_id}` container (mounts scripts-ro/data-ro/outputs-rw, env JOB_ID/DATA_DIR/OUTPUT_DIR/RESUME_CHECKPOINT/SEARCH_SPACE_JSON), streams logs, parses JSON progress lines (`EPOCH_COMPLETE`→furnace_feed). Crash: save `crash_ckpt_attempt_{n}`, SET `:last_crash`, publish CRASH_EVENT→furnace_crash, then **XREAD dissect_output `$` block=600_000** (10 min); RESUME_TRAINING→loop with patched script+checkpoint; ESCALATE/timeout/>3 attempts→give up. Success: `TrainingCompleteEvent`→furnace_output (⚠ metric_name hardcoded "auc_roc" even for regression).

**5. Dissect** — `handle_crash(crash_event)`: taxonomy classify (regex → LLM single-word fallback novel_error) → gates (terminal category, duplicate sha256 fingerprint, `has_progress`, per-fingerprint budget) → 5-level cascade (§4) → `validate_patch_pre` → Docker sandbox test → publish RESUME_TRAINING(+patched script, checkpoint, patch_id) or ESCALATE. Every attempt RPUSHes `patch_log_queue` (drained to `research/patch_log.jsonl` by `patch_log_writer.run_writer()` — agents must NEVER write that file directly). Successful L4 patches feed repair_cache; L2 replay ≥2 promotes to L1 template; L1 use ≥3 / L2 replay ≥3 push prevention rules back into Forge.

**6. Arbiter** — `on_training_complete(event)`: brief→constraints (deployment_threshold/operator `>`), loads `checkpoints/y_test.npy`+`y_pred.npy` (+y_prob; guard: refuses to evaluate if only y_train present), computes metrics + dataset-relative threshold, `make_decision`: no threshold→PASS; passes→PASS; |gap|/|thr| ≤ **15%**→RETRY; else FAIL→ESCALATE. Saves evaluation.json/metrics.csv/decision.json/plots + ExperienceRecord (Chroma) + `swarm_arbiter_decisions_total`. ⚠ crash_count is read but NOT used in the decision (the "≥3 crashes→ESCALATE" rule exists only in the legacy unused `tools.make_decision`/`controller.run_evaluation`).

**7. Harbor** — `on_evaluation_pass(event)`: serialize model **ONNX → TorchScript .pt → torch.save .pth → pickle** fallback chain + write `PreprocessingContract` JSON (hash-verified); generate contract-driven FastAPI app (`/predict /health /verify /metrics`); `verify_deployment()` pre-deploy gate (contract load/hash/validity, ONNX input-names/feature-count, app no-hardcoding) — **failure is fatal (JOB_FAILED)**; self-test posts a synthetic row to the live endpoint. Deploy: build image (python:3.11-slim, conditional libgomp1) → local `docker run -d -p {8080+}:8080 --restart unless-stopped` (port probes + in-process lock ⚠ never released) or GKE (`REGISTRY_URL` push + helm chart). Then `start_drift_monitor_loop` (PSI, 3600s interval, 1000 window, 0.2 threshold) and ENDPOINT_LIVE (⚠ p95 hardcoded 0.0).

**8. Drift Monitoring** — per-feature 10-bin histogram baselines from the training CSV; DRIFT_ALERT→runtime→SCOUT_RETRAIN→inline Scout. ⚠ **the loop compares baselines against `np.random.normal(mean, std)` simulated samples** — no real inference traffic ever reaches it; see §8.

### The Two Orchestrator Drivers
1. **`orchestrator/runtime.py` (1199)** — event-driven `OrchestratorRuntime.run()`: 7 `_consume_*` coroutines (XREADGROUP orchestrator group, block=2000, ACK after handler) + `_heartbeat_loop` (`orch:heartbeat` SET every 5s) + metrics server :9090 + tool_memory registration + HealthMonitor. Agents run **inline** (so `_consume_forge` blocks for Forge's whole duration; Furnace↔Dissect concurrency works because Dissect runs inside `_consume_furnace_crash`). Full state transitions, plan dispatch, escalation→diagnostic JSON + mission report + container kill + JOB_FAILED.
2. **`orchestrator/job_runner.py` (417)** — `run_job(JobConfig)`: inline Scout→Forge→Furnace with a concurrent `dissect_listener` (GROUP_DISSECT on furnace_crash) + patch_log_writer; outcomes read by `xrevrange(…, count=50)` scans; returns `JobResult`. Used by `mission new --block`, research runners. ⚠ Does **not** transition phases during the run and treats EVALUATION_RETRY as escalate (§8 bugs 1–3).

---

## 7. Current Implementation Status

| Component | Status | Evidence |
|-----------|--------|----------|
| 6 Agent cores | ✅ Working | ~17k lines; Redis I/O, events, metrics all real |
| Contracts (domain/events/state) | ✅ Working | 19 payloads, 21-phase matrix, legacy normalization |
| Event bus | ✅ Working | XADD/XREADGROUP, agent-event trackers; ⚠ no MAXLEN/reclaim |
| Orchestrators | 🟡 Working w/ defects | runtime.py is the live path; retry + PEL reclaim broken (§8) |
| CLI (19 commands) | ✅ Working | generated registry, aliases, fuzzy, REPL wizard |
| StreamRenderer + Cockpit TUI | ✅ Working | search/filter fixed; legacy ui.py panels mostly orphaned |
| LLM provider (Anthropic) | ✅ Working | used only by Dissect L4 (+taxonomy fallback) |
| Skill platform + 6 Dissect skills | ✅ Working | signed install, sandboxed subprocess, evidence-gated promotion |
| Forge templates + generators | ✅ Working | ⚠ cache-reuse path broken (§8); "llm" strategy is deterministic |
| Dissect cascade L0–L4 + budgets | ✅ Working | ⚠ sandbox timeout=PASS (§8) |
| Retry engine | 🟡 Partial | 4 escalation dimensions real; orchestrator wiring broken; dead params |
| Metrics (shared/metrics.py) | ✅ Working | ~50 swarm_* metrics; serving/metrics.py DEAD |
| Memory (Redis + Chroma) | 🟡 Partial | 4 collections wired; ⚠ ALLOW_RESET exposed; embedding normalization inconsistent |
| Training containers | ✅ Working | ⚠ no GPU despite TabNet/distilbert/efficientnet ambitions |
| Harbor serving | ✅ Working | ONNX→TorchScript→pickle chain, 6-phase gate |
| Drift monitor | 🔴 Fabricated | compares against simulated normals (§8) |
| Research framework | ✅ Working | ⚠ integrity items in §8 |
| Tests | ✅ 97 files | ⚠ titanic fixture deleted → 3 tests broken/skipped (§8) |
| Frontend | 🟡 Demo | 18 routes, direct-Redis API, mock mission UI |
| Kubernetes/Helm | 🟡 Present | chart 0.1.0 real; :latest images; localhost-scoped monitoring |
| OpenAI provider | ⚪ None | config mentions only |
| Built-in plugins | 🔴 Empty | plugin system import-time only |

---

## 8. Known Issues (verified 2026-09-15; Week-1/2 fixes applied same day)

### ✅ Fixed (Week 1+2, 2026-09-15) — regression-tested
1. ~~Orchestrated retry dead~~ — FIXED: retry walks the legal matrix path ARBITER_COMPLETED→RETRY_PENDING→RETRY_RUNNING→FORGE_RUNNING; Forge is launched inline with a real `RetryPlan` (escalated architecture/trials/features/imbalance via `build_next_strategy_from_state`); retry budget (`max_retries`, "budget exhausted" → escalation) bounds the loop.
2. ~~PEL pile-up~~ — FIXED: all 7 runtime consumers route through `_safe_handle` (handler exception → dead-letter escalation → ACK anyway); `_reclaim_stale_pending()` XAUTOCLAIMs PEL entries idle >5 min at startup and dead-letters them.
3. ~~Dissect sandbox: timeout=PASS~~ — FIXED: timeout now PASSes only with observable training progress (JSON progress lines / `[N]` eval lines / TRAINING_COMPLETE); a silent-hang timeout FAILS and the patch is rejected. `run_sandbox_test(…, timeout_s=)` parameterized. (Note: generated scripts don't yet read a sandbox epoch cap from env — enforcing `max_epochs` in the sandbox remains open.)
4. ~~ALLOW_RESET~~ — FIXED: compose ships `ALLOW_RESET=false`; `ChromaClient.reset_collection()` refuses unless `ALLOW_RESET=true` is set in the environment (code guard now exists).
5. ~~job_runner state never persisted~~ — FIXED: explicit status→phase map writes the terminal phase (pass→MISSION_PASSED; crash/timeout/error→MISSION_FAILED) + timeline entry. Also fixed: `api_cost_usd` always 0.0 (was reading the RPUSH list key as a hash; now reads `api_cost_summary` with an LRANGE fallback).
6. ~~CI theater~~ — FIXED: ci.yml runs unit+validators+services as a failing gate (real requirements install, no `|| echo`); quality.yml moved to `main`, installs real deps (no nonexistent `[dev]` extra), ruff/format gates scoped (repo-wide format debt documented); the claude-code-proxy dir is excluded from lint.
7. ~~Missing fixture~~ — FIXED: `tests/fixtures/titanic.csv` restored; test_titanic_e2e 5/5 (stale test updated to pass the now-required `architecture` arg); test_scenarios_e2e no longer skips for the fixture.
8. ~~Pre-existing test-vs-code drift (7 unit failures)~~ — FIXED: `runtime/retry_state.py` save/load round-trips RetryState to its own file (was writing mission_state.json and returning MissionState without `attempt_number`); mission_report `_render_markdown` no longer crashes on alternatives lacking `expected_metric_range`. **Full suite GREEN: 1351 passed / 0 failed** (2 files locally deselected for the known Windows asyncio hang — test_shell_interactive, test_init_wizard_interactive).
9. ~~Statistics scale bug + deprecated input~~ — FIXED: `research/statistical_analysis.py` rewritten — per-task-family Mann-Whitney (AUC and RMSE never pooled), crash/timeout placeholders excluded from metric tests, paired McNemar kept (scale-free), refuses `deprecated`-flagged files, `--baseline/--output` args, optional Condition-A block.
10. ~~Test pollutes research data~~ — FIXED: `test_furnace_dissect_loop` no longer appends to `research/patch_log.jsonl`; synthetic `{"test":"direct"}` injections removed.
11. ~~Condition A mislabeled~~ — FIXED: genuine human-written baseline at `research/baselines/human_baseline.py` (hand-coded cleaning/LightGBM choices, no Optuna, no swarm memory, same npy evaluation contract), wired into `run_condition_a` for tabular problems (text/image report the scope limit).
12. ~~Ablation integrity~~ — FIXED: library-level (non-orchestrated) nature documented in module + run_single_problem docstrings; `DISABLE_DISSECT` now honored for the dissect axis; dead always-−1 `cascade_level_used` field removed; rows carry `evaluation_metric`.
13. ~~Campaign cost estimate~~ — PARTIAL: benchmark rows carry metered `api_cost_usd` now; `run_campaign.compute_run_metrics` records `metered_cost_usd` + `cost_source` (fixed 3000/800 estimate remains labeled fallback for analyze-mode over historical logs).
14. ~~Benchmark membership bug + rerun fixes~~ — FIXED during the rerun: `if "B" in args.condition` never matched "both", silently dropping unavailable/crash rows from batch files (→ `_effective_conditions()`); Forge target-column validation now delimiter-sniffs (semicolon CSVs like TC06 falsely failed); `--output` baselines embed `problems` + `condition_a`. **Rerun outcome (2026-09-15, `research/benchmark/results/baseline_v2_rerun_2026-09-15.json` + `statistical_analysis_v2_rerun.json`)**: 9/10 problems executed both conditions (TC12 needs manual Kaggle download). Honest headline: **B and C pass identically (6/9) — the current benchmark does NOT stress Dissect**: the tabular scripts don't crash (nothing to repair) and text/image failures are CPU-resource timeouts/crashes that patching cannot fix (IC03-C burned 2 patch attempts, still escalated). The old v1 22pp "improvement" came from the flawed subprocess-mode runs; the genuine Dissect evidence is the campaign patch logs (111 attempts) + the injected-error integration tests. **Week-3 action: make a crash-inducing benchmark variant (wire `evaluation/stress_injector.py`) so B-vs-C becomes meaningful again.**

### 🔴 Still open — P0
15. **Harbor drift loop simulates its own traffic** (`np.random.normal(mean, std)` fallback in `run_drift_check`) → perpetual false DRIFT_ALERTs on non-normal features; the generated serving app never feeds real /predict samples into Redis. (Week-3 target.)
16. **Furnace hard-timeout gap**: benchmark text jobs showed ~1300–2400s durations despite `wait_for(timeout=600)` — the Docker training container keeps running after the asyncio cancellation (orphan `prometheus-train-*` containers confirmed); the cancellation path must kill the container.

### 🟠 P1 — correctness
17. **Duplicate MissionState HAS DRIFTED** (`runtime/models.py` vs `contracts/state.py`): 17 vs 21 phases (missing HARBOR_DEPLOYING/HARBOR_COMPLETED/SCOUT_RETRAIN/CANCELLED), different transition matrix (`ARBITER_RUNNING→[ARBITER_COMPLETED]` only, `MISSION_PASSED→[]`), `is_terminal` includes MISSION_PASSED in models vs {MISSION_FAILED, CANCELLED} in contracts, schema_version "1.0" vs "1", no `:status` dual-write. retry_orchestrator mixes both classes. Kill the models.py copy or re-export from contracts.
18. **Forge cross-job cache dead**: stored `forge:script_fp:*` vs lookup `fingerprint:*:meta` (tools.py ~1259) — patterns never match.
19. **Arbiter ignores crash_count** in the live decision path (documented rule only exists in dead legacy code); duplicate decision logic across decision.py/tools.py/controller.py — consolidate on decision.py.
20. **Furnace metric mislabel**: `_guess_metric_name()` hardcoded "auc_roc" for regression runs (confirmed in rerun logs: TR01/TR05 report `metric=auc_roc` with RMSE values); two log parsers coexist (agent.py vs tools.monitor_loss).
21. **Harbor details**: missing-checkpoint branch returns without JobFailedEvent; `.pkl`/`.joblib` fallback double-replace unreachable; `_PORT_LOCK` never released; p95=0.0.
22. **Silent-failure surfaces**: `memory stats` permanently blank (broken imports swallowed); `job_service.cancel()` always False (`CliRedis.update_job_status` doesn't exist); `live_progress.watch_job` KeyError (`status` vs `phase`); `core/pipeline.py` deprecated but still the JobService.submit path — trains with `use_docker=False` (no isolation, no Dissect).
23. **execution_outcome/planner_feedback meta drop**: peak RAM/GPU/deployment_success built but never passed to `store_experience` → RAM/VRAM planning hints permanently empty.
24. **experience_memory read-after-write mismatch**: `query_similar_experiences` parses metadata keys `_build_metadata` never writes (pipeline_steps/feature_engineering empty on read); embeddings stored unnormalized while similarity assumes cosine.
25. **Two parallel thinking streams** (agent_thinking/THINKING_TOKEN from llm_client vs thinking_delta/THINKING_DELTA from bus) + per-token XADD with no batching (unbounded stream churn); `publish()` has no MAXLEN; seq keys (`agent_event_seq`, `thinking_seq`, `execution_outcome`) have no TTL.
26. **No GPU in training containers** (docker_manager passes no device_requests) despite TabNet/distilbert/efficientnet architectures and ComputationalBudget.gpu_required; CPU-only text/image training hit the timeout on real datasets in the 2026-09-15 rerun (TX01, TX04) — a benchmark-scope limitation to state honestly, not a bug in the Dissect claim.

### 🟡 P2 — hygiene
27. PLAN.md is 3150+ lines of build log; README stale counts/phase claims; ~330 orphan `training_script_*.py` in scripts/ + strays at root (`model.pt`); duplicate `scripts/{statistical_analysis,compare_baselines}.py` vs research/ versions; `prometheus/cli/output.py` twin of utils/output.py (mission uses utils); `cli/mission/session.py` (MissionSession) + `ui_harbor.py` + `_launch_claude_transcript` + several `_legacy_*` renderers DEAD; `training/{checkpoint_manager,label_normalizer}.py`, `serving/{metrics,onnx_runtime}.py`, `check_drift`, serving/docker/Dockerfile, `prometheus/schemas/*`, `orchestrator/health_monitor.py` (superseded by runtime's own reclaim), `evaluation` STRESS_MODE+stress_injector harness, `planner_feedback.compute/store_prediction_error`, `bus.consume_one/loop` — dead; taxonomy docstring says "21" categories (actual 24); problems.json trimmed 50→10 but baselines/scripts still cite the 40 stale ids (TC12 dataset needs manual Kaggle download); compat.py checks Python≥3.10 (docs say 3.11+); bandit scope omits most packages; repo-wide `ruff format` debt (~85 files, gated per-directory now).
28. Compose binds whole repo (incl. `.env`) + `/var/run/docker.sock` into the orchestrator container (root-equivalent host escape); `restart: unless-stopped` without resource limits; `main.py` global `os.chdir` makes relative paths repo-root-dependent; k8s uses mutable `:latest`; prometheus.yml scrapes localhost targets only.

---

## 9. Pending Design Decisions

| Question | Options | Current Leaning |
|----------|---------|-----------------|
| Default orchestrator | runtime.py (event-driven) vs job_runner.py (sequential) | runtime.py for serving/CLI; job_runner for benchmark — **must converge retry semantics first** |
| MissionState location | contracts/ vs runtime/ | contracts/ canonical; runtime/ copy to be deleted (drifted — §8.9) |
| Retry loop shape | RETRY_PENDING path in runtime vs delegating to retry_orchestrator | Pick one; today four divergent semantics exist |
| Training isolation | Docker vs subprocess | Docker (but CLI path violates it via deprecated pipeline — §8.17; GPU support needed for text/image claims) |
| Dissect evaluation integrity | metered LLM cost vs estimated; independent runs vs shared memory | Metered + per-run memory snapshots before camera-ready |
| OpenAI provider / frontend / K8s | implement vs defer | Deferred (research CLI-first) |

---

## 10. Design History & Rationale

- **Redis Streams over Kafka**; **ChromaDB over Pinecone**; **Jinja2 templates over programmatic generation** (debuggability when LLM scripts were unreliable); **Textual over web dashboard** (information density); **click over argparse**; **Docker Compose over K8s** (single-node research); **pydantic-settings over dotenv** (typed loads).
- **Determinism-first agents**: five of six agents are pure deterministic pipelines; the LLM is reserved for Dissect L4 — cheap, budget-governed, cacheable, and the sole research variable. This is deliberate (reproducibility for the paper), not unfinished work.
- **Skill platform** (`agents/skills/`): deterministic helpers with hard contracts — installed skills are signed, gated per-agent by smoke tests on captured contexts, sandboxed in subprocesses with runtime/memory caps, and promoted (bundled→trusted-instruction injection) only via the evidence gate. Skills wrap the cascade (pre-taxonomy localization, signature extraction, assertion generation, rule generalization) rather than adding a 6th repair level.

### Past incidents (remember these)
1. **Credential overwrite** — config set wiped .env; fix: read-before-write + `.env.backup` + sk-ant guard. (Keep this pattern in ANY new writer.)
2. **Fabricated spec citations** — an agent claimed features were in the design book that weren't. Ground rule: **verify claims against code, not docs** (this file included — see §8).
3. **Silent ChromaDB data loss** — collection reset lost patch memory; the `ALLOW_RESET` guard existed only as a claim — compose shipped `ALLOW_RESET=true` and no code guard existed at all. Fixed 2026-09-15: compose ships `false`, and `ChromaClient.reset_collection()` raises unless `ALLOW_RESET=true` is set in the environment (§8.4).
4. **Dissect infinite loop** — fingerprint ignored exception message; fixed (msg[:200] in hash).
5. (New 2026-09) **Doc-vs-code drift audit** — this entire §8 exists because the 2026-08 CLAUDE.md asserted statuses ("✅ Fixed") that source contradicted (ALLOW_RESET guard, label_normalizer wiring, registered command list).

---

## 11. Testing & Verification State

- **pytest**, asyncio_mode=auto, testpaths=tests, pythonpath=[.], markers: unit, integration, slow, e2e, validation, training_exec.
- **97 test files: 79 unit (flat) + 12 integration + 5 services + 1 validators**; `tests/cli/conftest.py` (mocks), `tests/research/patch_log.jsonl` (data).
- Unit suite is hermetic and strong: state machine (42 exhaustive matrix), dissect (taxonomy/rules/templates/reliability w/ fingerprint+budget+terminality contracts), forge (decision tree/planner/templates/confidence/**13 fuzz CSVs**), retry (40, incl. contract guards rejecting dicts), **skill platform (32: kill-on-timeout, atomic reinstall, run()-never-raises, signature tamper)**, cockpit (golden byte-for-byte replay), validation mirrors, registry 1:1 tree walk.
- Integration truth table: require live Redis (aioredis localhost:6379), often Docker image `prometheus-training-base`, and real `sk-ant-` keys — **real LLM calls** in test_furnace_dissect_loop / test_job_runner (has an anti-bypass `duration>5s` assertion) / test_orchestrator_titanic_real / test_trace_persister; hermetic ones: test_harbor_serving (Starlette TestClient on tiny LGBM), test_bus_e2e (Redis only), test_orchestrator_escalate (fully mocked).
- **Known suite breakage (§8.8)**: missing `tests/fixtures/titanic.csv` errors test_titanic_e2e and always-skips test_scenarios_e2e; test_furnace_dissect_loop writes research patch-log entries (deselect when producing paper data). **Actual full pass-rate not yet re-run under this audit.**

## 12. Coding Conventions & Patterns

Python 3.11+, type-hinted signatures, Google docstrings, snake_case/PascalCase/UPPER_SNAKE. click + Rich + Textual + Pydantic v2. Async-first; CLI wraps async via asyncio.run (and the blocking mission path via worker-thread event loop). ruff + black, line-length 100. Windows-only quirks: venv redirector PIDs, WindowsSelectorEventLoopPolicy subprocess limits (see memory notes).

**Error handling**: try/except with `[Agent][job=…]` context on every Redis/Docker/LLM call; critical re-raise, non-critical fallbacks. ⚠ Pervasive `except Exception: return {}/[]/False` has hidden four live bugs (§8.17) — prefer logging at ERROR + metric when swallowing.

**How to add an agent**: agents/<name>/{agent,tools,prompts,models}.py; subclass BaseAgent (agent_name/system_prompt/run); add stream+group+event constants to bus/events.py AND payload to contracts/events.py; add phase edges to `contracts/state.py:MISSION_PHASE_TRANSITIONS` (runtime/models.py should be deleted rather than synced); consume in orchestrator/runtime.py `_consume_*`; register in prometheus/cli/agent.py AGENT_NAMES; emit metrics from `shared/metrics.py` (NOT serving/metrics.py); tests flat in tests/unit/.

**How to add a CLI command**: implement with @click.group/command; `cli.add_command(...)` in `prometheus/main.py:_register_commands`. That's it — the registry, docs, REPL nouns, and validators/test_registry.py all follow from the live tree. (The old "edit the 1089-line _build()" and "no redirect stubs" instructions are obsolete.)

**How to add a skill**: directory with SKILL.md (YAML manifest: name, version, category, agents:[...], type: code|instruction, deterministic, max_runtime_s, permissions) + `skill.py` subclass of agents.skills.base.Skill returning SkillResult; install via `prometheus skill install` (trust→structural→smoke gate) or drop in `agents/*/skills/` for bundled; never raise from run().

**Test conventions**: unit tests flat (`tests/unit/test_<module>.py`), integration in tests/integration/ with infra skip-guards, fixtures in tests/fixtures/, `pytest.mark.asyncio`/auto-mode.

## 13. Running, Building & Testing

Prereqs: Python 3.11+, Docker, Redis 7+, ChromaDB, ANTHROPIC_API_KEY.

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # authoritative over pyproject (§8 deps gap)
copy .env.example .env                    # set ANTHROPIC_API_KEY
docker compose up -d redis chromadb      # ⚠ consider setting ALLOW_RESET=false until code guard lands
# one-off: build training image
powershell scripts\build-training-image.ps1
```

```powershell
python -m prometheus mission new "predict customer churn" -d data/churn.csv --target Churn   # auto-starts orchestrator
python -m prometheus mission new "..." -d data/x.csv --block                                  # in-process sequential run
python -m prometheus mission watch <slug|job_id>          # stream renderer (default live UI)
python -m prometheus mission watch <id> --cockpit         # Textual TUI (or: python -m prometheus.ui.cockpit.app)
python -m prometheus daemon start|status|stop|logs        # manual orchestrator control
python -m prometheus doctor                               # prereq checks
python -m prometheus                                      # REPL (wizard if unconfigured)
```

```bash
pytest tests/unit -q                       # 79 hermetic files — the fast gate
pytest tests/unit -m "not slow" -v
pytest tests/integration/test_harbor_serving.py -v        # hermetic integration
pytest tests/integration/test_titanic_e2e.py -v -s        # needs fixture restore (§8.8), Redis+Docker+key
ruff check . && ruff format --check . && pre-commit run --all-files
```

Research: `python -m research.run_benchmark --condition all --count 10` · `run_ablation.py` · `run_campaign.py --runs 10 --condition C` · `validate/` framework → experiments/*.json; frontend: `cd frontend && npm run dev` (:3000, direct Redis).

### Environment (.env)
`ANTHROPIC_API_KEY` (required) · `ANTHROPIC_MODEL` (claude-sonnet-4-6) · `REDIS_HOST/PORT/PASSWORD` · `CHROMA_HOST/PORT` · `TRAINING_IMAGE_NAME` (prometheus-training-base) · `SCRIPTS_DIR/OUTPUTS_DIR/DATA_DIR` · `PATCH_LOG_PATH` (./research/patch_log.jsonl) · `SERVING_PORT` (8080) · `LOG_LEVEL` · `PROMETHEUS_PORT` (9090 metrics) · `LLM_TIMEOUT` · feature flags `DISABLE_PLANNER` / `DISABLE_PATCH_MEMORY` / `DISABLE_DISSECT` / `PROFILE_MODE` (+ orphaned `STRESS_MODE`) · `HARBOR_TARGET` (local|gke), `REGISTRY_URL` · `EMBEDDING_MODEL` · `PSI_THRESHOLD` / `PSI_WINDOW_SIZE` / `PSI_CHECK_INTERVAL_SECONDS` · `FURNACE_AUTO_EARLY_STOP` · `DISSECT_MAX_LLM_CALLS/COST_USD/…` · `ALLOW_RESET` (server-side only — the missing code guard, §8.5) · `PROMETHEUS_DEBUG`, `PROMETHEUS_HOME`.

## 14. Key File Reference

| Purpose | Files |
|---------|-------|
| Entry/CLI | `prometheus/__main__.py` · `prometheus/main.py` · `prometheus/repl.py` |
| Mission UX | `prometheus/cli/mission/__init__.py` · `prometheus/ui/stream/renderer.py` · `prometheus/ui/cockpit/{app,widgets,consumer,trace_replay}.py` |
| Command surface | `prometheus/registry/generate.py` (build_from_cli) · `prometheus/utils/docs_gen.py` · `validators/test_registry.py` |
| Agent core | `agents/base.py` · `agents/llm_client.py` · `agents/{scout,forge,furnace,dissect,arbiter,harbor}/agent.py` |
| Dissect | `routing.py` (cascade) · `taxonomy.py` (24) · `rules.py` (18) · `repair_templates.py` · `repair_cache.py` · `fingerprint.py` · `governor.py`/`budget.py` · `validation.py` · `knowledge_store.py` · `patch_log.py` · `agents/dissect/skills/*` |
| Skill platform | `agents/skills/{base,context,manifest,loader,registry,installer,signing,subprocess_runner}.py` · `prometheus/cli/skill.py` |
| Contracts/bus | `contracts/{state,domain,events}.py` · `bus/{events,publisher,consumer,agent_events}.py` |
| Orchestration | `orchestrator/{runtime,job_runner,job_queue,mission_report,patch_log_writer,trace_persister,reproducibility}.py` |
| Retry | `runtime/{retry_orchestrator,retry_engine,retry_strategy,retry_state,capability_registry,models,paths}.py` |
| Memory | `memory/{redis_client,chroma_client,schemas,embeddings}.py` · `memory/collections/*` |
| Training/serving infra | `training/docker_manager.py` · `training/base_training_image/Dockerfile` · `agents/harbor/{tools,serving_template,artifact_validator}.py` · `serving/drift_monitor.py` |
| Observability | `shared/metrics.py` (live) · `shared/health_monitor.py` · `infra/monitoring/*` |
| Research | `research/{run_benchmark,run_campaign,run_ablation,statistical_analysis}.py` · `research/validation/*` · `research/benchmark/{problems.json,baseline_v2.json}` · `RESULTS_SCHEMA.md` |
| Learning loop | `learning/{execution_outcome,planner_feedback}.py` · `agents/forge/quality_feedback.py` |

## 15. Resolved Questions / Remaining Unknowns

Items previously listed as "unverified" are now resolved by this audit: test pass-rate is NOT yet re-executed (run `pytest tests/unit` to establish the green baseline); runtime/models drift diffed field-by-field (§8.9); ChromaDB end-to-end semantic search exercised by tests (hermetic + key-gated integration); `src/` is gone (no longer at top level); `prometheus/providers/` never existed (provider logic = `prometheus/services/provider_service.py`); helm/k8s contents now verified (chart 0.1.0, `:latest` caveats); Furnace default is Docker (`use_docker=True`) except the deprecated CLI pipeline path which forces `use_docker=False`; benchmark B/C genuinely use real LLM + Docker (no mock mode); problems.json's 10 problems confirmed and old-50 references catalogued (§8.22); frontend build status still unexercised (demo-grade, 8 mock pages).
