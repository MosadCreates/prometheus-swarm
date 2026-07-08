"""Adaptive Planning Engine — execution feedback, planning hints, prediction error.

The learning module bridges execution experience back into planning.
It is not an agent — no event loop, no consumer group, no LLM calls.
It is a library consumed by the Orchestrator to produce PlanningHints
from historical ExecutionOutcome records.
"""
