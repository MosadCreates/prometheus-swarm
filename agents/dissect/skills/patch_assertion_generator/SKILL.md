---
name: patch_assertion_generator
version: "1.0.0"
description: Generate structural post-conditions a patched training script must satisfy
category: validation
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: PatchAssertionGeneratorSkill
trusted: true
---
After Dissect applies a patch (deterministic cascade or LLM), generate named
structural assertions about the *patched* script — AST validity, no duplicate
top-level definitions, the crash's missing name now resolved, and the original
entry call preserved. An additive guard alongside the sandbox test: violations
are logged as warnings, never fatal (the sandbox outcome stays authoritative).
