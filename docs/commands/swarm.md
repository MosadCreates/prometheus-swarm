# Swarm Commands

## `swarm health`
Run swarm health checks.
- **Category:** Swarm
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus swarm health`
- **Related:** `swarm status`

## `swarm monitor`
Monitor swarm activity in real-time.
- **Category:** Swarm
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus swarm monitor`
- **Related:** `swarm status`, `swarm health`
- **Experimental:** yes

## `swarm reset`
Reset swarm state.
- **Category:** Swarm
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.3.0
- **Experimental:** yes

## `swarm restart`
Restart the swarm.
- **Category:** Swarm
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `swarm start`
Start the swarm.
- **Category:** Swarm
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `swarm status`
Show swarm runtime status.
- **Category:** Swarm
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus swarm status`
- **Related:** `swarm health`

## `swarm stop`
Stop the swarm.
- **Category:** Swarm
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0
