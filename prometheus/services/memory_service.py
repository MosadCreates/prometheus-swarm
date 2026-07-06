from __future__ import annotations

from prometheus.contracts import IMemoryService


class MemoryService(IMemoryService):
    def stats(self) -> dict:
        try:
            from memory.chroma_client import get_collection_stats

            chroma = get_collection_stats()
        except Exception:
            chroma = {}

        try:
            from memory.redis_client import get_info

            redis_info = get_info()
        except Exception:
            redis_info = {}

        return {
            "chroma": chroma,
            "redis": redis_info,
        }

    def search(self, query: str, limit: int = 10) -> list[dict]:
        try:
            from memory.chroma_client import search_memory

            return search_memory(query, n_results=limit)
        except Exception:
            return []
