from __future__ import annotations

from abc import ABC, abstractmethod

from prometheus.dto.job_dto import JobResult, JobStatusRow


class IJobService(ABC):
    @abstractmethod
    def list_jobs(self) -> list[JobStatusRow]: ...

    @abstractmethod
    def get_status(self, job_id: str) -> JobStatusRow | None: ...

    @abstractmethod
    def submit(
        self, dataset: str, description: str, target_column: str | None = None
    ) -> JobResult: ...

    @abstractmethod
    def cancel(self, job_id: str) -> bool: ...
