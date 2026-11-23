"""Local extraction and normalization of acquired documents into text files."""
from __future__ import annotations

import json
import os
from pathlib import Path

SUPPORTED = {".txt", ".md", ".text", ".html", ".htm", ".pdf", ".epub", ".docx"}


def extract_text(path: Path) -> str:
    """Extract text from supported local formats; never fetch or execute content."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".text"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        from bs4 import BeautifulSoup
        return BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser").get_text(" ", strip=True)
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        from docx import Document
        document = Document(str(path))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if suffix == ".epub":
        from ebooklib import epub, ITEM_DOCUMENT
        from bs4 import BeautifulSoup
        book = epub.read_epub(str(path))
        sections = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            text = BeautifulSoup(item.get_content(), "html.parser").get_text(" ", strip=True)
            if text:
                sections.append(text)
        return "\n\n".join(sections)
    raise ValueError(f"Unsupported file type: {suffix}")


def process_directory(source_dir: Path, output_dir: Path) -> dict[str, int]:
    """Extract supported documents to mirrored .txt files, writing atomically."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    if not source_dir.is_dir():
        return {"processed": 0, "skipped": 0, "errors": 0}
    processed = skipped = errors = 0
    output_resolved = output_dir.resolve()
    for path in source_dir.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        try:
            if output_resolved == path.resolve() or output_resolved in path.resolve().parents:
                continue
            rel = path.relative_to(source_dir)
            target_name = rel.with_suffix(".txt") if path.suffix.lower() in {".txt", ".md", ".text"} else rel.with_suffix(rel.suffix.lower() + ".txt")
            target = output_dir / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            content = extract_text(path)
            if not content.strip():
                skipped += 1
                continue
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(content.strip() + "\n", encoding="utf-8")
            os.replace(temporary, target)
            meta = target.with_suffix(".json")
            meta_tmp = meta.with_suffix(meta.suffix + ".tmp")
            meta_tmp.write_text(json.dumps({"source": str(rel), "format": path.suffix.lower()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(meta_tmp, meta)
            processed += 1
        except Exception as exc:
            # Parsing libraries raise format-specific exceptions; isolate failures
            # per file so one malformed document does not abort the batch.
            errors += 1
            print(f"[process] skip {path}: {type(exc).__name__}")
    return {"processed": processed, "skipped": skipped, "errors": errors}
