"""tool_memory collection: semantic retrieval of tool docstrings."""

import importlib
import logging
from typing import Any

from memory.chroma_client import ChromaClient

logger = logging.getLogger(__name__)

COLLECTION_NAME = "tool_memory"


def _get_collection():
    return ChromaClient().get_or_create_collection(COLLECTION_NAME)


def store_tool(
    tool_id: str,
    agent_name: str,
    tool_name: str,
    docstring: str,
    source_file: str,
) -> None:
    """Store a tool's docstring for semantic retrieval.

    Args:
        tool_id: Unique ID for the tool
        agent_name: Which agent owns this tool (e.g., "Scout", "Forge")
        tool_name: Function name
        docstring: The tool's docstring
        source_file: File path where the tool is defined
    """
    from memory.embeddings import get_embedding_model

    model = get_embedding_model()
    if model is None:
        logger.warning("Embedding model not available")
        return

    embedding = model.encode(docstring).tolist()

    metadata = {
        "agent_name": agent_name,
        "tool_name": tool_name,
        "source_file": source_file,
    }

    collection = _get_collection()
    collection.upsert(
        ids=[tool_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[docstring],
    )

    logger.debug(f"Tool stored: {tool_name} | agent={agent_name}")


def query_tools(
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve K most semantically similar tools.

    Args:
        query: Natural-language description of what the tool should do
        k: Number of results

    Returns:
        List of dicts with keys: tool_name, agent_name, docstring, similarity_score
    """
    from memory.embeddings import get_embedding_model

    model = get_embedding_model()
    if model is None:
        logger.warning("Embedding model not available")
        return []
    embedding = model.encode(query).tolist()

    collection = _get_collection()

    results = collection.query(
        query_embeddings=[embedding],
        n_results=k,
    )

    tools = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0.0

            tools.append(
                {
                    "tool_id": doc_id,
                    "similarity_score": round(max(0.0, 1.0 - float(distance)), 4),
                    "tool_name": meta.get("tool_name", ""),
                    "agent_name": meta.get("agent_name", ""),
                    "docstring": results["documents"][0][i] if results.get("documents") else "",
                }
            )

    return tools


def retrieve_relevant_tools(
    agent_name: str,
    task: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve the tools most relevant to a task, for a given agent.

    Thin, failure-tolerant wrapper over :func:`query_tools` so callers (e.g.
    Forge's LLM strategy) can inject retrieved tool docstrings into prompts or
    generated-script headers without handling ChromaDB/embedding failures.

    Args:
        agent_name: Which agent the tools belong to (e.g. ``"Forge"``).
        task: Natural-language description of what the agent is about to do.
        k: Number of tools to retrieve.

    Returns:
        List of tool dicts (see :func:`query_tools`); ``[]`` on any failure.
    """
    try:
        return query_tools(query=task, k=k)
    except Exception as e:
        logger.warning(f"[{agent_name}] tool_memory retrieval failed: {e}")
        return []


def format_tool_hints(tools: list[dict[str, Any]]) -> str:
    """Format retrieved tools into a compact "available tools" text block.

    Safe with empty lists — returns ``""`` so callers can append it to a header
    without extra branching.
    """
    if not tools:
        return ""
    lines = []
    for t in tools:
        name = t.get("tool_name") or t.get("tool_id") or "tool"
        agent = t.get("agent_name") or ""
        doc = (t.get("docstring") or "").strip().splitlines()
        doc_head = doc[0].strip() if doc else ""
        sim = t.get("similarity_score")
        sim_suffix = f" (sim {sim:.2f})" if isinstance(sim, (int, float)) else ""
        lines.append(f"  - {name} [{agent}]{sim_suffix}: {doc_head}")
    return "Available tools from tool memory:\n" + "\n".join(lines)


def register_agent_tools(agent_name: str, module_path: str) -> int:
    """Register all public callable functions with docstrings from a tools module.

    Scans the module for functions (not starting with ``_``) that have a non-empty
    docstring and stores each one in the ``tool_memory`` ChromaDB collection.

    Args:
        agent_name: Agent identifier (e.g. ``"Scout"``, ``"Forge"``)
        module_path: Dotted module path (e.g. ``"agents.scout.tools"``)

    Returns:
        Number of tools successfully registered
    """
    try:
        module = importlib.import_module(module_path)
    except Exception as e:
        logger.warning(f"Cannot import module {module_path}: {e}")
        return 0

    import inspect

    count = 0
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("_"):
            content = obj.__doc__ or f"{name}({inspect.signature(obj)})"
            tool_id = f"{agent_name}:{name}"
            store_tool(
                tool_id=tool_id,
                agent_name=agent_name,
                tool_name=name,
                docstring=content,
                source_file=module_path,
            )
            count += 1

    logger.info(f"Registered {count} tools for agent {agent_name} from {module_path}")
    return count
