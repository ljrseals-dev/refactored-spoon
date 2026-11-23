from pathlib import Path

import httpx
import pytest

from offline_doc_mcp.services.http import RobotsAwareHTTP, RobotsDenied
from offline_doc_mcp.services.internet_archive import _is_public_domain


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_robots_policy_blocks_disallowed_path_and_allows_permitted_download(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, content=b"safe document")

    client = RobotsAwareHTTP("RefactoredSpoonBot/0.2", min_delay=0, client=client_for(handler))
    try:
        target = tmp_path / "download.txt"
        assert client.download("https://example.org/public.txt", target) == len(b"safe document")
        assert target.read_bytes() == b"safe document"
        with pytest.raises(RobotsDenied):
            client.download("https://example.org/private/secret.txt", tmp_path / "secret.txt")
        assert not (tmp_path / "secret.txt").exists()
        assert all(request.headers.get("user-agent") for request in requests)
    finally:
        client.close()


def test_robots_unavailable_fails_closed():
    client = RobotsAwareHTTP(
        "RefactoredSpoonBot/0.2", min_delay=0,
        client=client_for(lambda request: httpx.Response(503)),
    )
    try:
        assert client.allowed("https://example.org/document.txt") is False
        with pytest.raises(RobotsDenied):
            client.get("https://example.org/document.txt")
    finally:
        client.close()


def test_download_size_limit_and_https_only(tmp_path):
    client = RobotsAwareHTTP(
        "RefactoredSpoonBot/0.2", min_delay=0,
        client=client_for(lambda request: httpx.Response(
            200, text="User-agent: *\nAllow: /"
        ) if request.url.path == "/robots.txt" else httpx.Response(200, content=b"12345")),
    )
    try:
        with pytest.raises(ValueError):
            client.download("https://example.org/file.txt", tmp_path / "file.txt", max_bytes=4)
        with pytest.raises(ValueError):
            client.get("http://example.org/file.txt")
        with pytest.raises(ValueError, match="Credentials"):
            client.get("https://user:secret@example.org/file.txt")
    finally:
        client.close()


def test_internet_archive_requires_public_domain_or_cc0_license():
    assert _is_public_domain({"licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/"})
    assert _is_public_domain({"rights": "Public domain"})
    assert not _is_public_domain({"licenseurl": "https://creativecommons.org/licenses/by/4.0/"})
    assert not _is_public_domain({})
    assert _is_public_domain({"licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"})
    assert not _is_public_domain({"licenseurl": "https://creativecommons.org/publicdomain/zero/1.0.evil"})
    assert not _is_public_domain({"licenseurl": "https://fakecreativecommons.org/publicdomain/zero/1.0"})
    assert not _is_public_domain({"licenseurl": "http://creativecommons.org/publicdomain/zero/1.0"})
    assert not _is_public_domain({"rights": "Public domain status has not been verified"})
    assert not _is_public_domain({"rights": "copyright public domain text"})
    assert _is_public_domain({"rights": "Public  Domain"})
    assert not _is_public_domain({"licenseurl": "https://creativecommons.org:8443/publicdomain/zero/1.0/"})


def test_robots_crawl_delay_and_request_rate_are_honored(monkeypatch):
    client = RobotsAwareHTTP(
        "RefactoredSpoonBot/0.2",
        min_delay=0,
        client=client_for(lambda request: httpx.Response(
            200,
            text="User-agent: *\nCrawl-delay: 2\nRequest-rate: 1/3\nAllow: /\n",
        )),
    )
    sleeps = []
    monkeypatch.setattr("offline_doc_mcp.services.http.time.sleep", sleeps.append)
    try:
        url = "https://example.org/document.txt"
        assert client.allowed(url)
        client._throttle("https://example.org")
        client._throttle("https://example.org")
        assert sleeps and sleeps[-1] >= 2.0
    finally:
        client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/private",
        "https://service.local/private",
        "https://service.internal/private",
        "https://127.0.0.1/private",
        "https://10.0.0.2/private",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/private",
    ],
)
def test_source_urls_reject_local_and_non_public_hosts(url):
    client = RobotsAwareHTTP("RefactoredSpoonBot/0.2", min_delay=0, client=client_for(
        lambda request: httpx.Response(200, text="User-agent: *\\nAllow: /")
    ))
    try:
        with pytest.raises(ValueError, match="Local|Non-public"):
            client._origin(url)
    finally:
        client.close()


def test_get_redirects_do_not_consume_retry_budget():
    redirects = {"count": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\\nAllow: /\\n")
        if request.url.path.startswith("/hop"):
            redirects["count"] += 1
            return httpx.Response(302, headers={"Location": f"/hop{redirects['count'] + 1}"})
        if request.url.path == "/hop5":
            return httpx.Response(200, text="final response")
        return httpx.Response(404)

    client = RobotsAwareHTTP("RefactoredSpoonBot/0.2", min_delay=0, max_retries=1, client=client_for(handler))
    try:
        response = client.get("https://example.org/hop1")
        assert response.text == "final response"
        assert redirects["count"] == 4
    finally:
        client.close()
