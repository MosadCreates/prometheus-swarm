from __future__ import annotations

from pathlib import Path

from prometheus.dto.agent_dto import AgentDetail, AgentSummary
from prometheus.contracts import IAgentService


AGENT_NAMES = {
    "scout": ("Scout", "The Perceiver — exploratory data analysis"),
    "forge": ("Forge", "The Architect — model architecture selection"),
    "furnace": ("Furnace", "The Smith — distributed training execution"),
    "dissect": ("Dissect", "The Debugger — error diagnosis and patching"),
    "arbiter": ("Arbiter", "The Judge — model evaluation"),
    "harbor": ("Harbor", "The Keeper — model deployment"),
}

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


class AgentService(IAgentService):
    def list_agents(self) -> list[AgentSummary]:
        agents: list[AgentSummary] = []
        for role, (display, _desc) in AGENT_NAMES.items():
            tool_count = self._count_tools_for(role)
            agents.append(
                AgentSummary(
                    name=role,
                    display_name=display,
                    status="idle",
                    tools=tool_count,
                )
            )
        return agents

    def inspect_agent(self, name: str) -> AgentDetail | None:
        entry = AGENT_NAMES.get(name.lower())
        if entry is None:
            return None
        display, desc = entry
        tools = self._collect_tools(name)
        return AgentDetail(
            name=name,
            display_name=display,
            status="idle",
            role=name.capitalize(),
            version="0.1.0",
            tools=tools,
            capabilities=[desc],
        )

    def count_agents(self) -> int:
        return len(AGENT_NAMES)

    def count_tools(self) -> int:
        total = 0
        for role in AGENT_NAMES:
            total += self._count_tools_for(role)
        return total

    def _count_tools_for(self, role: str) -> int:
        try:
            mod_path = AGENTS_DIR / role / "tools.py"
            if not mod_path.exists():
                return 0
            import importlib.util
            import inspect

            spec = importlib.util.spec_from_file_location(f"agents.{role}.tools", mod_path)
            if spec is None or spec.loader is None:
                return 0
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return sum(
                1 for n, f in inspect.getmembers(mod, inspect.isfunction) if not n.startswith("_")
            )
        except Exception:
            return 0

    def _collect_tools(self, role: str) -> list[str]:
        try:
            mod_path = AGENTS_DIR / role / "tools.py"
            if not mod_path.exists():
                return []
            import importlib.util
            import inspect

            spec = importlib.util.spec_from_file_location(f"agents.{role}.tools", mod_path)
            if spec is None or spec.loader is None:
                return []
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return [
                f"{role}.{n}"
                for n, f in inspect.getmembers(mod, inspect.isfunction)
                if not n.startswith("_")
            ]
        except Exception:
            return []
