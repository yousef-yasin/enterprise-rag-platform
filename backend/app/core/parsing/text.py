"""Plain-text and Markdown parsing (docs/ARCHITECTURE.md §8.2)."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.models import DocumentBlock
from app.core.parsing.normalize import normalize_text


def decode_text(data: bytes) -> tuple[str, str]:
    """Return ``(text, encoding)`` using charset-normalizer's best guess."""

    from charset_normalizer import from_bytes

    match = from_bytes(data).best()
    if match is None:
        return data.decode("utf-8", errors="replace"), "utf-8"
    return str(match), match.encoding or "utf-8"


def parse_plain_text(data: bytes) -> tuple[list[DocumentBlock], str]:
    text, encoding = decode_text(data)
    text = normalize_text(text)
    blocks: list[DocumentBlock] = []
    offset = 0
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        end = offset + len(para)
        blocks.append(DocumentBlock(kind="paragraph", text=para, char_start=offset, char_end=end))
        offset = end + 1
    return blocks, encoding


def parse_markdown(data: bytes) -> tuple[list[DocumentBlock], str]:
    from markdown_it import MarkdownIt

    text, encoding = decode_text(data)
    md = MarkdownIt("commonmark", {"html": False})
    tokens = md.parse(text)

    blocks: list[DocumentBlock] = []
    offset = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            level = int(tok.tag[1])
            inline = tokens[i + 1].content if i + 1 < len(tokens) else ""
            content = normalize_text(inline)
            if content:
                end = offset + len(content)
                blocks.append(
                    DocumentBlock(
                        kind="heading", text=content, level=level, char_start=offset, char_end=end
                    )
                )
                offset = end + 1
            i += 3
            continue
        if tok.type == "fence" or tok.type == "code_block":
            content = tok.content.strip("\n")
            if content:
                end = offset + len(content)
                blocks.append(
                    DocumentBlock(kind="code", text=content, char_start=offset, char_end=end)
                )
                offset = end + 1
            i += 1
            continue
        if tok.type == "inline":
            content = normalize_text(tok.content)
            if content:
                end = offset + len(content)
                kind = "list_item" if _in_list(tokens, i) else "paragraph"
                blocks.append(
                    DocumentBlock(kind=kind, text=content, char_start=offset, char_end=end)  # type: ignore[arg-type]
                )
                offset = end + 1
        i += 1
    return blocks, encoding


def _in_list(tokens: Sequence[object], index: int) -> bool:
    depth = 0
    for tok in tokens[:index]:
        t = getattr(tok, "type", "")
        if t in {"bullet_list_open", "ordered_list_open"}:
            depth += 1
        elif t in {"bullet_list_close", "ordered_list_close"}:
            depth -= 1
    return depth > 0
