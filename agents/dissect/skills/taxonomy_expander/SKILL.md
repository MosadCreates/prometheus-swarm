---
name: taxonomy_expander
version: "1.0.0"
description: Propose a candidate taxonomy category for weakly-matched crashes
category: analysis
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: TaxonomyExpanderSkill
trusted: true
---
When the taxonomy's match confidence is low, propose a candidate category +
regex pattern from keyword heuristics in the exception message. Surfaces
*unseen* error shapes to the researcher — the raw material for expanding the
24-category taxonomy. Never auto-applies: it only suggests.
