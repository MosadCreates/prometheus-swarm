# Memory Commands

## `memory clear`
Clear memory store.
- **Category:** Memory
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `memory export`
Export memory data.
- **Category:** Memory
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.3.0

## `memory search`
Search memory store.
- **Category:** Memory
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `mem search`
- **Examples:**
  - `prometheus prometheus memory search 'query'`
- **Related:** `memory stats`

## `memory stats`
Show memory statistics.
- **Category:** Memory
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `mem stats`
- **Examples:**
  - `prometheus prometheus memory stats`
- **Related:** `memory search`
