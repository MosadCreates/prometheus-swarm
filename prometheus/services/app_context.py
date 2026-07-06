from __future__ import annotations

from typing import Any


class AppContext:
    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    @property
    def agents(self):
        if "agents" not in self._services:
            from prometheus.services.agent_service import AgentService

            self._services["agents"] = AgentService()
        return self._services["agents"]

    @property
    def config(self):
        if "config" not in self._services:
            from prometheus.services.config_service import ConfigService

            self._services["config"] = ConfigService()
        return self._services["config"]

    @property
    def jobs(self):
        if "jobs" not in self._services:
            from prometheus.services.job_service import JobService

            self._services["jobs"] = JobService()
        return self._services["jobs"]

    @property
    def providers(self):
        if "providers" not in self._services:
            from prometheus.services.provider_service import ProviderService

            self._services["providers"] = ProviderService()
        return self._services["providers"]

    @property
    def memory(self):
        if "memory" not in self._services:
            from prometheus.services.memory_service import MemoryService

            self._services["memory"] = MemoryService()
        return self._services["memory"]

    @property
    def workspace(self):
        if "workspace" not in self._services:
            from prometheus.services.workspace_service import WorkspaceService

            self._services["workspace"] = WorkspaceService()
        return self._services["workspace"]

    @property
    def profiles(self):
        if "profiles" not in self._services:
            from prometheus.services.profile_service import ProfileService

            self._services["profiles"] = ProfileService()
        return self._services["profiles"]

    @property
    def plugins(self):
        if "plugins" not in self._services:
            from prometheus.plugins.registry import PluginRegistry

            self._services["plugins"] = PluginRegistry()
            self._load_plugins()
        return self._services["plugins"]

    def _load_plugins(self) -> None:
        import importlib
        import pkgutil

        import prometheus.plugins.builtin

        for _imp, name, _ispkg in pkgutil.iter_modules(prometheus.plugins.builtin.__path__):
            try:
                mod = importlib.import_module(f"prometheus.plugins.builtin.{name}")
                if hasattr(mod, "create_plugin"):
                    plugin = mod.create_plugin()
                    self._services["plugins"].register(plugin)
            except Exception:
                import traceback

                traceback.print_exc()

    @classmethod
    def create(cls) -> AppContext:
        return cls()
