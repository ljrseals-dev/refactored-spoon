"""Simple text chunking for offline RAG."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator


def chunk_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
    min_chars: int = 200,
) -> list[str]:
    if not text or len(text) < min_chars:
        return []
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        # try to break on paragraph or sentence
        if end < length:
            for sep in ("\n\n", "\n", ". ", " "):
                pos = text.rfind(sep, start + min_chars, end)
                if pos != -1:
                    end = pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if len(chunk) >= min_chars:
            chunks.append(chunk)
        start = max(end - overlap, start + 1)
        if start >= length:
            break
    return chunks


def iter_text_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".txt", ".md", ".text"}:
            yield p
