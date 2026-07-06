# Logs Commands

## `logs search`
Search log entries.
- **Category:** Logs
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus logs search 'error'`
- **Related:** `logs tail`

## `logs tail`
Tail Prometheus logs.
- **Category:** Logs
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `logs follow`
- **Examples:**
  - `prometheus prometheus logs tail --lines 50`
- **Related:** `logs search`
