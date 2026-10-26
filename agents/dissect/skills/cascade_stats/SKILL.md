---
name: cascade_stats
version: "1.0.0"
description: Summarize a cascade attempt (levels tried, resolution) compactly
category: analysis
agents: [dissect]
type: code
deterministic: true
requires_llm: false
entry_class: CascadeStatsSkill
trusted: true
---
Aggregates a Dissect cascade attempt — the cascade path (levels tried +
outcomes) plus the final resolution — into a compact human-readable summary.
This is the research evidence of *which* cascade level resolves which error
category, surfaced in the agent log after `run_cascade`.
