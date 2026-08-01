# Prometheus Swarm

> *"You describe the task. The swarm does the rest."*

**Prometheus Swarm** is an autonomous multi-agent system that accepts a raw natural-language description of a machine-learning problem and returns — without any human intervention — a fully trained, evaluated, and live-served model endpoint.

Six specialized AI agents coordinate through a Redis Streams message bus. No agent calls another directly. Each has its own system prompt, tools, and memory scope.

---

## Architecture

```
Job Submitted → [Scout] → [Forge] → [Furnace ⟷ Dissect] → [Arbiter] → [Harbor] → Live Endpoint
```

| Agent | Role | Input → Output |
|-------|------|---------------|
| **Scout** | Perceiver | Raw problem description → `mission_brief.json` |
| **Forge** | Architect | Mission brief → training script + hyperparameter space |
| **Furnace** | Trainer | Script → trained model checkpoint + live metrics |
| **Dissect** | Debugger | Crash trace → patched script + `RESUME_TRAINING` |
| **Arbiter** | Critic | Checkpoint → evaluation report + PASS/RETRY/ESCALATE |
| **Harbor** | Deployer | Model → HTTPS endpoint + drift monitor |

---

## Quick Start

### Prerequisites
- Python 3.11+
- Docker Desktop
- Redis (via Docker Compose)
- Anthropic API key

### Setup

```bash
# Clone the repo
git clone https://github.com/MosadCreates/prometheus-swarm.git
cd prometheus-swarm

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # Linux/macOS

# Install dependencies
uv pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY=your-key-here

# Start infrastructure
docker compose up -d
```

### Run the Titanic Pipeline

```bash
python scripts/run_titanic_e2e.py
```

This runs the full pipeline end-to-end on the Titanic dataset:
1. **Scout** detects tabular classification, writes mission brief
2. **Forge** selects LightGBM, generates training script
3. **Furnace** trains the model (Accuracy ~0.81)
4. **Arbiter** evaluates (AUC ~0.98, decision: PASS)
5. **Harbor** deploys to a Docker container at `http://localhost:8081`

### Test the Live Endpoint

```powershell
$body = '{"instances":[{"PassengerId":892,"Pclass":3,"Sex":"male","Age":34.5,"SibSp":0,"Parch":0,"Fare":7.83,"Embarked":"Q"}]}'
Invoke-RestMethod -Uri "http://localhost:8081/predict" -Method Post -Body $body -ContentType "application/json"
```

---

## Project Structure

```
prometheus-swarm/
├── agents/          # Six AI agents (scout, forge, furnace, dissect, arbiter, harbor)
├── bus/             # Redis Streams message bus (publisher, consumer, events)
├── contracts/       # Pydantic event payloads + mission state machine
├── orchestrator/    # Event-driven + sequential job orchestration
├── runtime/         # Retry engine, retry strategies, state tracking
├── memory/          # Redis (short-term) + ChromaDB (long-term vector memory)
├── prometheus/      # CLI application (click groups + Rich UI + Cockpit TUI)
├── training/        # Docker container management, checkpoint manager
├── serving/         # ONNX runtime, drift monitor, Dockerfile
├── evaluation/      # Benchmark validation, stress injection, reproducibility
├── scripts/         # Operational scripts + generated training scripts
├── tests/           # 82 unit/integration/service test files
├── frontend/        # Next.js live agent feed UI
├── research/        # Paper, benchmarks (10 problems), patch_log dataset
└── infra/           # Kubernetes, Prometheus, Grafana configs
```

---

## Tests

The suite has **82 test files** (verified 2026-08-01): 64 unit tests (fast, no external deps), 12 integration tests (require Redis, some also Docker), 5 service tests, and 1 registry validator test.

```bash
# All tests
pytest tests/ -v

# Fast tests only (no Docker/Redis)
pytest tests/ -m "not slow" -v

# Integration tests (requires running Docker + Redis)
pytest tests/integration/test_titanic_e2e.py -v -s
```

| Test Suite | File | Notes |
|-----------|------|-------|
| Titanic E2E | `tests/integration/test_titanic_e2e.py` | Requires Redis/Docker |
| 3 Kaggle E2E | `tests/integration/test_three_kaggle_e2e.py` | Requires Redis/Docker |
| Scout Tools | `tests/unit/test_scout_tools.py` | Fast |
| Forge Decision Tree | `tests/unit/test_forge_decision_tree.py` | Fast |
| Dissect Taxonomy | `tests/unit/test_dissect_taxonomy.py` | Fast |
| Arbiter Metrics | `tests/unit/test_arbiter_metrics.py` | Fast |
| Bus Events | `tests/unit/test_bus_events.py` | Fast |
| Furnace–Dissect Loop | `tests/integration/test_furnace_dissect_loop.py` | Requires Redis/Docker |
| Harbor Serving | `tests/integration/test_harbor_serving.py` | Requires Redis/Docker |

---

## Phase Status

| Phase | Goal | Status |
|-------|------|--------|
| **0** | Foundation (Redis, Docker, Claude API, ChromaDB) | ✅ Complete |
| **1** | Scout + Forge + Furnace (Titanic E2E) | ✅ Complete |
| **2** | Dissect + Arbiter + Harbor (3 Kaggle datasets) | ✅ Complete |
| **3** | ChromaDB memory + Orchestrator hardening | ✅ Complete |
| **3.5** | CLI (13+ command groups), Cockpit TUI, streaming renderer | ✅ Complete |
| **4** | Research experiments + Paper (benchmark runner, 10 problems, 15 campaigns) | 🔄 In progress |

**Current state (2026-08-01):** the six-agent pipeline, CLI (15 registered commands), Cockpit TUI, and research framework (benchmark/ablation/statistics) are all functional. The CLI now runs on an event-driven orchestrator (`orchestrator/runtime.py`) with a sequential in-process driver (`orchestrator/job_runner.py`) as the alternative. Active work focuses on research publication at MSR 2026 / ASE 2026.

---

## Research

Prometheus Swarm targets publication at **MSR 2026** or **ASE 2026**.

The core contribution is the **Dissect** agent: autonomous self-patching of ML training failures without human input. The `research/patch_log.jsonl` dataset records every patch attempt (success or failure) and serves as the experimental dataset for the paper.

---

## License

MIT — see LICENSE file.
