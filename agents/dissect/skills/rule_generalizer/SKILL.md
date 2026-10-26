---
name: rule_generalizer
version: "1.0.0"
description: Generalize a successful repair into a reusable message-pattern rule
category: learning
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: RuleGeneralizerSkill
trusted: true
---
Derives a generalized rule from a successful repair: the error category, a
regex built by blanking out volatile tokens (numbers, hex, quoted literals) in
the exception message, and the patch diff that fixed it. This is the raw
material Dissect's promotion machinery (repair templates / cache / rules) is
built on — surfaced for the researcher, never auto-applied.
