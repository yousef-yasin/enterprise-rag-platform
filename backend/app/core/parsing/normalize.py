"""Text normalisation applied to every parsed block (docs/ARCHITECTURE.md §8.2)."""

from __future__ import annotations

import re
import unicodedata

_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_WS = re.compile(r"[ \t]+")
_MULTI_NL = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    text = _MULTI_WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def strip_repeated_lines(pages: list[str], *, min_pages: int = 3) -> list[str]:
    """Drop lines (headers/footers) that recur on most pages."""

    if len(pages) < min_pages:
        return pages
    from collections import Counter

    counts: Counter[str] = Counter()
    for page in pages:
        for line in {ln.strip() for ln in page.splitlines() if ln.strip()}:
            counts[line] += 1
    threshold = max(min_pages, int(len(pages) * 0.6))
    boilerplate = {line for line, n in counts.items() if n >= threshold and len(line) < 120}
    if not boilerplate:
        return pages
    cleaned: list[str] = []
    for page in pages:
        kept = [ln for ln in page.splitlines() if ln.strip() not in boilerplate]
        cleaned.append("\n".join(kept))
    return cleaned
