"""Simple text chunking for offline RAG."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator


def chunk_text(
    text: str, chunk_size: int = 1200, overlap: int = 150, min_chars: int = 200,
) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")
    if min_chars < 0:
        raise ValueError("min_chars must not be negative")
    if not text or len(text) < min_chars:
        return []
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            for separator in ("\n\n", "\n", ". ", " "):
                position = text.rfind(separator, start + min_chars, end)
                if position != -1:
                    end = position + len(separator)
                    break
        chunk = text[start:end].strip()
        if len(chunk) >= min_chars:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def iter_text_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".text"}:
            yield path
