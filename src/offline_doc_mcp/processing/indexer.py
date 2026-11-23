"""Local SQLite FTS index for offline search."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .chunker import chunk_text, iter_text_files

MAX_LIMIT = 50
_TOKEN = re.compile(r"\w+", re.UNICODE)


def fts_query(raw: str) -> str:
    """Convert untrusted free text into an AND query of quoted FTS5 tokens."""
    return " AND ".join(f'"{token}"' for token in _TOKEN.findall(raw or ""))


class LocalIndex:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, source TEXT
                )"""
            )
            conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    doc_id UNINDEXED, chunk_index UNINDEXED, content, title, path
                )"""
            )

    def add_document(
        self, path: Path, text: str, title: str | None = None,
        source: str = "local", chunk_size: int = 1200, overlap: int = 150,
        min_chars: int = 200,
    ) -> int:
        title = title or path.stem
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap, min_chars=min_chars)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO documents(path,title,source) VALUES(?,?,?)
                   ON CONFLICT(path) DO UPDATE SET title=excluded.title, source=excluded.source""",
                (str(path), title, source),
            )
            row = conn.execute(
                "SELECT id FROM documents WHERE path=?", (str(path),)
            ).fetchone()
            if row is None:
                raise RuntimeError("Document index row was not created")
            doc_id = int(row[0])
            # FTS5 has no cascading foreign key; explicitly replace old chunks.
            conn.execute("DELETE FROM chunks WHERE path=?", (str(path),))
            for i, chunk in enumerate(chunks):
                conn.execute(
                    """INSERT INTO chunks(doc_id,chunk_index,content,title,path)
                       VALUES(?,?,?,?,?)""",
                    (doc_id, i, chunk, title, str(path)),
                )
        return len(chunks)

    def remove_documents(self, paths: list[str]) -> int:
        """Remove document rows and their FTS passages in one transaction."""
        if not paths:
            return 0
        removed = 0
        # Bound each statement to avoid SQLite variable-limit failures for
        # directories containing large numbers of stale documents.
        with self._connect() as conn:
            for start in range(0, len(paths), 500):
                batch = paths[start:start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT id FROM documents WHERE path IN ({placeholders})", batch
                ).fetchall()
                conn.execute(f"DELETE FROM chunks WHERE path IN ({placeholders})", batch)
                conn.execute(f"DELETE FROM documents WHERE path IN ({placeholders})", batch)
                removed += len(rows)
        return removed

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        safe_query = fts_query(query)
        if not safe_query:
            return []
        try:
            bounded_limit = max(1, min(int(limit), MAX_LIMIT))
        except (TypeError, ValueError):
            bounded_limit = 8
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT doc_id, chunk_index, content, title, path, rank
                   FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?""",
                (safe_query, bounded_limit),
            ).fetchall()
        return [
            {
                "doc_id": r["doc_id"],
                "chunk_index": int(r["chunk_index"]),
                "content": r["content"],
                "title": r["title"],
                "path": r["path"],
                "score": r["rank"],
            }
            for r in rows
        ]

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"documents": int(docs), "chunks": int(chunks)}


def build_index_from_dir(
    data_root: Path, db_path: Path, chunk_size: int = 1200, overlap: int = 150,
    min_chars: int = 200,
) -> LocalIndex:
    idx = LocalIndex(db_path)
    if not data_root.is_dir():
        return idx
    seen_paths: set[str] = set()
    for txt in iter_text_files(data_root):
        seen_paths.add(str(txt))
        try:
            content = txt.read_text(encoding="utf-8", errors="replace")
            idx.add_document(
                txt, content, title=txt.stem, source=str(txt),
                chunk_size=chunk_size, overlap=overlap, min_chars=min_chars,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"[index] skip {txt}: {type(exc).__name__}")

    # Reconcile only records belonging to this input tree. If the directory is
    # missing, above returns without pruning; unreadable files remain protected
    # because their paths were recorded before reading.
    root = data_root.resolve()
    with idx._connect() as conn:
        indexed_paths = [row[0] for row in conn.execute("SELECT path FROM documents")]
    stale: list[str] = []
    for stored in indexed_paths:
        try:
            candidate = Path(stored).resolve()
            if candidate == root or root in candidate.parents:
                if stored not in seen_paths:
                    stale.append(stored)
        except (OSError, RuntimeError):
            continue
    idx.remove_documents(stale)
    return idx
