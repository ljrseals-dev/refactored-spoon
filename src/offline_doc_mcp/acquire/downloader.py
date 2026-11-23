"""Resumable, validated and atomic document downloads."""
from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import time
import zipfile
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

import httpx

from .state import DownloadState, utcnow


class PausedDownload(Exception):
    """Raised when an acquisition run is asked to stop cleanly."""


class DownloadValidationError(ValueError):
    pass


STOP_REQUESTED = Event()
RETRYABLE = {408, 429, 500, 502, 503, 504}
CHUNK_SIZE = 256 * 1024
CHECKPOINT_BYTES = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sniff(path: Path) -> str:
    with path.open("rb") as stream:
        head = stream.read(8192)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown"
    return "text" if head.strip() else "unknown"


def validate_file(path: Path, *, expected_size: int | None = None,
                  expected_sha256: str | None = None) -> list[str]:
    problems: list[str] = []
    actual_size = path.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        problems.append(f"size mismatch: {actual_size} != {expected_size}")
    if expected_sha256 and _sha256(path).lower() != expected_sha256.lower():
        problems.append("sha256 mismatch")
    kind = _sniff(path)
    if kind == "unknown":
        problems.append("unrecognized or empty file format")
    elif kind == "pdf":
        with path.open("rb") as stream:
            stream.seek(max(0, actual_size - 4096))
            if b"%%EOF" not in stream.read():
                problems.append("PDF missing %%EOF trailer")
    elif kind == "html":
        content = path.read_bytes().lower()
        if b"</html>" not in content[-8192:]:
            problems.append("HTML missing closing html tag")
    elif kind == "zip":
        try:
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    problems.append(f"corrupt ZIP entry: {bad}")
                if "mimetype" not in archive.namelist():
                    problems.append("ZIP is not an EPUB container")
        except (zipfile.BadZipFile, OSError):
            problems.append("invalid or truncated ZIP container")
    return problems


