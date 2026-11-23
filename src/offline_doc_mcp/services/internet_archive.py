"""Internet Archive public-domain / CC0 text acquisition."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from .base import BaseService


_ALLOWED_LICENSE_PATHS = {
    "/publicdomain/zero/1.0",
    "/publicdomain/mark/1.0",
}


def _is_public_domain(metadata: dict) -> bool:
    license_url = str(metadata.get("licenseurl") or "").strip()
    parsed = urlparse(license_url)
    canonical_license = (
        parsed.scheme == "https"
        and parsed.hostname == "creativecommons.org"
        and parsed.port in (None, 443)
        and not parsed.query and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/").lower() in _ALLOWED_LICENSE_PATHS
    )
    # Free-form rights text is not reliable enough for substring checks.
    rights = re.sub(r"\\s+", " ", str(metadata.get("rights") or "").strip().lower())
    exact_rights = rights in {"public domain", "public domain mark 1.0", "cc0"}
    return canonical_license or exact_rights


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
                self.downloader.http = self.http
                self.downloader.download(self.name, url, destination, max_bytes=max_bytes, force=force)
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
