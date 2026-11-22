from pathlib import Path

import pytest

from offline_doc_mcp.processing.indexer import LocalIndex, fts_query
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
    assert index.search('"broken', limit=5000) == [] or index.search('"broken', limit=5000) == []
    assert len(index.search("navigation", limit=5000)) <= 50


@pytest.mark.parametrize("chunk_size,overlap", [(0, 0), (10, 10), (10, 11), (-1, 0)])
def test_chunker_validates_window(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_text("x" * 500, chunk_size=chunk_size, overlap=overlap)
