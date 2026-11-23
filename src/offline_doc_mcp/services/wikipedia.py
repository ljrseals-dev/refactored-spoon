"""Wikipedia REST API acquisition (CC BY-SA attribution retained).

This is a bounded page-search downloader, not a multi-gigabyte dump mirror.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from .base import BaseService


def _article_output_name(title: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", title)[:80].strip("._") or "article"
    suffix = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return f"{safe}-{suffix}.txt"


class WikipediaService(BaseService):
    def acquire(self, force: bool = False) -> int:
        out = self.ensure_output_dir()
        self.downloader.http = self.http
        queries = self.config.get("queries") or (
            [self.config["query"]] if self.config.get("query") else []
        )
        max_pages = max(0, min(int(self.config.get("max_pages", 20)), 100))
        count = 0
        seen: set[str] = set()
        for query in queries:
            if count >= max_pages:
                break
            try:
                response = self.http.get(
                    "https://en.wikipedia.org/w/rest.php/v1/search/page",
                    params={"q": str(query), "limit": min(20, max_pages - count)},
                )
                pages = response.json().get("pages", [])
            except (httpx.HTTPError, ValueError, AttributeError):
                continue
            for page in pages:
                if count >= max_pages:
                    break
                title = str(page.get("title") or "").strip()
                if not title or title in seen:
                    continue
                try:
                    summary = self.http.get(
                        "https://en.wikipedia.org/api/rest_v1/page/summary/"
                        + quote(title.replace(" ", "_"), safe="")
                    ).json()
                except (httpx.HTTPError, ValueError):
                    continue
                extract = str(summary.get("extract") or "").strip()
                if len(extract) < 200:
                    continue
                destination = out / _article_output_name(title)
                if destination.exists() and not force:
                    continue
                page_url = summary.get("content_urls", {}).get("desktop", {}).get("page", "")
                content = (
                    f"{title}\n\n{extract}\n\nSource: {page_url}\n"
                    "License: Creative Commons Attribution-ShareAlike (CC BY-SA); "
                    "Wikipedia contributors are the authors.\n"
                ).encode("utf-8")
                self.downloader.store_content(self.name, page_url or title, destination, content, force=force)
                (destination.with_suffix(".source.json")).write_text(
                    json.dumps({
                        "title": title,
                        "source": "Wikipedia",
                        "source_url": summary.get("content_urls", {}).get("desktop", {}).get("page"),
                        "license": "CC BY-SA",
                        "attribution": "Wikipedia contributors",
                        "revision": summary.get("revision"),
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                seen.add(title)
                count += 1
        print(f"[{self.name}] downloaded {count} attributed article extracts")
        return count
