from pathlib import Path

import pytest

from offline_doc_mcp.processing.indexer import LocalIndex, fts_query, build_index_from_dir
from offline_doc_mcp.processing.chunker import chunk_text


def test_fts_query_quotes_operators_and_punctuation():
    assert fts_query('what is "ancient" navigation? OR * : -') == (
        '"what" AND "is" AND "ancient" AND "navigation" AND "OR"'
    )
    assert fts_query('*** : --') == ""


def test_indexing_same_path_replaces_old_chunks(tmp_path):
    index = LocalIndex(tmp_path / "index.db")
    path = tmp_path / "book.txt"
    first = "alpha " * 100
    second = "beta " * 100
    index.add_document(path, first, title="Book")
    before = index.stats()
    index.add_document(path, second, title="Book revised")
    after = index.stats()
    assert after["documents"] == before["documents"] == 1
    assert after["chunks"] <= before["chunks"]
    assert index.search("beta")
    assert not index.search("alpha")


def test_search_rejects_fts_operator_injection_and_bounds_limit(tmp_path):
    index = LocalIndex(tmp_path / "index.db")
    index.add_document(Path("a.txt"), "navigation " * 100)
    assert index.search('"broken', limit=5000) == []
    assert len(index.search("navigation", limit=5000)) <= 50


@pytest.mark.parametrize("chunk_size,overlap", [(0, 0), (10, 10), (10, 11), (-1, 0)])
def test_chunker_validates_window(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_text("x" * 500, chunk_size=chunk_size, overlap=overlap)


def test_chunker_rejects_minimum_larger_than_window():
    with pytest.raises(ValueError):
        chunk_text("x" * 500, chunk_size=100, overlap=10, min_chars=101)


def test_indexing_uses_requested_chunk_parameters(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    source = root / "a.txt"
    source.write_text("word " * 400, encoding="utf-8")
    index = build_index_from_dir(root, tmp_path / "db.sqlite", chunk_size=300, overlap=50, min_chars=50)
    chunks = index.search("word", limit=50)
    assert chunks
    assert all(len(chunk["content"]) <= 300 for chunk in chunks)


def test_index_refresh_removes_deleted_files_without_touching_outside_root(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    keep = root / "keep.txt"
    removed = root / "removed.txt"
    outside = tmp_path / "outside.txt"
    keep.write_text("keepword " * 100, encoding="utf-8")
    removed.write_text("goneword " * 100, encoding="utf-8")
    outside.write_text("outsideword " * 100, encoding="utf-8")
    index = LocalIndex(tmp_path / "db.sqlite")
    index.add_document(keep, keep.read_text(), chunk_size=100, overlap=10, min_chars=10)
    index.add_document(removed, removed.read_text(), chunk_size=100, overlap=10, min_chars=10)
    index.add_document(outside, outside.read_text(), chunk_size=100, overlap=10, min_chars=10)
    removed.unlink()
    refreshed = build_index_from_dir(root, tmp_path / "db.sqlite", chunk_size=100, overlap=10, min_chars=10)
    assert refreshed.search("keepword")
    assert not refreshed.search("goneword")
    assert refreshed.search("outsideword")


def test_missing_source_directory_does_not_prune_index(tmp_path):
    index = LocalIndex(tmp_path / "db.sqlite")
    index.add_document(tmp_path / "data/a.txt", "preserve " * 100)
    refreshed = build_index_from_dir(tmp_path / "missing", tmp_path / "db.sqlite")
    assert refreshed.search("preserve")


def test_directory_processing_extracts_text_and_html(tmp_path):
    from offline_doc_mcp.processing.processor import process_directory
    source = tmp_path / "source"
    output = tmp_path / "processed"
    source.mkdir()
    (source / "plain.txt").write_text("Text content", encoding="utf-8")
    (source / "page.html").write_text("<title>Heading</title><p>HTML content</p>", encoding="utf-8")
    result = process_directory(source, output)
    assert result == {"processed": 2, "skipped": 0, "errors": 0}
    assert (output / "plain.txt").read_text().strip() == "Text content"
    assert "HTML content" in (output / "page.txt").read_text()
    assert (output / "plain.json").exists()
