"""ChromaDB connection singleton. All memory collections use this."""

import logging
import os

import chromadb
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
        if self._client is not None:
            return self._client

        host = os.getenv("CHROMA_HOST", "localhost")
        port = int(os.getenv("CHROMA_PORT", 8000))

        self._client = chromadb.HttpClient(
            host=host,
            port=port,
        )

        logger.info(f"ChromaDB connected at {host}:{port}")
        return self._client

    @property
    def client(self) -> chromadb.ClientAPI:
        if self._client is None:
            return self.connect()
        return self._client

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        try:
            return self.client.get_collection(name)
        except ValueError:
            return self.client.create_collection(name)
