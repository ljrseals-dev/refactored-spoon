from pathlib import Path

import httpx
import pytest

from offline_doc_mcp.acquire import DownloadState, PausedDownload, ResumableDownloader, STOP_REQUESTED
from offline_doc_mcp.services.http import RobotsAwareHTTP


def make_http(handler):
    return RobotsAwareHTTP(
        "RefactoredSpoonBot/0.2", min_delay=0,
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


def test_download_state_persists_and_resume_uses_range(tmp_path):
    payload = b"0123456789" * 100_000
    requested_ranges = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        range_header = request.headers.get("range")
        requested_ranges.append(range_header)
        if range_header:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            return httpx.Response(206, content=payload[start:],
                                  headers={"Content-Range": f"bytes {start}-{len(payload)-1}/{len(payload)}",
                                           "ETag": '"v1"'})
        return httpx.Response(200, content=payload,
                              headers={"Content-Length": str(len(payload)), "ETag": '"v1"'})

    http = make_http(handler)
    state = DownloadState(tmp_path / "state.db")
    partial_run = ResumableDownloader(http, state, tmp_path / "quarantine",
                                       max_bytes_per_run=300_000)
    destination = tmp_path / "corpus" / "document.txt"
    try:
        with pytest.raises(PausedDownload):
            partial_run.download("fixture", "https://example.org/document.txt",
                                 destination, max_bytes=len(payload))
        row = state.resumable()[0]
        assert row["state"] == "paused"
        assert row["bytes_done"] > 0
        assert row["bytes_done"] < len(payload)

        resumed = ResumableDownloader(http, state, tmp_path / "quarantine")
        assert resumed.download("fixture", "https://example.org/document.txt",
                                destination, max_bytes=len(payload)) == len(payload)
        assert destination.read_bytes() == payload
        assert any(value and value.startswith("bytes=") for value in requested_ranges)
        assert state.get(row["doc_id"])["state"] == "completed"
    finally:
        http.close()
        STOP_REQUESTED.clear()


def test_bad_checksum_quarantines_and_never_publishes(tmp_path):
    payload = b"ordinary text content " * 100

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, content=payload)

    http = make_http(handler)
    state = DownloadState(tmp_path / "state.db")
    destination = tmp_path / "corpus" / "document.txt"
    try:
        downloader = ResumableDownloader(http, state, tmp_path / "quarantine")
        with pytest.raises(Exception, match="sha256 mismatch"):
            downloader.download("fixture", "https://example.org/document.txt",
                                destination, expected_sha256="0" * 64)
        row = next(iter(state.connect().execute(
            "SELECT doc_id,state FROM downloads"
        )))
        assert row[1] == "quarantined"
        assert not destination.exists()
        assert (tmp_path / "quarantine" / row[0] / "reason.txt").exists()
    finally:
        http.close()


def test_permanent_http_error_is_not_retried_without_force(tmp_path):
    hits = {"document": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        hits["document"] += 1
        return httpx.Response(404)

    http = make_http(handler)
    state = DownloadState(tmp_path / "state.db")
    destination = tmp_path / "missing.txt"
    try:
        downloader = ResumableDownloader(http, state, tmp_path / "quarantine")
        with pytest.raises(httpx.HTTPStatusError):
            downloader.download("fixture", "https://example.org/missing.txt", destination)
        with pytest.raises(RuntimeError, match="failed permanently"):
            downloader.download("fixture", "https://example.org/missing.txt", destination)
        assert hits["document"] == 1
    finally:
        http.close()


def test_downloader_checks_robots_on_redirect_target(tmp_path):
    blocked_requests = []

    def handler(request):
        if request.url.host == "source.example" and request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.host == "blocked.example" and request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        if request.url.host == "source.example" and request.url.path == "/start":
            return httpx.Response(302, headers={
                "Location": "https://blocked.example/private/document.txt"
            })
        blocked_requests.append(request)
        return httpx.Response(200, content=b"must not be downloaded")

    http = make_http(handler)
    state = DownloadState(tmp_path / "state.db")
    destination = tmp_path / "corpus" / "document.txt"
    try:
        downloader = ResumableDownloader(
            http, state, tmp_path / "quarantine", retry_max=1
        )
        with pytest.raises(PermissionError, match="robots.txt"):
            downloader.download(
                "fixture", "https://source.example/start", destination
            )
        assert blocked_requests == []
        assert not destination.exists()
    finally:
        http.close()
