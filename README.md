# Offline Document MCP Server

Reliable offline-first document corpus + MCP server for local LLMs.

## Retrieval-Augmented Generation (RAG) Pipeline

The answering path is RAG-first: **Ingest → Parse → Chunk → Index → Retrieve → Generate → Cite**. The current local retrieval implementation uses SQLite FTS lexical search; semantic embeddings and reranking are not yet implemented, so those stages are explicitly future capabilities rather than claimed features. Provider-enabled modes receive numbered retrieved passages and grounding instructions; answers must cite passage markers and acknowledge missing context. Offline modes only retrieve and return source passages and never invoke a provider.

## Core Guarantees

- **CLASSICAL / ARCHIVE / AUTO** modes **never** touch an LLM provider, never perform network calls after corpus is built, and never discover API keys.
- Only modes explicitly marked `allows_provider=True` may use a provider explicitly injected by the caller; there is no environment-key discovery.
- Acquisition is limited to public-domain/open-license source paths, subject to source rights and local verification.
- Once indexed, search runs fully offline.

## Supported Sources

Configured in `config/services.yaml`. Only enabled sources run.

## Quick Start

```bash
pip install -e .

# Acquire documents (optional; external sources and robots policy apply)
offline-doc acquire --service project_gutenberg

# Extract supported files to text
offline-doc process

# Build/refresh local index
offline-doc index

# Search offline index
offline-doc search "document search"

# Run MCP server (stdio)
python -m offline_doc_mcp.mcp_server

# Optional local HTML UI
python -m offline_doc_mcp.html_server --port 8765
```

## Processing and indexing

`offline-doc process` extracts locally from text, Markdown, HTML, PDF, EPUB, and DOCX into a mirrored `data/processed/` text tree. PDF/EPUB/DOCX parsing is local-only; this command makes no network requests and does not execute document content. Empty/unextractable files are skipped with counts. Each extracted text file gets a small JSON sidecar identifying its source-relative path and format.

`offline-doc index` reads `data/processed/` and uses `processing.chunk_size`, `chunk_overlap`, and `min_chunk_chars` from `config/services.yaml`. Refresh reconciles documents removed from the processed tree, but does not prune when the source directory is missing. Search is lexical FTS5; all query tokens are ANDed and query syntax is treated as plain tokens.

## Acquisition and attribution

Acquisition is subject to robots.txt and source-specific licensing. It does not spoof browser identities, bypass robots rules, defeat authentication, or fetch login-gated content. PDFs and EPUBs can be extracted during processing, but OCR is not implemented; scanned PDFs may produce empty text.

Official source links:
- [Project Gutenberg catalog](https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv)
- [Project Gutenberg terms](https://www.gutenberg.org/policy/terms_of_use.html)
- [Internet Archive advanced search](https://archive.org/advancedsearch.php)
- [Internet Archive metadata API](https://archive.org/developers/md-read.html)
- [Wikimedia dump portal](https://dumps.wikimedia.org/)
- [Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/)

Project Gutenberg public-domain status varies by jurisdiction. Internet Archive items must be checked against their metadata/rights. Wikipedia extracts require CC BY-SA attribution. This application preserves local file paths as source labels; users should retain source/license metadata when redistributing documents.

## Modes

See `src/offline_doc_mcp/engine/modes.py` and `engine.py`. Provider access is explicit and mode-gated.

## License

MIT (code). Source documents retain their own licenses.
