# Profile Commands

## `profile current`
Show the active profile.
- **Category:** Profile
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `profiles current`
- **Examples:**
  - `prometheus prometheus profile current`
- **Related:** `profile list`

## `profile delete`
Delete a saved profile.
- **Category:** Profile
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `profiles delete`
- **Examples:**
  - `prometheus prometheus profile delete my-config`
- **Related:** `profile list`

## `profile inspect`
Show a profile's environment variables.
- **Category:** Profile
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `profiles inspect`
- **Examples:**
  - `prometheus prometheus profile inspect my-config`
- **Related:** `profile list`

## `profile list`
List all saved profiles.
- **Category:** Profile
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `profiles list`
- **Examples:**
  - `prometheus prometheus profile list`
- **Related:** `profile current`, `profile save`, `profile switch`

## `profile save`
Save current environment as a profile.
- **Category:** Profile
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `profiles save`
- **Examples:**
  - `prometheus prometheus profile save my-config`
- **Related:** `profile list`, `profile switch`

## `profile switch`
Switch to a saved profile.
- **Category:** Profile
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `profiles switch`
- **Examples:**
  - `prometheus prometheus profile switch my-config`
- **Related:** `profile list`, `profile save`
