# Prometheus Swarm — Command Reference

| Command | Category | Description | Implemented |
|---------|----------|-------------|-------------|
| `agent disable` | Agents | Disable an agent. | ✗ |
| `agent enable` | Agents | Enable a disabled agent. | ✗ |
| `agent inspect` | Agents | Inspect a specific agent. | ✓ |
| `agent list` | Agents | List all registered agents. | ✓ |
| `agent logs` | Agents | Show agent logs. | ✓ |
| `agent metrics` | Agents | Show agent performance metrics. | ✓ |
| `agent run` | Agents | Run an agent directly. | ✗ |
| `agent stop` | Agents | Stop a running agent. | ✗ |
| `config check` | Config | Validate all prerequisites. | ✓ |
| `config edit` | Config | Open .env in the default editor. | ✓ |
| `config set` | Config | Set a KEY=VALUE in .env. | ✓ |
| `config show` | Config | Show current configuration. | ✓ |
| `deploy list` | Deploy | List deployed endpoints. | ✓ |
| `deploy logs` | Deploy | Show deploy container logs. | ✓ |
| `deploy stop` | Deploy | Stop a deployed endpoint. | ✓ |
| `deploy test` | Deploy | Test a deployed endpoint. | ✓ |
| `job cancel` | Jobs | Cancel a running job. | ✓ |
| `job delete` | Jobs | Delete a job record. | ✗ |
| `job list` | Jobs | List all jobs. | ✓ |
| `job logs` | Jobs | Show job execution logs. | ✓ |
| `job retry` | Jobs | Retry a failed job. | ✓ |
| `job status` | Jobs | Show job status. | ✓ |
| `job submit` | Jobs | Submit a dataset to the pipeline. | ✓ |
| `logs search` | Logs | Search log entries. | ✓ |
| `logs tail` | Logs | Tail Prometheus logs. | ✓ |
| `memory clear` | Memory | Clear memory store. | ✗ |
| `memory export` | Memory | Export memory data. | ✗ |
| `memory search` | Memory | Search memory store. | ✓ |
| `memory stats` | Memory | Show memory statistics. | ✓ |
| `plugin inspect` | Plugin | Inspect a specific plugin. | ✓ |
| `plugin list` | Plugin | List all registered plugins. | ✓ |
| `profile current` | Profile | Show the active profile. | ✓ |
| `profile delete` | Profile | Delete a saved profile. | ✓ |
| `profile inspect` | Profile | Show a profile's environment variables. | ✓ |
| `profile list` | Profile | List all saved profiles. | ✓ |
| `profile save` | Profile | Save current environment as a profile. | ✓ |
| `profile switch` | Profile | Switch to a saved profile. | ✓ |
| `project doctor` | Project | Check project health. | ✗ |
| `project info` | Project | Show project metadata and stats. | ✗ |
| `provider current` | Provider | Show the active provider. | ✓ |
| `provider list` | Provider | List all AI providers. | ✓ |
| `provider login` | Provider | Authenticate with a provider. | ✗ |
| `provider logout` | Provider | Log out from a provider. | ✗ |
| `provider switch` | Provider | Switch the active provider. | ✗ |
| `provider test` | Provider | Test provider connectivity. | ✗ |
| `swarm health` | Swarm | Run swarm health checks. | ✓ |
| `swarm monitor` | Swarm | Monitor swarm activity in real-time. | ✓ |
| `swarm reset` | Swarm | Reset swarm state. | ✗ |
| `swarm restart` | Swarm | Restart the swarm. | ✗ |
| `swarm start` | Swarm | Start the swarm. | ✗ |
| `swarm status` | Swarm | Show swarm runtime status. | ✓ |
| `swarm stop` | Swarm | Stop the swarm. | ✗ |
| `benchmark` | System | Run performance benchmarks. | ✗ |
| `cheatsheet` | System | Show a quick-reference cheatsheet. | ✓ |
| `commands` | System | List all available commands. | ✓ |
| `diagnostics` | System | Show command diagnostics and telemetry. | ✓ |
| `docs` | System | Generate command reference documentation. | ✓ |
| `doctor` | System | Check system prerequisites and health. | ✓ |
| `help` | System | Show help for any command. | ✓ |
| `search` | System | Search commands by name, description, or keyword. | ✓ |
| `update` | System | Check for and apply updates. | ✗ |
| `version` | System | Show the Prometheus version. | ✓ |
| `tool inspect` | Tools | Inspect a specific tool. | ✓ |
| `tool list` | Tools | List all registered tools. | ✓ |
| `workspace clean` | Workspace | Clean workspace artifacts. | ✗ |
| `workspace index` | Workspace | Index workspace for search. | ✗ |
| `workspace info` | Workspace | Show workspace metadata. | ✓ |
| `workspace init` | Workspace | Initialize a new workspace. | ✗ |
| `workspace open` | Workspace | Open workspace in file manager. | ✓ |
| `workspace scan` | Workspace | Scan workspace files and structure. | ✓ |
| `workspace status` | Workspace | Show workspace status. | ✓ |
| `workspace tree` | Workspace | Show workspace directory tree. | ✓ |
