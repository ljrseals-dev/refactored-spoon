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

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
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
