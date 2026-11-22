# Offline Document MCP Server

Reliable offline-first document corpus + MCP server for local LLMs.

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

# Process + index
python -m offline_doc_mcp.cli process
python -m offline_doc_mcp.cli index

# Run MCP server (stdio)
python -m offline_doc_mcp.mcp_server

# Optional local HTML UI
python -m offline_doc_mcp.html_server --port 8765
```

## Real acquisition, robots policy and attribution

The acquisition services now download source material rather than creating metadata
stubs. All source requests use HTTPS, a descriptive `RefactoredSpoonBot` User-Agent,
a per-host delay, bounded retries, redirect limits, download-size caps, and the
origin's `robots.txt`. A disallowed path is skipped; if robots policy cannot be
read (network error or server error), the downloader fails closed. It does not
spoof browser identities, bypass robots rules, or defeat authentication.

Set a contact address so source operators can identify the crawler:

```bash
export OFFLINE_DOC_CONTACT="crawler-admin@example.org"
```

This is contact metadata, not a password or API credential. Public Gutenberg,
Wikipedia REST and public Internet Archive files do not require login credentials.
The downloader does not send stored cookies or API keys. It will not fetch private,
restricted, or login-gated items.

### Download and index

```bash
# Project Gutenberg: downloads UTF-8 plain text for the configured US
# public-domain jurisdiction; confirm legal status outside the US.
offline-doc acquire --service project_gutenberg

# Internet Archive: searches the configured query, verifies a Public Domain
# or CC0 license in item metadata, and downloads a .txt file when available.
offline-doc acquire --service internet_archive_pd

# Wikipedia: provide a search phrase; saves attributed CC BY-SA extracts.
offline-doc acquire --service wikipedia_dumps --query "open source software"

# Build / refresh the FTS index, then search it.
offline-doc index
offline-doc search "document search"
python -m offline_doc_mcp.mcp_server
```

Official source links:
- [Project Gutenberg catalog](https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv)
- [Project Gutenberg terms](https://www.gutenberg.org/policy/terms_of_use.html)
- [Internet Archive advanced search](https://archive.org/advancedsearch.php)
- [Internet Archive metadata API](https://archive.org/developers/md-read.html)
- [Wikimedia dump portal](https://dumps.wikimedia.org/)
- [Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/)

Project Gutenberg's public-domain status is jurisdiction-dependent; this
configuration is explicitly limited to US public-domain use and is not a legal
determination for other countries. Internet Archive files are accepted only
when item metadata identifies a Public Domain Mark / CC0 license or explicit
public-domain rights. Wikipedia extracts retain page URLs and CC BY-SA
attribution. Sidecar JSON files preserve source/license metadata.

Only `.txt`, `.md`, and `.text` files are indexed. PDF/EPUB conversion and
multi-gigabyte Wikimedia dump mirroring are not silently attempted. A zero
download count can mean robots.txt disallowed the source, no suitable public
text was found, or the remote source was unavailable; inspect the source's
robots policy and item rights rather than bypassing them.

## Mode Isolation

See `src/offline_doc_mcp/engine/modes.py` and `engine.py`.  
Offline modes short-circuit before any provider lookup.

## License

MIT (code).  
Documents retain their original licenses (public domain / CC BY-SA / CC0 etc.).
