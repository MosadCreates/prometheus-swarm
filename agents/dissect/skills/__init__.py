"""Bundled Dissect skills (Phase 3).

Each subdirectory is a real skill folder (``SKILL.md`` + ``skill.py``),
authored exactly as a third-party skill would be — the reference
implementations that prove the skill platform in production. They are scanned
by ``default_bundled_roots()`` (``agents/<agent>/skills``), run in-process,
and wired into ``DissectAgent.handle_crash`` with a non-blocking fallback
(Cross-cutting contract #4): a failed skill call degrades to the existing
deterministic path instead of failing the job.
"""
