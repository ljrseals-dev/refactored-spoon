"""MCP server exposing the local offline document index."""
from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .processing.indexer import LocalIndex

mcp = FastMCP("offline-doc-mcp")
INDEX_DB = Path(os.environ.get("OFFLINE_DOC_INDEX", "data/index.db"))


def get_index() -> LocalIndex:
    return LocalIndex(INDEX_DB)


@mcp.tool()
def search_documents(query: str, limit: int = 8) -> str:
    """Search indexed passages; results include title, source path and chunk."""
    results = get_index().search(query, limit=limit)
    return json.dumps(
        {"results": results, "message": "No matches" if not results else None},
        ensure_ascii=False,
    )


@mcp.tool()
def index_stats() -> str:
    """Return document and chunk counts."""
    return json.dumps(get_index().stats())


@mcp.tool()
def list_sources() -> str:
    """List configured acquisition services."""
    from .services import load_config
    try:
        config = load_config()
        return json.dumps({
            name: {
                "enabled": value.get("enabled"),
                "description": value.get("description"),
                "output_dir": value.get("output_dir"),
            }
            for name, value in config.get("services", {}).items()
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": type(exc).__name__})


if __name__ == "__main__":
    mcp.run()
