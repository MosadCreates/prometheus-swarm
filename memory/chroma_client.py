"""ChromaDB connection — lazy health-checked client for memory collections.

Connection lifecycle:
  - connect() is called lazily on first query
  - get_or_create_collection() calls _ensure_healthy() before every query
  - If the connection is stale (heartbeat fails), the client is recreated
  - No long-lived singleton assumption — recreates on stale connections
  - Telemetry disabled via Settings(anonymized_telemetry=False)
"""

import logging
import os

import chromadb
from chromadb.config import Settings as ChromaSettings
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class ChromaClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
        return cls._instance

    def connect(self) -> chromadb.ClientAPI:
        """Create a fresh HTTP connection to ChromaDB.

        Idempotent — safe to call multiple times. Returns the new client.
        """
        host = os.getenv("CHROMA_HOST", "localhost")
        port = int(os.getenv("CHROMA_PORT", 8000))

        self._client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        logger.info(f"ChromaDB connected at {host}:{port}")
        return self._client

    def _ensure_healthy(self) -> chromadb.ClientAPI:
        """Return a healthy client, recreating if stale.

        Pings the server via heartbeat. If the heartbeat fails
        (connection reset, timeout, server restart), creates a
        fresh client and logs the reconnect.

        This prevents "Connection lost" / "Connection closed by
        server" errors when ChromaDB restarts between jobs.
        """
        if self._client is not None:
            try:
                self._client.heartbeat()
                return self._client
            except Exception as e:
                logger.warning(
                    "ChromaDB connection stale — reconnecting " "(%s: %s)",
                    type(e).__name__,
                    e,
                )
        return self.connect()

    @property
    def client(self) -> chromadb.ClientAPI:
        if self._client is None:
            return self.connect()
        return self._client

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        """Get or create a collection with lazy health check.

        Calls _ensure_healthy() before each query to verify the
        connection is still alive. If the server has restarted or
        the connection was dropped, the client is recreated.
        """
        healthy = self._ensure_healthy()
        try:
            return healthy.get_collection(name)
        except Exception:
            return healthy.create_collection(name)
