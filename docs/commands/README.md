# Prometheus Swarm — Command Reference

| Command | Category | Description | Implemented |
|---------|----------|-------------|-------------|
| `agent inspect` | Agents | Inspect a specific agent in detail | ✓ |
| `agent list` | Agents | List all registered agents with their status | ✓ |
| `agent logs` | Agents | Show agent execution logs | ✓ |
| `agent metrics` | Agents | Show agent performance metrics | ✓ |
| `agent trace` | Agents | Show event trace for a specific agent across missions | ✓ |
| `config check` | Config | Validate all prerequisites | ✓ |
| `config edit` | Config | Open .env in the default editor | ✓ |
| `config get` | Config | Get a single configuration value by key | ✓ |
| `config list` | Config | Show current .env configuration | ✓ |
| `config set` | Config | Set a KEY VALUE pair in .env | ✓ |
| `deploy list` | Deploy | List all deployed serving containers | ✓ |
| `deploy logs` | Deploy | Show logs for a deployed serving container | ✓ |
| `deploy stop` | Deploy | Stop and remove a deployed serving container | ✓ |
| `deploy test` | Deploy | Send test predictions to a deployed endpoint | ✓ |
| `evaluate calibration` | Evaluate | Show planner calibration metrics from an experiment set | ✓ |
| `evaluate compare` | Evaluate | Compare hypotheses within an experiment set | ✓ |
| `evaluate failures` | Evaluate | Analyse failures in an experiment set | ✓ |
| `evaluate list` | Evaluate | List all saved experiment sets | ✓ |
| `evaluate report` | Evaluate | Generate evaluation report (Markdown + JSON) for an experiment set | ✓ |
| `evaluate run` | Evaluate | Run benchmark experiments and capture results as an ExperimentSet | ✓ |
| `evaluate stats` | Evaluate | Show execution statistics from benchmark data | ✓ |
| `evaluate summary` | Evaluate | Show aggregated benchmark results across all conditions | ✓ |
| `evaluate visualize` | Evaluate | Generate all figures for an experiment set | ✓ |
| `evaluate wins` | Evaluate | Show architecture win rates across benchmark problems | ✓ |
| `memory search` | Memory | Search the memory store | ✓ |
| `memory stats` | Memory | Show memory store statistics | ✓ |
| `mission cancel` | Mission | Cancel a running mission | ✓ |
| `mission list` | Mission | List missions with their current phase and status | ✓ |
| `mission logs` | Mission | Show mission event log as one line per event | ✓ |
| `mission new` | Mission | Create and start a new mission — the six-agent pipeline, end to end | ✓ |
| `mission replay` | Mission | Step through a finished mission's event trace | ✓ |
| `mission report` | Mission | Render a complete mission report | ✓ |
| `mission resume` | Mission | Resume an interrupted mission | ✓ |
| `mission status` | Mission | Show current status of a mission (latest by default) | ✓ |
| `mission watch` | Mission | Attach live progress to a mission | ✓ |
| `model export` | Model | Export a trained model to ONNX or pickle format | ✓ |
| `model inspect` | Model | Show model metadata, metrics, and evaluation results | ✓ |
| `model list` | Model | List all trained models found in outputs/ | ✓ |
| `model show` | Model | Show model metadata, metrics, and evaluation results (alias for inspect) | ✓ |
| `planner dry-run` | Planner | Compile a MissionSpecification into a plan and validate it (no execution) | ✓ |
| `planner explain` | Planner | Show why the Planner estimated what it did for a job | ✓ |
| `planner inspect` | Planner | Show the ExecutionPlan for a job | ✓ |
| `planner prediction-error` | Planner | Show prediction error history across jobs | ✓ |
| `planner stats` | Planner | Show aggregate execution statistics per architecture | ✓ |
| `planner validate` | Planner | Run all 5 validators on an existing ExecutionPlan | ✓ |
| `plugin inspect` | Plugin | Inspect a specific plugin | ✓ |
| `plugin install` | Plugin | Install a plugin by import path or package name | ✓ |
| `plugin list` | Plugin | List all registered plugins | ✓ |
| `plugin remove` | Plugin | Remove (unregister) a previously installed plugin | ✓ |
| `profile current` | Profile | Show the active profile | ✓ |
| `profile delete` | Profile | Delete a saved profile | ✓ |
| `profile inspect` | Profile | Show a profile's environment variables | ✓ |
| `profile list` | Profile | List all saved profiles | ✓ |
| `profile save` | Profile | Save current environment as a profile | ✓ |
| `profile switch` | Profile | Switch to a saved profile | ✓ |
| `provider add` | Provider | Add and verify a model provider's credentials | ✓ |
| `provider current` | Provider | Show the currently active provider with detailed status | ✓ |
| `provider list` | Provider | List all configured AI providers | ✓ |
| `daemon start` | System | Start the orchestrator as a background daemon process | ✓ |
| `daemon status` | System | Check if the orchestrator daemon is running and responding | ✓ |
| `daemon stop` | System | Stop the background orchestrator daemon | ✓ |
| `docs` | System | Generate command reference documentation from the live command tree | ✓ |
| `doctor` | System | Check system health and prerequisites | ✓ |
| `help` | System | Show help for a command or list commands by category | ✓ |
| `init` | System | Run the guided setup wizard (first-time config) | ✓ |
| `version` | System | Show the Prometheus version and dependency versions | ✓ |
| `workspace init` | Workspace | Mark a directory as a Prometheus workspace | ✓ |
| `workspace list` | Workspace | List known workspace directories | ✓ |
| `workspace use` | Workspace | Switch the active workspace by name or path | ✓ |
