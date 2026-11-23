"""Answering engine with strict mode isolation and provenance."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .modes import Mode, resolve_mode

TRUTH_STATUSES = ("OFFICIAL", "CONSENSUS", "PLAUSIBLE", "SPECULATIVE", "UNKNOWN")
_STATUS_LINE = re.compile(r"^\s*TRUTH_STATUS:\s*([A-Za-z]+)\s*$", re.MULTILINE)
ArchiveSearch = Callable[[str], list[dict[str, Any]]]


@dataclass
class Answer:
    question: str
    mode: str
    answer: str
    subject: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    classical: bool = True
    truth_status: str = "UNKNOWN"
    error: str | None = None
    version: str = "0.1.0"


def make_archive_search(index: Any, limit: int = 3) -> ArchiveSearch:
    return lambda question: index.search(question, limit=limit)


def _source_label(passage: dict[str, Any]) -> str:
    label = f"{passage.get('title') or 'untitled'} ({passage.get('path') or 'unknown path'}"
    if passage.get("chunk_index") is not None:
        label += f", chunk {passage['chunk_index']}"
    return label + ")"


def _evidence(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": "archive",
            "title": item.get("title"),
            "path": item.get("path"),
            "doc_id": item.get("doc_id"),
            "chunk_index": item.get("chunk_index"),
            "text": str(item.get("content") or "")[:500],
        }
        for item in passages
    ]


def _format_passages(passages: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{i}] Source: {_source_label(item)}\n{item.get('content', '')}"
        for i, item in enumerate(passages, 1)
    )


def _split_truth_status(raw: str) -> tuple[str, str]:
    matches = list(_STATUS_LINE.finditer(raw))
    status = "UNKNOWN"
    if matches:
        candidate = matches[-1].group(1).upper()
        if candidate in TRUTH_STATUSES:
            status = candidate
    return _STATUS_LINE.sub("", raw).strip(), status


class Engine:
    def __init__(
        self,
        provider: Any = None,
        require_llm: bool = False,
        archive_search: ArchiveSearch | None = None,
    ):
        # Provider injection is explicit. There is deliberately no environment
        # key lookup or implicit provider discovery in this package.
        self._provider = provider
        self.require_llm = require_llm
        self.archive_search = archive_search

    @property
    def provider(self) -> Any:
        return self._provider

    def _retrieve(self, question: str) -> list[dict[str, Any]]:
        if self.archive_search is None:
            return []
        return list(self.archive_search(question) or [])

    def ask(self, question: str, mode: str | Mode = "CLASSICAL") -> Answer:
        mode_spec = resolve_mode(mode)
        mode_name = mode_spec.name.value
        passages = self._retrieve(question)
        evidence = _evidence(passages)
        sources = [_source_label(item) for item in passages]
        provider = self.provider if mode_spec.allows_provider else None

        if provider is not None and not passages:
            return Answer(
                question=question, mode=mode_name,
                answer="No relevant source passages were retrieved. Add or index source material before requesting a grounded answer.",
                classical=True, error="no_retrieved_context",
            )

        if provider is None:
            if mode_spec.allows_provider and self.require_llm:
                return Answer(
                    question=question, mode=mode_name,
                    answer=f"{mode_name} mode requires an explicitly supplied provider.",
                    classical=True, error="provider_required",
                )
            if not passages:
                return Answer(
                    question=question, mode=mode_name,
                    answer=(
                        "No relevant, source-bearing documents were retrieved. "
                        + (
                            "Index documents or explicitly supply a provider for this mode."
                            if mode_spec.allows_provider
                            else f"{mode_name} mode is offline-only and never calls an LLM provider; "
                                 "index more documents or use RESEARCH, AUDIT or HYBRID."
                        )
                    ),
                    classical=True,
                )
            note = "Retrieved documents (no provider supplied):\n\n" if mode_spec.allows_provider else "Retrieved documents:\n\n"
            return Answer(
                question=question, mode=mode_name,
                answer=note + _format_passages(passages),
                evidence=evidence, sources=sources, classical=True,
            )

        # RAG grounding contract: answers must be grounded in retrieved
        # passages, cite numbered markers, and acknowledge missing context.
        rag_system = (
            mode_spec.system_addendum
            + "\n\nRAG grounding requirements: Use retrieved context only. "
            "Cite supporting passages using their bracketed numbers (for example [1]). "
            "Never invent citations or unsupported facts. If context is absent or "
            "insufficient, state what is missing and ask for source material."
        )
        user = (
            f"Question: {question}\n\nRetrieved context (numbered source passages):\n"
            f"{_format_passages(passages) or '(no passages retrieved)'}"
        )
        try:
            raw = provider.complete(rag_system, user)
        except Exception as exc:
            return Answer(
                question=question, mode=mode_name,
                answer=f"The provider failed ({type(exc).__name__}); no answer was produced.",
                evidence=evidence, sources=sources, classical=False,
                error=f"provider_error: {type(exc).__name__}",
            )
        answer_text, truth_status = _split_truth_status(str(raw))
        return Answer(
            question=question, mode=mode_name, answer=answer_text,
            evidence=evidence, sources=sources, classical=False,
            truth_status=truth_status,
        )
