from __future__ import annotations

from abc import ABC, abstractmethod

from prometheus.dto.agent_dto import AgentDetail, AgentSummary


class IAgentService(ABC):
    @abstractmethod
    def list_agents(self) -> list[AgentSummary]: ...

    @abstractmethod
    def inspect_agent(self, name: str) -> AgentDetail | None: ...

    @abstractmethod
    def count_agents(self) -> int: ...

    @abstractmethod
    def count_tools(self) -> int: ...
