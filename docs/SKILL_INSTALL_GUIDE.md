# Installing & Verifying a Skill — Step-by-Step

How to install an external skill into Prometheus Swarm and prove the system
actually learned it, using the CLI alone (no Redis / Docker / API key required).

> **Is this Dissect-only?** No. The skill platform is mounted on **all six agents**
> (`agents/base.py:47` sets `self.skills` on every agent), and any skill can route to
> any agent via its `agents:` manifest field plus `skill install --agent`.
> What is Dissect-only *today*: (a) the **bundled** skills (Phase 3 is being built one
> agent at a time, Dissect first), and (b) the **code call sites** — only the six
> Dissect names below are invoked by agent code, so a code skill with a *new* name
> installs and passes `skill test` but isn't called until that agent's wiring lands.
> The zero-code paths that work for **any** agent right now:
> - a **trusted instruction skill** is auto-injected into the LLM prompt (wired for
>   Dissect and Forge),
> - a **same-named installed skill shadows the bundled one** and is the copy that runs.

## Prerequisites

- The repo venv with `requirements.txt` installed (the `prometheus` command or
  `python -m prometheus`).
- **None of the verify steps below need Redis, Docker, or an API key.** Only
  `skill promote` (the runtime evidence gate) reads Redis — see "What CLI-level
  verification cannot prove" at the end.

## Exact skill file names to start with

These are the six bundled Dissect skills — the **only code-skill names wired into an
agent today**, so an installed copy of any of them is the copy that would actually run
on a crash:

```
crash_localizer
error_signature_extractor
patch_assertion_generator
cascade_stats
taxonomy_expander
rule_generalizer
```

The repo ships two ready-to-install example skills under `examples/skills/`:

| Folder | Kind | What it demonstrates |
|--------|------|----------------------|
| `examples/skills/crash_localizer_shadow/` | code (name `crash_localizer`, v1.1.0) | the **shadow** path — installs as `root=installed`, subprocess-isolated, adds a `suggestion` field |
| `examples/skills/forge_md_tips/` | instruction (markdown only) | the **zero-code** path — needs `--trust`, then auto-injects into Forge's LLM prompt |

## Step 1 — Install

All commands run from the repo root.

```bash
# A) Local skill folder (type auto-detected as "local")
python -m prometheus skill install examples/skills/crash_localizer_shadow --agent dissect
# → "Installed skill 'crash_localizer'"

# B) A bare .md instruction skill — --trust is REQUIRED
python -m prometheus skill install examples/skills/forge_md_tips --agent forge --trust
# → "Installed skill 'forge_md_tips'"

# C) git repo / registry archive (signature required unless --no-verify)
#    NOTE: the URLs below are PLACEHOLDERS — use a real, reachable repo/archive,
#    or git clone / getaddrinfo will fail with a staging error (expected).
python -m prometheus skill install https://github.com/<you>/<repo> --type git
python -m prometheus skill install https://<host>/acme.zip --type registry
```

Notes:
- `--type` is optional — the source is auto-detected (`.md` → `md`, `http(s)/git@/ssh://`
  → `git` or `registry` if it ends in `.zip/.tar.gz/.tgz`, a directory → `local`).
- `--name NAME` renames the skill at install; `--force` overwrites an already-installed
  name.
- Install is **atomic**: the skill is staged, run through the 4-step gate, then swapped
  into `~/.prometheus/skills/<name>/` in one `os.replace` — a running job never reads a
  half-written skill.
- The install gate prints exactly which check failed, e.g.:
  ```
  ✗ trust: instruction skills require --trust (their body is injected into an LLM agent's prompt)
  ✗ structural: no Skill subclass found in skill.py
  ✗ smoke:dissect: agent-compat smoke failed for dissect: ...
  ```

## Step 2 — Verify the system really learned it (CLI ladder)

### 1. `skill list` — it is discovered
```bash
python -m prometheus skill list --agent dissect
```
Your installed skill appears as a row with `root=installed` and `status=active`.
For the shadow demo, the installed `crash_localizer` v1.1.0 **replaces** the bundled
row — the registry keeps one row per name and the installed copy wins — so you see
`crash_localizer` once with `root=installed` (and the pre-install baseline had it as
`root=bundled`). `--installed-only` shows only installed skills; `skill info` confirms
the installed `path` under `~/.prometheus/skills/`.

### 2. `skill info <name>` — it is validated + active
```bash
python -m prometheus skill info crash_localizer
```
Confirms `root=installed`, `type=code`, `trusted=yes`, `status=active (ok)`,
`structural=ok`, and the installed `path` under `~/.prometheus/skills/`.

### 3. `skill test <name> --agent <agent>` — it actually executes (strongest CLI proof)
```bash
python -m prometheus skill test crash_localizer --agent dissect
# → "'crash_localizer' ran cleanly"
#   {..., 'suggestion': 'inspect the call around line ...', ...}
```
This re-runs the install gate's dry-run smoke **in the subprocess worker** against the
real captured mission context (`tests/fixtures/skill_contexts/<agent>.json`). For the
shadow, the detail dict includes the new `suggestion` field — proving the **installed**
copy ran, not the bundled one. An instruction skill reports
`'forge_md_tips' is an instruction skill — body is valid, nothing to execute`.

### 4. `skill verify <name>` — signature (signed skills only)
```bash
python -m prometheus skill verify crash_localizer
```
Only meaningful for a publisher-signed skill; an unsigned skill reports
`manifest declares no publisher`.

### Cleanup
```bash
python -m prometheus skill remove crash_localizer     # removes the installed copy
python -m prometheus skill remove forge_md_tips
```
Bundled skills can never be removed (`'<name>' is a bundled skill and cannot be removed`).

## What CLI-level verification cannot prove (honest)

`skill list/info/test` prove the system *has*, *validated*, and *can execute* the skill.
They do **not** prove an agent *invoked it during a real job*. That is the runtime
evidence gate, which needs a live mission (Redis + Docker + API key):

- Every `SkillRegistry.run()` updates Redis `skill:<name>:<agent>:stats` with
  `total_runs`, `ok_runs`, `consecutive_ok`, `fallback_fired`.
- `skill promote <name> --agent <agent>` refuses until ≥10 consecutive ok runs with zero
  fallbacks (default; `promote_consecutive_ok`), then writes the promotion to
  `~/.prometheus/promotions.json`.
- Without Redis, `skill promote` returns the expected refusal:
  `evidence gate not met: no stats recorded for <name> on '<agent>' (need 10 consecutive ok runs, zero fallbacks)`

So the full "learned it" claim is: **discovered + validated + executes (CLI)** → then
**invoked on real jobs + stats accumulate (runtime)** → then **promoted stable + fallback
removed** (`skill check-orphans` lists any stable skill whose call site still carries a
fallback branch).
