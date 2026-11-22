"""Internet Archive public-domain / CC0 text acquisition."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from .base import BaseService


_ALLOWED_LICENSE_MARKERS = (
    "creativecommons.org/publicdomain/zero/1.0",
    "creativecommons.org/publicdomain/mark/1.0",
    "creativecommons.org/publicdomain/zero/1.0/",
    "creativecommons.org/publicdomain/mark/1.0/",
)


def _is_public_domain(metadata: dict) -> bool:
    license_url = str(metadata.get("licenseurl") or "").lower()
    rights = str(metadata.get("rights") or "").lower()
    return any(marker in license_url for marker in _ALLOWED_LICENSE_MARKERS) or (
        "public domain" in rights and "copyright" not in rights
    )


class InternetArchiveService(BaseService):
    def acquire(self, force: bool = False) -> int:
        out = self.ensure_output_dir()
        query = str(self.config.get("query", "licenseurl:(*publicdomain* OR *cc0*)"))
        max_items = max(0, min(int(self.config.get("max_items", 50)), 500))
        max_bytes = max(1024, int(self.config.get("max_file_bytes", 50_000_000)))
        endpoint = str(self.config.get("search_url", "https://archive.org/advancedsearch.php"))
        params = {
            "q": query,
            "fl[]": ["identifier", "title", "licenseurl"],
            "rows": max_items,
            "page": 1,
            "output": "json",
        }
        try:
            response = self.http.get(endpoint, params=params)
            payload = response.json()
            docs = payload.get("response", {}).get("docs", [])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            print(f"[{self.name}] search unavailable: {type(exc).__name__}")
            return 0

        count = 0
        for item in docs:
            identifier = str(item.get("identifier") or "")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", identifier):
                continue
            try:
                meta_response = self.http.get(
                    f"https://archive.org/metadata/{quote(identifier, safe='')}"
                )
                metadata = meta_response.json().get("metadata", {})
                if not _is_public_domain(metadata):
                    continue
                files = meta_response.json().get("files", [])
            except (httpx.HTTPError, ValueError, AttributeError):
                continue

            text_files = [
                f for f in files
                if isinstance(f, dict)
                and str(f.get("name", "")).lower().endswith(".txt")
                and str(f.get("name", "")).lower() not in {"__ia_thumb.jpg"}
            ]
            text_files.sort(key=lambda f: (
                0 if "djvu" in str(f.get("format", "")).lower() else 1,
                len(str(f.get("name", ""))),
            ))
            if not text_files:
                continue
            file_info = text_files[0]
            filename = str(file_info["name"])
            if filename.startswith("/") or ".." in Path(filename).parts:
                continue
            destination = out / f"{identifier}-{Path(filename).name}"
            if destination.exists() and not force:
                continue
            url = (
                f"https://archive.org/download/{quote(identifier, safe='')}/"
                f"{quote(filename, safe='/')}"
            )
            try:
                self.http.download(url, destination, max_bytes=max_bytes)
            except (httpx.HTTPError, PermissionError, ValueError, OSError):
                continue
            (destination.with_suffix(destination.suffix + ".source.json")).write_text(
                json.dumps({
                    "title": metadata.get("title") or item.get("title") or identifier,
                    "identifier": identifier,
                    "source": "Internet Archive",
                    "source_url": f"https://archive.org/details/{identifier}",
                    "file": filename,
                    "licenseurl": metadata.get("licenseurl"),
                    "rights": metadata.get("rights"),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            count += 1
        print(f"[{self.name}] downloaded {count} verified public-domain/CC0 text files")
        return count
