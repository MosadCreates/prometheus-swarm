# Workspace Commands

## `workspace clean`
Clean workspace artifacts.
- **Category:** Workspace
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `workspace index`
Index workspace for search.
- **Category:** Workspace
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `workspace info`
Show workspace metadata.
- **Category:** Workspace
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `ws info`
- **Examples:**
  - `prometheus prometheus workspace info`
- **Related:** `workspace scan`, `workspace status`

## `workspace init`
Initialize a new workspace.
- **Category:** Workspace
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `workspace open`
Open workspace in file manager.
- **Category:** Workspace
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `ws open`
- **Examples:**
  - `prometheus prometheus workspace open`
- **Related:** `workspace info`, `workspace tree`
- **Requires workspace:** yes

## `workspace scan`
Scan workspace files and structure.
- **Category:** Workspace
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `ws scan`
- **Examples:**
  - `prometheus prometheus workspace scan`
- **Related:** `workspace info`
- **Requires workspace:** yes

## `workspace status`
Show workspace status.
- **Category:** Workspace
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `ws status`
- **Examples:**
  - `prometheus prometheus workspace status`
- **Related:** `workspace info`, `workspace scan`

## `workspace tree`
Show workspace directory tree.
- **Category:** Workspace
- **Tier:** 2
- **Implemented:** ✓
- **Aliases:** `ws tree`
- **Examples:**
  - `prometheus prometheus workspace tree`
- **Related:** `workspace info`, `workspace status`
- **Requires workspace:** yes
