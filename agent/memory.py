"""ChromaDB-backed persistent memory for LocalGrokLoop."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings

logger = logging.getLogger(__name__)


class MemoryStore:
    """Vector memory with metadata for agent recall across restarts."""

    def __init__(self) -> None:
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.memory_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Connected to ChromaDB collection: %s", settings.memory_collection)

    def store(
        self,
        content: str,
        *,
        goal_id: str = "",
        memory_type: str = "observation",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a memory chunk; returns memory ID."""
        doc_id = hashlib.sha256(
            f"{goal_id}:{content}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16]

        meta: dict[str, Any] = {
            "goal_id": goal_id,
            "type": memory_type,
            "tags": ",".join(tags or []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})

        self._collection.upsert(ids=[doc_id], documents=[content], metadatas=[meta])
        logger.debug("Stored memory %s (%s)", doc_id, memory_type)
        return doc_id

    def search(self, query: str, *, goal_id: str = "", top_k: int | None = None) -> list[dict]:
        """Semantic search over stored memories."""
        k = top_k or settings.memory_top_k
        where: dict[str, Any] | None = {"goal_id": goal_id} if goal_id else None

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=k,
                where=where,
            )
        except Exception as exc:
            logger.warning("Memory search failed: %s", exc)
            return []

        memories: list[dict] = []
        if not results.get("documents"):
            return memories

        for i, doc in enumerate(results["documents"][0]):
            memories.append(
                {
                    "id": results["ids"][0][i],
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                }
            )
        return memories

    def format_context(self, query: str, *, goal_id: str = "", include_global: bool = True) -> str:
        """Format goal-specific and global memories as context for the LLM."""
        goal_hits = self.search(query, goal_id=goal_id, top_k=4) if goal_id else []
        global_hits = self.search(query, goal_id="", top_k=4) if include_global else []

        if not goal_hits and not global_hits:
            return "No relevant memories found."

        lines: list[str] = []
        if goal_hits:
            lines.append("## Goal-specific memories")
            for hit in goal_hits:
                meta = hit.get("metadata", {})
                lines.append(f"- [{meta.get('type', 'note')}] {hit['content'][:400]}")
        if global_hits:
            lines.append("## Global/project memories")
            seen = {h["id"] for h in goal_hits}
            for hit in global_hits:
                if hit["id"] in seen:
                    continue
                meta = hit.get("metadata", {})
                gid = meta.get("goal_id", "global")
                lines.append(f"- [{meta.get('type', 'note')} goal={gid}] {hit['content'][:400]}")
        return "\n".join(lines)

    def count(self) -> int:
        return self._collection.count()


_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Lazy singleton — allows ChromaDB time to start."""
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


class _MemoryProxy:
    """Proxy so `memory_store.store(...)` works after lazy init."""

    def __getattr__(self, name: str):
        return getattr(get_memory_store(), name)


memory_store = _MemoryProxy()
