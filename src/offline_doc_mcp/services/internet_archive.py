"""Internet Archive public-domain / CC0 service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseService


class InternetArchiveService(BaseService):
    def acquire(self, force: bool = False) -> int:
        out = self.ensure_output_dir()
        query = self.config.get("query", "publicdomain")
        max_items = int(self.config.get("max_items", 50))
        print(f"[{self.name}] IA search query: {query}")
        print(f"  Max items: {max_items}")
        print(f"  Output: {out}")
        print(
            "  Full IA bulk download requires the official 'ia' CLI or careful "
            "use of the advanced search API. This stub only prepares the folder."
        )
        marker = out / "README_USE_IA_CLI.txt"
        if not marker.exists() or force:
            marker.write_text(
                "Use the official Internet Archive CLI (`ia`) or the web UI\n"
                "to download public-domain / CC0 items into this directory.\n"
                f"Suggested query: {query}\n",
                encoding="utf-8",
            )
        return 0
