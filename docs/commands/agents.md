# Agents Commands

## `agent disable`
Disable an agent.
- **Category:** Agents
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `agent enable`
Enable a disabled agent.
- **Category:** Agents
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `agent inspect`
Inspect a specific agent.
- **Category:** Agents
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `ag inspect`
- **Examples:**
  - `prometheus prometheus agent inspect scout`
- **Related:** `agent list`

## `agent list`
List all registered agents.
- **Category:** Agents
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `ag list`, `agent ls`
- **Examples:**
  - `prometheus prometheus agent list`
- **Related:** `agent inspect`

## `agent logs`
Show agent logs.
- **Category:** Agents
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `ag logs`
- **Examples:**
  - `prometheus prometheus agent logs forge`
- **Related:** `agent list`, `agent inspect`

## `agent metrics`
Show agent performance metrics.
- **Category:** Agents
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `ag metrics`
- **Examples:**
  - `prometheus prometheus agent metrics`
- **Related:** `agent list`, `agent logs`

## `agent run`
Run an agent directly.
- **Category:** Agents
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `agent stop`
Stop a running agent.
- **Category:** Agents
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0
