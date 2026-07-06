from __future__ import annotations

from abc import ABC, abstractmethod

from prometheus.dto.workspace_dto import ScanResult, WorkspaceInfo


class IWorkspaceService(ABC):
    @abstractmethod
    def get_info(self) -> WorkspaceInfo: ...

    @abstractmethod
    def scan(self) -> ScanResult: ...

    @abstractmethod
    def status(self) -> str: ...
