"""Prometheus Planner — execution strategist for the swarm.

The Planner is a deterministic compiler, not an autonomous agent.
It converts MissionSpecification (what to build) into ExecutionPlan (how to execute it).

No Agent class. No event loop. No heartbeat. No Redis consumer group.
It is a pure library consumed by the Orchestrator.
"""
