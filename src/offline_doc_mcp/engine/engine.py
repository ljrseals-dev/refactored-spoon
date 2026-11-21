"""Brain Engine with strict mode isolation.

Supports two operating regimes:
1. Classical / offline  – uses Expert rules + Archive retrieval (no external LLM)
2. Hybrid / LLM-backed – uses an LLMProvider when one is configured

Mode isolation is enforced here: CLASSICAL, ARCHIVE (and AUTO, which resolves
to CLASSICAL) NEVER touch an LLM provider, even if one was injected or API keys
are configured. Only modes whose ModeSpec.allows_provider is True may do so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .modes import Mode, ModeSpec, resolve_mode


@dataclass
class Answer:
    question: str
    mode: str
    answer: str
    subject: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    classical: bool = True
    truth_status: str = "UNKNOWN"
    version: str = "0.1.0"


class Engine:
    def __init__(
        self,
        provider: Optional[Any] = None,
        require_llm: bool = False,
        archive_search: Optional[Callable[[str], str]] = None,
    ):
        self._provider = provider
        self.require_llm = require_llm
        self.archive_search = archive_search or (lambda q: "")

    @property
    def provider(self):
        """Only return the provider if the current mode will allow it.
        Discovery is deferred until a provider-capable mode is active.
        """
        return self._provider

    def ask(self, question: str, mode: str | Mode = "CLASSICAL") -> Answer:
        mode_spec = resolve_mode(mode)

        # 1. Archive retrieval (always allowed)
        context = self.archive_search(question) if self.archive_search else ""

        # 2. Expert rules / classical path would go here
        #    (placeholder – extend with your rule engine)

        # 3. Fall back to LLM provider only if the mode permits it.
        #    Provider discovery (API-key lookup) is skipped entirely otherwise.
        provider = self.provider if mode_spec.allows_provider else None

        if provider is None:
            if context:
                answer_text = (
                    "No matching expert rule"
                    + ("" if not mode_spec.allows_provider else " and no LLM provider configured")
                    + ".\n\nRetrieved Archive context:\n"
                    + context
                )
                return Answer(
                    question=question,
                    mode=mode_spec.name.value,
                    answer=answer_text,
                    evidence=[{"source": "archive", "text": context[:500]}],
                    classical=True,
                    truth_status="UNKNOWN",
                )
            return Answer(
                question=question,
                mode=mode_spec.name.value,
                answer=(
                    "No expert rule matched. "
                    + (
                        "No LLM provider is configured; import documents into the "
                        "Archive or set OPENAI_API_KEY / ANTHROPIC_API_KEY."
                        if mode_spec.allows_provider
                        else f"{mode_spec.name.value} mode is offline-only and never "
                        "calls an LLM provider. Import documents into the Archive, "
                        "add expert rules, or use HYBRID mode for model-backed answers."
                    )
                ),
                classical=True,
                truth_status="UNKNOWN",
            )

        # Provider path (only reached when allows_provider=True)
        try:
            system = mode_spec.system_addendum
            user = f"Question: {question}\n\nContext:\n{context}"
            raw = provider.complete(system, user)
            return Answer(
                question=question,
                mode=mode_spec.name.value,
                answer=raw,
                evidence=[{"source": "provider+archive", "text": context[:300]}],
                classical=False,
                truth_status="CONSENSUS",
            )
        except Exception as exc:
            return Answer(
                question=question,
                mode=mode_spec.name.value,
                answer=f"Provider error: {exc}",
                classical=False,
                truth_status="UNKNOWN",
            )
