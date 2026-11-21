"""Mode definitions with strict provider policy.

Mode isolation is enforced here: CLASSICAL, ARCHIVE (and AUTO, which resolves
to CLASSICAL) NEVER touch an LLM provider, even if one was injected or API keys
are configured. Only modes whose ModeSpec.allows_provider is True may do so.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    CLASSICAL = "CLASSICAL"
    ARCHIVE = "ARCHIVE"
    AUTO = "AUTO"
    RESEARCH = "RESEARCH"
    AUDIT = "AUDIT"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class ModeSpec:
    name: Mode
    blurb: str
    system_addendum: str
    # Policy: may this mode ever reach an external LLM provider?
    allows_provider: bool = False


MODES: dict[Mode, ModeSpec] = {
    Mode.CLASSICAL: ModeSpec(
        name=Mode.CLASSICAL,
        blurb="Strict offline classical reasoning using rules + archive only.",
        system_addendum=(
            "Answer using only expert rules and retrieved archive context. "
            "Never invent facts. Prefer UNKNOWN when evidence is insufficient."
        ),
        allows_provider=False,
    ),
    Mode.ARCHIVE: ModeSpec(
        name=Mode.ARCHIVE,
        blurb="Archive retrieval only – pure offline document lookup.",
        system_addendum=(
            "Return the most relevant archive passages. Do not synthesize "
            "beyond what the documents support. Cite sources."
        ),
        allows_provider=False,
    ),
    Mode.AUTO: ModeSpec(
        name=Mode.AUTO,
        blurb="Automatically choose the safest offline mode.",
        system_addendum="Resolve to CLASSICAL behaviour.",
        allows_provider=False,
    ),
    Mode.RESEARCH: ModeSpec(
        name=Mode.RESEARCH,
        blurb="Research mode – may use provider when available.",
        system_addendum=(
            "Distinguish documented fact, hypothesis, and open question. "
            "Cite fields or primary sources where possible."
        ),
        allows_provider=True,
    ),
    Mode.AUDIT: ModeSpec(
        name=Mode.AUDIT,
        blurb="Critical audit of claims.",
        system_addendum=(
            "Identify weaknesses, unstated assumptions, and overclaims. "
            "Be direct but constructive. Prefer conservative truth-status tags."
        ),
        allows_provider=True,
    ),
    Mode.HYBRID: ModeSpec(
        name=Mode.HYBRID,
        blurb="Hybrid classical + model contribution with full provenance.",
        system_addendum=(
            "Clearly separate contributions from classical components "
            "(rules, associative memory, statistics) from any modern model "
            "contribution. Maintain full provenance."
        ),
        allows_provider=True,
    ),
}


def resolve_mode(name: str | Mode) -> ModeSpec:
    if isinstance(name, Mode):
        mode = name
    else:
        mode = Mode(name.upper())
    if mode is Mode.AUTO:
        return MODES[Mode.CLASSICAL]
    return MODES[mode]
