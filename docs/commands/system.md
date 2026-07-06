# System Commands

## `benchmark`
Run performance benchmarks.
- **Category:** System
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.3.0
- **Experimental:** yes

## `cheatsheet`
Show a quick-reference cheatsheet.
- **Category:** System
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus cheatsheet`
- **Related:** `help`, `commands`, `search`

## `commands`
List all available commands.
- **Category:** System
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus commands`
- **Related:** `help`, `search`

## `diagnostics`
Show command diagnostics and telemetry.
- **Category:** System
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus diagnostics`
- **Related:** `doctor`

## `docs`
Generate command reference documentation.
- **Category:** System
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus docs --output docs/commands`
- **Related:** `help`, `commands`

## `doctor`
Check system prerequisites and health.
- **Category:** System
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus doctor`
- **Related:** `config check`

## `help`
Show help for any command.
- **Category:** System
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `?`
- **Examples:**
  - `prometheus prometheus help`
  - `prometheus prometheus help agent list`
- **Related:** `commands`, `search`, `cheatsheet`

## `search`
Search commands by name, description, or keyword.
- **Category:** System
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus search deploy`
- **Related:** `commands`, `help`

## `update`
Check for and apply updates.
- **Category:** System
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `version`
Show the Prometheus version.
- **Category:** System
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `--version`
- **Examples:**
  - `prometheus prometheus version`
- **Related:** `doctor`
