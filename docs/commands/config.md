# Config Commands

## `config check`
Validate all prerequisites.
- **Category:** Config
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `cfg check`
- **Examples:**
  - `prometheus prometheus config check`
- **Related:** `doctor`

## `config edit`
Open .env in the default editor.
- **Category:** Config
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `cfg edit`
- **Examples:**
  - `prometheus prometheus config edit`
- **Related:** `config show`, `config set`

## `config set`
Set a KEY=VALUE in .env.
- **Category:** Config
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `cfg set`
- **Examples:**
  - `prometheus prometheus config set KEY=value`
- **Related:** `config show`

## `config show`
Show current configuration.
- **Category:** Config
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `cfg show`
- **Examples:**
  - `prometheus prometheus config show`
- **Related:** `config set`, `config check`
