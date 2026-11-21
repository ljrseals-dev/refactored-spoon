# Offline Document MCP Server

Reliable offline-first document corpus + MCP server for local LLMs.

## Core Guarantees (from mode-isolation patch)

- **CLASSICAL / ARCHIVE / AUTO** modes **never** touch an LLM provider, never perform network calls after corpus is built, and never discover API keys.
- Only modes explicitly marked `allows_provider=True` may use an injected or discovered provider.
- All document acquisition is limited to clearly public-domain / open-license sources.
- Once indexed, the system runs fully offline.

## Supported Sources (modular)

Configured in `config/services.yaml`. Add new legal sources by appending a service block.

Current defaults:
- Project Gutenberg (public domain)
- Wikipedia / Wikimedia dumps (CC BY-SA)
- Internet Archive public-domain / CC0 items

## Quick Start

```bash
# Install
pip install -e .

# (Optional) Download legal corpora
python -m offline_doc_mcp.cli acquire --service project_gutenberg
python -m offline_doc_mcp.cli acquire --service wikipedia_dumps
python -m offline_doc_mcp.cli acquire --service internet_archive_pd

# Process + index
python -m offline_doc_mcp.cli process
python -m offline_doc_mcp.cli index

# Run MCP server (stdio)
python -m offline_doc_mcp.mcp_server

# Optional local HTML UI
python -m offline_doc_mcp.html_server --port 8765
```

## Mode Isolation

See `src/offline_doc_mcp/engine/modes.py` and `engine.py`.  
Offline modes short-circuit before any provider lookup.

## License

MIT (code).  
Documents retain their original licenses (public domain / CC BY-SA / CC0 etc.).
