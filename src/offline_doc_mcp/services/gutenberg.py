"""Project Gutenberg text acquisition with rights and robots safeguards.

Gutenberg texts are generally public domain in the United States; copyright
status differs by jurisdiction. This service defaults to a US-only policy and
does not represent downloaded works as public domain worldwide.
"""
from __future__ import annotations

import csv
import io
import json
import re

import httpx

from .base import BaseService


class GutenbergService(BaseService):
    def acquire(self, force: bool = False) -> int:
        out = self.ensure_output_dir()
        catalog_url = self.config.get(
            "catalog_url",
            "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
        )
        jurisdiction = str(self.config.get("public_domain_jurisdiction", "US")).upper()
        if jurisdiction != "US":
            raise ValueError("Project Gutenberg auto-download is restricted to the configured US public-domain jurisdiction")
        max_books = max(0, min(int(self.config.get("max_books", 100)), 5000))
        max_bytes = max(1024, int(self.config.get("max_book_bytes", 25_000_000)))
        language = str(self.config.get("language", "en")).lower()
        try:
            catalog = self.http.get_text(catalog_url)
        except (httpx.HTTPError, PermissionError, ValueError) as exc:
            print(f"[{self.name}] catalog unavailable: {type(exc).__name__}")
            return 0

        reader = csv.DictReader(io.StringIO(catalog))
        count = 0
        for row in reader:
            if count >= max_books:
                break
            ebook_no = (row.get("Text#") or row.get("etext_no") or row.get("id") or "").strip()
            if not ebook_no.isdigit():
                continue
            languages = (row.get("Language") or row.get("language") or "en").lower()
            if language and language not in languages:
                continue
            title = (row.get("Title") or row.get("title") or f"Gutenberg {ebook_no}").strip()
            safe_title = re.sub(r"[^A-Za-z0-9._ -]+", "_", title)[:100].strip(" ._") or ebook_no
            destination = out / f"{ebook_no}-{safe_title}.txt"
            if destination.exists() and not force:
                continue

            candidates = [
                f"https://www.gutenberg.org/cache/epub/{ebook_no}/pg{ebook_no}.txt.utf8",
                f"https://www.gutenberg.org/cache/epub/{ebook_no}/pg{ebook_no}.txt",
                f"https://www.gutenberg.org/files/{ebook_no}/{ebook_no}-0.txt",
                f"https://www.gutenberg.org/files/{ebook_no}/{ebook_no}.txt",
            ]
            for url in candidates:
                try:
                    size = self.http.download(url, destination, max_bytes=max_bytes)
                    metadata = destination.with_suffix(".source.json")
                    metadata.write_text(json.dumps({
                        "title": title,
                        "source": "Project Gutenberg",
                        "source_url": url,
                        "book_id": ebook_no,
                        "rights_scope": "public-domain-in-US-only",
                        "license_notice": "Verify copyright status in your jurisdiction",
                    }, ensure_ascii=False, indent=2), encoding="utf-8")
                    count += 1
                    print(f"[{self.name}] downloaded {ebook_no} ({size} bytes)")
                    break
                except (httpx.HTTPError, PermissionError, ValueError, OSError):
                    continue
        return count
