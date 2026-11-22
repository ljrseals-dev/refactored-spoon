from __future__ import annotations

import json

import httpx

from offline_doc_mcp.services.gutenberg import GutenbergService
from offline_doc_mcp.services.internet_archive import InternetArchiveService
from offline_doc_mcp.services.wikipedia import WikipediaService
from offline_doc_mcp.services.http import RobotsAwareHTTP


def install_mock_http(service, handler):
    service.http.close()
    service.http = RobotsAwareHTTP(
        "RefactoredSpoonBot/0.2", min_delay=0,
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


def test_gutenberg_downloads_actual_text_and_writes_provenance(tmp_path):
    catalog = 'Text#,Title,Language\n1342,"Sample Public Domain Book",en\n'

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path.endswith("pg_catalog.csv"):
            return httpx.Response(200, text=catalog)
        if request.url.path.endswith("pg1342.txt.utf8"):
            return httpx.Response(200, content=b"A" * 500)
        return httpx.Response(404)

    service = GutenbergService("project_gutenberg", {
        "output_dir": "data/gutenberg", "catalog_url": "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
        "max_books": 1, "public_domain_jurisdiction": "US", "request_delay_seconds": 0,
    }, tmp_path)
    install_mock_http(service, handler)
    try:
        assert service.acquire() == 1
        book = next((tmp_path / "data/gutenberg").glob("*.txt"))
        assert book.read_bytes() == b"A" * 500
        provenance = json.loads(book.with_suffix(".source.json").read_text())
        assert provenance["book_id"] == "1342"
        assert provenance["rights_scope"] == "public-domain-in-US-only"
    finally:
        service.close()


def test_internet_archive_downloads_only_verified_public_domain_text(tmp_path):
    item_metadata = {
        "metadata": {
            "title": "Public Domain Work",
            "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/",
            "rights": "CC0",
        },
        "files": [{"name": "work_djvu.txt", "format": "DjVuTXT"}],
    }

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/advancedsearch.php":
            return httpx.Response(200, json={"response": {"docs": [{
                "identifier": "public-work", "title": "Public Domain Work"
            }]}})
        if request.url.path == "/metadata/public-work":
            return httpx.Response(200, json=item_metadata)
        if request.url.path == "/download/public-work/work_djvu.txt":
            return httpx.Response(200, content=b"Public domain text " * 40)
        return httpx.Response(404)

    service = InternetArchiveService("internet_archive_pd", {
        "output_dir": "data/ia", "query": "publicdomain", "max_items": 1,
        "request_delay_seconds": 0,
    }, tmp_path)
    install_mock_http(service, handler)
    try:
        assert service.acquire() == 1
        book = next((tmp_path / "data/ia").glob("*.txt"))
        assert book.stat().st_size > 200
        metadata = json.loads(book.with_suffix(".txt.source.json").read_text())
        assert metadata["licenseurl"].endswith("/zero/1.0/")
    finally:
        service.close()


def test_wikipedia_search_download_preserves_attribution(tmp_path):
    extract = "A documented encyclopedic summary. " * 12

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/w/rest.php/v1/search/page":
            return httpx.Response(200, json={"pages": [{"title": "Test topic"}]})
        if request.url.path == "/api/rest_v1/page/summary/Test_topic":
            return httpx.Response(200, json={
                "title": "Test topic", "extract": extract,
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Test_topic"}},
                "revision": "12345",
            })
        return httpx.Response(404)

    service = WikipediaService("wikipedia_dumps", {
        "output_dir": "data/wikipedia", "queries": ["test topic"],
        "max_pages": 1, "request_delay_seconds": 0,
    }, tmp_path)
    install_mock_http(service, handler)
    try:
        assert service.acquire() == 1
        article = tmp_path / "data/wikipedia/Test_topic.txt"
        assert article.exists()
        assert "CC BY-SA" in article.read_text()
        metadata = json.loads(article.with_suffix(".source.json").read_text())
        assert metadata["revision"] == "12345"
    finally:
        service.close()
