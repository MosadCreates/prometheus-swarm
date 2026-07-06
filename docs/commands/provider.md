# Provider Commands

## `provider current`
Show the active provider.
- **Category:** Provider
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `prov current`
- **Examples:**
  - `prometheus prometheus provider current`
- **Related:** `provider list`

## `provider list`
List all AI providers.
- **Category:** Provider
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `prov list`
- **Examples:**
  - `prometheus prometheus provider list`
- **Related:** `provider current`

## `provider login`
Authenticate with a provider.
- **Category:** Provider
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.3.0

## `provider logout`
Log out from a provider.
- **Category:** Provider
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.3.0

## `provider switch`
Switch the active provider.
- **Category:** Provider
- **Tier:** 2
- **Implemented:** ✗
- **Since:** v0.2.0

## `provider test`
Test provider connectivity.
- **Category:** Provider
- **Tier:** 2
- **Implemented:** ✗
- **Since:** v0.2.0
