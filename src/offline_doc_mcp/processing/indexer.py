"""Local SQLite FTS index for offline search."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .chunker import chunk_text, iter_text_files


class LocalIndex:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE,
                    title TEXT,
                    source TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    doc_id UNINDEXED,
                    chunk_index UNINDEXED,
                    content,
                    title,
                    path
                )
                """
            )
            conn.commit()

    def add_document(
        self,
        path: Path,
        text: str,
        title: str | None = None,
        source: str = "local",
        chunk_size: int = 1200,
        overlap: int = 150,
    ) -> int:
        title = title or path.stem
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT OR REPLACE INTO documents (path, title, source) VALUES (?, ?, ?)",
                (str(path), title, source),
            )
            doc_id = cur.lastrowid
            for i, ch in enumerate(chunks):
                conn.execute(
                    "INSERT INTO chunks (doc_id, chunk_index, content, title, path) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, i, ch, title, str(path)),
                )
            conn.commit()
        return len(chunks)

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT content, title, path, rank
                FROM chunks
                WHERE chunks MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [
            {
                "content": r["content"],
                "title": r["title"],
                "path": r["path"],
                "score": r["rank"],
            }
            for r in rows
        ]

    def stats(self) -> dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"documents": docs, "chunks": chunks}


def build_index_from_dir(
    data_root: Path,
    db_path: Path,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> LocalIndex:
    idx = LocalIndex(db_path)
    for txt in iter_text_files(data_root):
        try:
            text = txt.read_text(encoding="utf-8", errors="ignore")
            idx.add_document(txt, text, chunk_size=chunk_size, overlap=overlap)
        except Exception as exc:
            print(f"[index] skip {txt}: {exc}")
    return idx
