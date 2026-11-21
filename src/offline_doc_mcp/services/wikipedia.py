"""Wikipedia dump service (CC BY-SA)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseService


class WikipediaService(BaseService):
    def acquire(self, force: bool = False) -> int:
        out = self.ensure_output_dir()
        languages = self.config.get("languages", ["en"])
        print(
            f"[{self.name}] Wikipedia dump acquisition is a manual/large-download step."
        )
        print(
            f"  Official dumps: https://dumps.wikimedia.org/"
        )
        print(
            f"  Configured languages: {languages}"
        )
        print(
            f"  Place extracted text or XML under: {out}"
        )
        # Create a marker so the pipeline knows the service was “run”
        marker = out / "README_PLACE_DUMPS_HERE.txt"
        if not marker.exists() or force:
            marker.write_text(
                "Place Wikimedia dump extracts (pages-articles) here.\n"
                "See https://dumps.wikimedia.org/ for current files.\n"
                "This service does not auto-download multi-GB dumps by default.\n",
                encoding="utf-8",
            )
        return 0
