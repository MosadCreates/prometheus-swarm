# Deploy Commands

## `deploy list`
List deployed endpoints.
- **Category:** Deploy
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `deploy ls`
- **Examples:**
  - `prometheus prometheus deploy list`
- **Related:** `deploy test`, `deploy logs`

## `deploy logs`
Show deploy container logs.
- **Category:** Deploy
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus deploy logs <container>`
- **Related:** `deploy list`

## `deploy stop`
Stop a deployed endpoint.
- **Category:** Deploy
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus deploy stop <container>`
- **Related:** `deploy list`

## `deploy test`
Test a deployed endpoint.
- **Category:** Deploy
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus deploy test http://localhost:8080 -i test.json`
- **Related:** `deploy list`
