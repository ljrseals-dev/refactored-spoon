"""Optional local HTML UI for browsing the offline index."""
from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import uvicorn

from .processing.indexer import LocalIndex

app = FastAPI(title="Offline Doc MCP – Local Browser")
INDEX_DB = Path(os.environ.get("OFFLINE_DOC_INDEX", "data/index.db"))


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html><html><head><title>Offline Document Search</title>
    <style>body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    input { width: 70%; padding: 0.5rem; font-size: 1rem; } button { padding: 0.5rem 1rem; }
    .result { border: 1px solid #ddd; margin: 1rem 0; padding: 1rem; border-radius: 6px; }
    .title { font-weight: bold; } .path { color: #666; font-size: 0.85rem; }</style></head>
    <body><h1>Offline Document Search</h1><p>Fully local index – no external calls.</p>
    <form action="/search" method="get"><input name="q" placeholder="Search query..." autofocus>
    <button type="submit">Search</button></form></body></html>
    """


@app.get("/search", response_class=HTMLResponse)
def search(q: str = Query("")):
    if not q.strip():
        return HTMLResponse("<p>Empty query</p><p><a href='/'>Back</a></p>")
    results = LocalIndex(INDEX_DB).search(q, limit=12)
    parts = [f"<h1>Results for: {html.escape(q)}</h1><p><a href='/'>New search</a></p>"]
    if not results:
        parts.append("<p>No matches.</p>")
    for result in results:
        parts.append(
            "<div class='result'>"
            f"<div class='title'>{html.escape(str(result['title']))}</div>"
            f"<div class='path'>{html.escape(str(result['path']))}</div>"
            f"<pre>{html.escape(str(result['content'])[:800])}</pre></div>"
        )
    return HTMLResponse("\n".join(parts))


def main():
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
