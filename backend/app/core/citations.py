"""Citation parsing, validation and the groundedness heuristic (docs/ARCHITECTURE.md
section 18).

Perfect claim-to-source attribution is NOT solved. Out-of-range markers are stripped;
weak / uncited sentences are flagged, not rewritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MARKER = re.compile(r"\[\[(\d+)\]\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class CitationRecord:
    citation_index: int
    was_cited: bool
    weak: bool


@dataclass(frozen=True, slots=True)
class CitationResult:
    text: str  # answer with invalid markers stripped
    records: list[CitationRecord]
    uncited_sentences: list[str]
    invalid_markers: int


def parse_and_validate(
    answer: str,
    citation_map: dict[int, tuple[str, str]],
    *,
    weak_sentences: set[int] | None = None,
) -> CitationResult:
    """``weak_sentences`` is a set of citation indices whose sentence similarity to
    the cited chunk fell below the threshold (computed by the caller)."""

    valid = set(citation_map)
    weak_sentences = weak_sentences or set()

    invalid = 0

    def _strip(match: re.Match[str]) -> str:
        nonlocal invalid
        n = int(match.group(1))
        if n in valid:
            return match.group(0)
        invalid += 1
        return ""

    cleaned = _MARKER.sub(_strip, answer).replace("  ", " ").strip()

    cited_now = {int(m) for m in _MARKER.findall(cleaned)}
    records = [
        CitationRecord(
            citation_index=idx,
            was_cited=idx in cited_now,
            weak=idx in weak_sentences,
        )
        for idx in sorted(valid)
    ]

    uncited: list[str] = []
    for sentence in _SENTENCE.split(cleaned):
        s = sentence.strip()
        if len(s.split()) > 6 and not s.endswith("?") and not _MARKER.search(s):
            uncited.append(s)

    return CitationResult(
        text=cleaned, records=records, uncited_sentences=uncited, invalid_markers=invalid
    )


def cited_indices(answer: str) -> set[int]:
    return {int(m) for m in _MARKER.findall(answer)}


def sentences_with_markers(answer: str) -> list[tuple[str, set[int]]]:
    out: list[tuple[str, set[int]]] = []
    for sentence in _SENTENCE.split(answer):
        markers = {int(m) for m in _MARKER.findall(sentence)}
        if markers:
            out.append((_MARKER.sub("", sentence).strip(), markers))
    return out
