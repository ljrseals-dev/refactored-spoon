"""Regression tests for provider isolation (adapted from original patch)."""

from __future__ import annotations

import pytest

from offline_doc_mcp.engine import Engine, MODES, Mode


OFFLINE_MODES = ["CLASSICAL", "ARCHIVE", "AUTO"]
PROVIDER_MODES = ["HYBRID", "RESEARCH", "AUDIT"]

NO_RULE_QUESTION = "zzqx unmatched gibberish question 12345"


class RecordingProvider:
    def __init__(self):
        self.calls = 0
        self.system = ""
        self.user = ""

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.system = system
        self.user = user
        return "fake answer from provider"


def test_provider_policy_matches_spec():
    assert {m.value for m, s in MODES.items() if s.allows_provider} == set(PROVIDER_MODES)
    assert not MODES[Mode.CLASSICAL].allows_provider
    assert not MODES[Mode.ARCHIVE].allows_provider


@pytest.mark.parametrize("mode", OFFLINE_MODES)
def test_offline_modes_never_call_injected_provider(mode):
    provider = RecordingProvider()
    answer = Engine(provider=provider).ask(NO_RULE_QUESTION, mode=mode)
    assert provider.calls == 0
    assert answer.classical is True
    assert answer.truth_status == "UNKNOWN"


@pytest.mark.parametrize("mode", PROVIDER_MODES)
def test_provider_modes_call_provider(mode):
    provider = RecordingProvider()
    answer = Engine(provider=provider).ask(NO_RULE_QUESTION, mode=mode)
    assert provider.calls == 1
    assert answer.classical is False


def test_provider_rag_prompt_requires_citations_and_uses_retrieved_context():
    provider = RecordingProvider()
    passages = [{"title": "Source A", "path": "source-a.txt", "doc_id": 7,
                "chunk_index": 0, "content": "The source states RAG is retrieval augmented generation."}]
    answer = Engine(provider=provider, archive_search=lambda _q: passages).ask("What is RAG?", mode="RESEARCH")
    assert provider.calls == 1
    assert "retrieved context only" in provider.system.lower()
    assert "bracketed numbers" in provider.system.lower()
    assert "[1] Source: Source A" in provider.user
    assert passages[0]["content"] in provider.user
    assert answer.evidence and answer.evidence[0]["title"] == "Source A"
