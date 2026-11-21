"""Project Gutenberg acquisition service (public domain only)."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import httpx

from .base import BaseService


class GutenbergService(BaseService):
    def acquire(self, force: bool = False) -> int:
        out = self.ensure_output_dir()
        catalog_url = self.config.get(
            "catalog_url",
            "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
        )
        max_books = int(self.config.get("max_books", 100))
        print(f"[{self.name}] fetching catalog from {catalog_url}")

        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                r = client.get(catalog_url)
                r.raise_for_status()
                text = r.text
        except Exception as exc:
            print(f"[{self.name}] catalog fetch failed: {exc}")
            return 0

        reader = csv.DictReader(io.StringIO(text))
        count = 0
        for row in reader:
            if count >= max_books:
                break
            # Very light filter – real runs should check Language, Rights, etc.
            title = row.get("Title") or row.get("title") or "unknown"
            ebook_no = row.get("Text#") or row.get("etext_no") or row.get("id")
            if not ebook_no:
                continue
            # Placeholder: write a stub metadata file.
            # Full implementation would download the actual epub/txt.
            meta_path = out / f"{ebook_no}.meta.txt"
            if meta_path.exists() and not force:
                continue
            meta_path.write_text(
                f"id={ebook_no}\ntitle={title}\nsource=gutenberg\n",
                encoding="utf-8",
            )
            count += 1

        print(f"[{self.name}] acquired metadata for {count} items → {out}")
        return count
