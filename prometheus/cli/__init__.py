from prometheus.cli.system import (
    help_cmd,
    commands_cmd,
    search_cmd,
    doctor_cmd,
    version_cmd,
    cheatsheet_cmd,
    docs_cmd,
    diagnostics_cmd,
)
from prometheus.cli.workspace import workspace
from prometheus.cli.agent import agent
from prometheus.cli.job import job
from prometheus.cli.config import config
from prometheus.cli.provider import provider
from prometheus.cli.swarm import swarm
from prometheus.cli.deploy import deploy
from prometheus.cli.logs import logs
from prometheus.cli.memory import memory
from prometheus.cli.tool import tool
from prometheus.cli.profile import profile
from prometheus.cli.plugin import plugin
from prometheus.cli.solve import solve
from prometheus.cli.explain import explain
from prometheus.cli.replay import replay
from prometheus.cli.report import report
from prometheus.cli.planner import planner
from prometheus.cli.benchmark import benchmark
from prometheus.cli.reproduce import reproduce
from prometheus.cli.evaluate import evaluate
from prometheus.cli.mission import mission_cmd as mission

__all__ = [
    "help_cmd",
    "commands_cmd",
    "search_cmd",
    "doctor_cmd",
    "version_cmd",
    "cheatsheet_cmd",
    "docs_cmd",
    "diagnostics_cmd",
    "workspace",
    "agent",
    "job",
    "config",
    "provider",
    "swarm",
    "deploy",
    "logs",
    "memory",
    "tool",
    "profile",
    "plugin",
    "solve",
    "explain",
    "replay",
    "report",
    "planner",
    "reproduce",
    "evaluate",
    "mission",
]
