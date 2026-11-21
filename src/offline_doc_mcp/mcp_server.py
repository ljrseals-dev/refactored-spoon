"""MCP server exposing offline document search.

Strictly respects mode isolation: the search tools themselves never call
external providers. Any higher-level Engine that uses this index still
honours allows_provider.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .processing.indexer import LocalIndex

mcp = FastMCP("offline-doc-mcp")

# Default index location – override with env or config later
INDEX_DB = Path("data/index.db")


def get_index() -> LocalIndex:
    return LocalIndex(INDEX_DB)


@mcp.tool()
def search_documents(query: str, limit: int = 8) -> str:
    """Search the local offline document index (keyword / FTS).

    Returns ranked passages with title and path. Fully offline.
    """
    idx = get_index()
    results = idx.search(query, limit=limit)
    if not results:
        return json.dumps({"results": [], "message": "No matches"})
    return json.dumps({"results": results}, ensure_ascii=False, indent=2)


@mcp.tool()
def index_stats() -> str:
    """Return document and chunk counts from the local index."""
    idx = get_index()
    return json.dumps(idx.stats())


@mcp.tool()
def list_sources() -> str:
    """List configured services (from services.yaml)."""
    from .services import load_config
    try:
        cfg = load_config()
        services = {
            name: {
                "enabled": sc.get("enabled"),
                "description": sc.get("description"),
                "output_dir": sc.get("output_dir"),
            }
            for name, sc in cfg.get("services", {}).items()
        }
        return json.dumps(services, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


if __name__ == "__main__":
    mcp.run()
