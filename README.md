# Offline Document MCP Server

Reliable offline-first document corpus + MCP server for local LLMs.

## Retrieval-Augmented Generation (RAG) Pipeline

The answering path is RAG-first: **Ingest → Parse → Chunk → Index → Retrieve → Generate → Cite**. The current local retrieval implementation uses SQLite FTS lexical search; semantic embeddings and reranking are not yet implemented, so those stages are explicitly future capabilities rather than claimed features. Provider-enabled modes receive numbered retrieved passages and grounding instructions; answers must cite passage markers and acknowledge missing context. Offline modes only retrieve and return source passages and never invoke a provider.

## Core Guarantees (from mode-isolation patch)

- **CLASSICAL / ARCHIVE / AUTO** modes **never** touch an LLM provider, never perform network calls after corpus is built, and never discover API keys.
- Only modes explicitly marked `allows_provider=True` may use a provider explicitly injected by the caller; there is no environment-key discovery.
- All document acquisition is limited to clearly public-domain / open-license sources.
- Once indexed, the system runs fully offline.

## Supported Sources (modular)

Configured in `config/services.yaml`. Add new legal sources by appending a service block.

Current defaults:
- Project Gutenberg (public domain)
- Wikipedia REST page extracts (CC BY-SA; large dumps are not automatically mirrored)
- Internet Archive public-domain / CC0 items

## Quick Start

```bash
# Install
pip install -e .

# (Optional) Download legal corpora
python -m offline_doc_mcp.cli acquire --service project_gutenberg
python -m offline_doc_mcp.cli acquire --service wikipedia_dumps
python -m offline_doc_mcp.cli acquire --service internet_archive_pd

# Extract acquired content into normalized text
python -m offline_doc_mcp.cli process

# Build/refresh the index
python -m offline_doc_mcp.cli index

# Search
offline-doc search "document search"

# Run MCP server (stdio)
python -m offline_doc_mcp.mcp_server

# Optional local HTML UI
python -m offline_doc_mcp.html_server --port 8765
```

## Real acquisition, robots policy and attribution

The acquisition services download source material rather than creating metadata stubs. All source requests use HTTPS, a descriptive `RefactoredSpoonBot` User-Agent, a per-host delay, bounded retries, redirect limits, download-size caps, and the origin's `robots.txt`. A disallowed path is skipped; if robots policy cannot be read (network error or server error), the downloader fails closed. It does not spoof browser identities, bypass robots rules, or defeat authentication.

Set a contact address so source operators can identify the crawler:

```bash
export OFFLINE_DOC_CONTACT="crawler-admin@example.org"
```

This is contact metadata, not a password or API credential. Public Gutenberg, Wikipedia REST and public Internet Archive files do not require login credentials. The downloader does not send stored cookies or API keys. It will not fetch private, restricted, or login-gated items.

### Download examples

```bash
# Project Gutenberg: UTF-8 plain text for the configured US public-domain jurisdiction
offline-doc acquire --service project_gutenberg

# Internet Archive: public-domain/CC0 metadata checks
offline-doc acquire --service internet_archive_pd

# Wikipedia: attributed CC BY-SA extracts
offline-doc acquire --service wikipedia_dumps --query "open source software"
```

## Processing and indexing

`process` performs local text extraction for plain text, Markdown, HTML, PDF, EPUB, and DOCX files under `data/`. Extracted text is written to `data/processed/` with source-relative paths and JSON sidecars recording source path and input format. Outputs are written atomically, malformed files are counted and skipped without aborting the whole batch, and obsolete generated outputs are removed when their source is deleted. It makes no network requests and does not execute document content.

PDF/EPUB/DOCX extraction is local. OCR is not implemented, so scanned PDFs may yield no text. Text extraction is best-effort; parser errors are surfaced as per-file error counts.

`index` reads the processed text tree and uses the `processing.chunk_size`, `chunk_overlap`, and `min_chunk_chars` settings from `config/services.yaml`. Index refresh reconciles deleted processed files, but does not prune when the input directory is missing. Search uses SQLite FTS5 lexical search; all query tokens are ANDed and query syntax is treated as plain tokens.

## Official source links

- [Project Gutenberg catalog](https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv)
- [Project Gutenberg terms](https://www.gutenberg.org/policy/terms_of_use.html)
- [Internet Archive advanced search](https://archive.org/advancedsearch.php)
- [Internet Archive metadata API](https://archive.org/developers/md-read.html)
- [Wikimedia dump portal](https://dumps.wikimedia.org/)
- [Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/)

Project Gutenberg public-domain status is jurisdiction-dependent; the configuration is explicitly limited to US public-domain use and is not a legal determination for other countries. Internet Archive files should be checked against item metadata for Public Domain Mark / CC0 or explicit public-domain rights. Wikipedia extracts require CC BY-SA attribution. Acquisition sidecar JSON files preserve source/license metadata.

A zero download count can mean robots.txt disallowed the source, no suitable public text was found, or the remote source was unavailable; inspect the source's robots policy and item rights rather than bypassing them.

## Mode Isolation

See `src/offline_doc_mcp/engine/modes.py` and `engine.py`. Offline modes short-circuit before any provider lookup.

## License

MIT (code). Documents retain their original licenses (public domain / CC BY-SA / CC0 etc.).