class ResumableDownloader:
    def __init__(self, http, state: DownloadState, quarantine_dir: Path,
                 *, retry_max: int = 3, max_bytes_per_run: int | None = None):
        self.http = http
        self.state = state
        self.quarantine_dir = quarantine_dir
        self.retry_max = max(0, min(retry_max, 8))
        self.max_bytes_per_run = max_bytes_per_run
        self.bytes_this_run = 0

    def download(self, source: str, url: str, destination: Path, *,
                 max_bytes: int = 25_000_000, expected_size: int | None = None,
                 expected_sha256: str | None = None, force: bool = False) -> int:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        current = url
        redirects = 0
        identity = hashlib.sha256(f"{source}\0{url}".encode()).hexdigest()
        doc_id = f"{source[:24]}-{identity[:32]}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(doc_id + ".part")
        row = self.state.ensure(doc_id=doc_id, source=source, url=url,
                                partial_path=partial, final_path=destination,
                                expected_size=expected_size, expected_sha256=expected_sha256)
        if row["state"] == "quarantined":
            raise DownloadValidationError("This source is quarantined; manual review required")
        if force:
            # Force means a fresh fetch, not merely retrying a failed state.
            partial.unlink(missing_ok=True)
            self.state.update(
                doc_id, state="pending", bytes_done=0, etag=None,
                last_modified=None, attempt_count=0, last_error=None,
                next_retry_at=None, completed_at=None,
            )
            row = self.state.get(doc_id) or row
        if row["state"] == "completed" and destination.exists() and not force:
            issues = validate_file(destination, expected_size=expected_size,
                                   expected_sha256=expected_sha256)
            if not issues:
                return destination.stat().st_size
        if row["state"] == "failed":
            if not force:
                raise RuntimeError("Download previously failed permanently; use force to retry")
            self.state.update(doc_id, state="pending", last_error=None, attempt_count=0)
        if destination.exists() and (row["state"] != "completed") and not force:
            destination.unlink()
        partial.parent.mkdir(parents=True, exist_ok=True)
        attempt = 0
        while attempt <= self.retry_max:
            if STOP_REQUESTED.is_set():
                self.state.update(doc_id, state="paused")
                raise PausedDownload()
            offset = partial.stat().st_size if partial.exists() else 0
            row = self.state.get(doc_id) or row
            if offset != int(row["bytes_done"]):
                self.state.update(doc_id, bytes_done=offset)
            origin = self.http._origin(current)
            if not self.http.allowed(current):
                self.state.update(doc_id, state="failed", last_error="robots.txt denied or unavailable")
                raise PermissionError("robots.txt denied or could not authorize this URL")
            self.http._throttle(origin)
            headers = {"User-Agent": self.http.user_agent}
            if offset:
                headers["Range"] = f"bytes={offset}-"
                validator = row.get("etag") or row.get("last_modified")
                if validator:
                    headers["If-Range"] = validator
            try:
                with self.http._client.stream("GET", current, headers=headers) as response:
                    if response.is_redirect:
                        if redirects >= 5:
                            raise DownloadValidationError("Too many redirects")
                        from urllib.parse import urljoin
                        current = urljoin(current, response.headers.get("location", ""))
                        self.http._origin(current)  # HTTPS-only validation
                        redirects += 1
                        continue
                    if response.status_code in RETRYABLE:
                        delay = self.http._retry_delay(response.headers.get("retry-after"), attempt)
                        raise _RetryableStatus(response.status_code, delay)
                    if response.status_code >= 400:
                        self.state.update(doc_id, state="failed",
                                          attempt_count=attempt + 1,
                                          last_error=f"HTTP {response.status_code}")
                        response.raise_for_status()
                    if offset and response.status_code == 200:
                        offset = 0
                        with partial.open("wb"):
                            pass
                        self.state.update(doc_id, bytes_done=0, etag=None, last_modified=None)
                    elif offset:
                        if response.status_code != 206:
                            raise DownloadValidationError(f"Unexpected range response: HTTP {response.status_code}")
                        content_range = response.headers.get("content-range", "")
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
                        range_length = (
                            int(match.group(2)) - int(match.group(1)) + 1
                            if match else -1
                        )
                        range_total = int(match.group(3)) if match and match.group(3) != "*" else None
                        response_length = response.headers.get("content-length")
                        if (
                            not match
                            or int(match.group(1)) != offset
                            or int(match.group(2)) < int(match.group(1))
                            or range_total is None
                            or int(match.group(2)) >= range_total
                            or int(match.group(2)) != range_total - 1
                            or (response_length is not None and int(response_length) != range_length)
                            or (expected_size is not None and range_total != expected_size)
                        ):
                            with partial.open("wb"):
                                pass
                            self.state.update(doc_id, bytes_done=0, etag=None, last_modified=None)
                            raise _RestartDownload("Content-Range mismatch; restarting from byte zero")
                        if expected_size is None:
                            expected_size = range_total
                    elif response.status_code != 200:
                        raise DownloadValidationError(f"Unexpected initial response: HTTP {response.status_code}")
                    length = response.headers.get("content-length")
                    if length and offset + int(length) > max_bytes:
                        raise DownloadValidationError("Download exceeds configured size limit")
                    self.state.update(doc_id, state="in_progress",
                                      started_at=row.get("started_at") or utcnow(),
                                      etag=response.headers.get("etag") or row.get("etag"),
                                      last_modified=response.headers.get("last-modified") or row.get("last_modified"),
                                      attempt_count=attempt)
                    mode = "ab" if offset else "wb"
                    since_checkpoint = 0
                    with partial.open(mode) as output:
                        for chunk in response.iter_bytes(CHUNK_SIZE):
                            if STOP_REQUESTED.is_set():
                                output.flush()
                                os.fsync(output.fileno())
                                self.state.update(doc_id, state="paused", bytes_done=partial.stat().st_size)
                                raise PausedDownload()
                            write_chunk = chunk
                            if self.max_bytes_per_run is not None:
                                budget_left = self.max_bytes_per_run - self.bytes_this_run
                                if budget_left <= 0:
                                    output.flush()
                                    os.fsync(output.fileno())
                                    self.state.update(doc_id, state="paused", bytes_done=partial.stat().st_size)
                                    raise PausedDownload()
                                if len(write_chunk) > budget_left:
                                    write_chunk = write_chunk[:budget_left]
                            if partial.stat().st_size + len(write_chunk) > max_bytes:
                                raise DownloadValidationError("Download exceeds configured size limit")
                            output.write(write_chunk)
                            self.bytes_this_run += len(write_chunk)
                            since_checkpoint += len(write_chunk)
                            if len(write_chunk) < len(chunk):
                                output.flush()
                                os.fsync(output.fileno())
                                self.state.update(doc_id, state="paused", bytes_done=partial.stat().st_size)
                                raise PausedDownload()
                            if since_checkpoint >= CHECKPOINT_BYTES:
                                output.flush()
                                os.fsync(output.fileno())
                                self.state.update(doc_id, bytes_done=partial.stat().st_size)
                                since_checkpoint = 0
                        output.flush()
                        os.fsync(output.fileno())
                    size = partial.stat().st_size
                    self.state.update(doc_id, bytes_done=size)
                    issues = validate_file(partial, expected_size=expected_size,
                                           expected_sha256=expected_sha256)
                    if issues:
                        # A known short response is resumable; other integrity
                        # failures are quarantined for explicit human review.
                        if expected_size is not None and size < expected_size and all(
                            item.startswith("size mismatch") for item in issues
                        ):
                            self.state.update(doc_id, state="paused",
                                              last_error="truncated response; resume on next run")
                            raise PausedDownload()
                        self._quarantine(doc_id, partial, issues)
                        raise DownloadValidationError("; ".join(issues))
                    os.replace(partial, destination)
                    self.state.update(doc_id, state="completed", bytes_done=size,
                                      completed_at=utcnow(), last_error=None, next_retry_at=None)
                    return size
            except _RestartDownload:
                attempt += 1
                continue
            except PausedDownload:
                raise
            except DownloadValidationError:
                raise
            except _RetryableStatus as exc:
                if attempt >= self.retry_max:
                    self.state.update(doc_id, state="failed", attempt_count=attempt + 1,
                                      last_error=f"HTTP {exc.status}")
                    raise httpx.HTTPStatusError(
                        f"retry budget exhausted: HTTP {exc.status}",
                        request=httpx.Request("GET", current),
                        response=httpx.Response(exc.status, request=httpx.Request("GET", current)),
                    )
                self.state.update(doc_id, state="paused", attempt_count=attempt + 1,
                                  bytes_done=partial.stat().st_size if partial.exists() else 0,
                                  last_error=f"retryable HTTP {exc.status}")
                time.sleep(exc.delay)
                attempt += 1
            except httpx.HTTPStatusError:
                self.state.update(doc_id, state="failed", attempt_count=attempt + 1,
                                  last_error="permanent HTTP response")
                raise
            except httpx.HTTPError as exc:
                if attempt >= self.retry_max:
                    self.state.update(doc_id, state="failed", attempt_count=attempt + 1,
                                      last_error=type(exc).__name__)
                    raise
                self.state.update(doc_id, state="paused", attempt_count=attempt + 1,
                                  bytes_done=partial.stat().st_size if partial.exists() else 0,
                                  last_error=type(exc).__name__)
                time.sleep(min(30, 2 ** attempt) * (0.5 + random.random()))
                attempt += 1
        raise RuntimeError("Download retry budget exhausted")

    def store_content(self, source: str, url: str, destination: Path, content: bytes, *, force: bool = False) -> int:
        """Atomically persist source-derived text using the download state table."""
        identity = hashlib.sha256(f"{source}\0{url}".encode()).hexdigest()
        doc_id = f"{source[:24]}-{identity[:32]}"
        partial = destination.with_name(doc_id + ".part")
        digest = hashlib.sha256(content).hexdigest()
        destination.parent.mkdir(parents=True, exist_ok=True)
        row = self.state.ensure(doc_id=doc_id, source=source, url=url,
                                partial_path=partial, final_path=destination,
                                expected_size=len(content), expected_sha256=digest)
        if row["state"] == "quarantined":
            raise DownloadValidationError("This source is quarantined; manual review required")
        if row["state"] == "quarantined":
            raise DownloadValidationError("This source is quarantined; manual review required")
        if row["state"] == "completed" and destination.exists() and not force:
            if not validate_file(destination, expected_size=len(content), expected_sha256=digest):
                return destination.stat().st_size
        if force:
            self.state.update(
                doc_id, state="pending", bytes_done=0, etag=None,
                last_modified=None, attempt_count=0, last_error=None,
                next_retry_at=None, completed_at=None,
            )
            partial.unlink(missing_ok=True)
        with partial.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        issues = validate_file(partial, expected_size=len(content), expected_sha256=digest)
        if issues:
            self._quarantine(doc_id, partial, issues)
            raise DownloadValidationError("; ".join(issues))
        os.replace(partial, destination)
        self.state.update(doc_id, state="completed", bytes_done=len(content),
                          completed_at=utcnow(), last_error=None)
        return len(content)

    def _quarantine(self, doc_id: str, partial: Path, issues: list[str]) -> None:
        target = self.quarantine_dir / doc_id
        target.mkdir(parents=True, exist_ok=True)
        if partial.exists():
            shutil.move(str(partial), str(target / "document.bad"))
        (target / "reason.txt").write_text("\n".join(issues) + "\n", encoding="utf-8")
        self.state.update(doc_id, state="quarantined", last_error="; ".join(issues))


class _RetryableStatus(Exception):
    def __init__(self, status: int, delay: float):
        self.status = status
        self.delay = delay


class _RestartDownload(Exception):
    pass
