"""Structure-aware chunker (docs/ARCHITECTURE.md §11.1-§11.3).

- token budget derived from the embedding model's ``max_tokens`` (never a fixed 512);
- packs blocks up to the target, breaking at block boundaries;
- never splits a table row; splits an over-long block by sentences;
- sentence-aligned overlap between consecutive chunks;
- prepends ``document title > section path`` before embedding (kept out of ``content``).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.core.embedding_profile import ChunkPolicy, resolved_chunk_sizing
from app.core.interfaces.embeddings import EmbeddingProfile
from app.core.models import ChunkSpec, DocumentBlock, DocumentTree

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

TokenCounter = Callable[[str], int]


class StructureAwareChunker:
    def __init__(
        self, *, profile: EmbeddingProfile, policy: ChunkPolicy, count_tokens: TokenCounter
    ) -> None:
        self._profile = profile
        self._policy = policy
        self._count = count_tokens
        self._prefix_reserve = min(
            48, max(8, count_tokens("Document Title > Section > Subsection"))
        )
        self._target, self._overlap = resolved_chunk_sizing(profile, policy, self._prefix_reserve)

    @property
    def target_tokens(self) -> int:
        return self._target

    def chunk(self, tree: DocumentTree) -> list[ChunkSpec]:
        section_stack: list[tuple[int, str]] = []
        pending: list[DocumentBlock] = []
        pending_tokens = 0
        specs: list[ChunkSpec] = []
        ordinal = 0
        carry_text = ""

        def flush() -> None:
            nonlocal pending, pending_tokens, ordinal, carry_text
            if not pending:
                return
            body = "\n\n".join(b.text for b in pending).strip()
            if carry_text:
                body = f"{carry_text}\n\n{body}"
            section_path = [name for _lvl, name in section_stack]
            spec = self._make_spec(ordinal, body, pending, section_path, tree.title)
            specs.append(spec)
            ordinal += 1
            carry_text = self._tail(body)
            pending = []
            pending_tokens = 0

        for block in tree.blocks:
            if block.kind == "heading":
                flush()
                carry_text = ""
                level = max(1, block.level)
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, block.text))
                continue

            block_tokens = self._count(block.text)
            if block_tokens > self._target and block.kind != "table":
                flush()
                carry_text = ""
                for piece in self._split_block(block):
                    section_path = [name for _lvl, name in section_stack]
                    specs.append(
                        self._make_spec(ordinal, piece.text, [piece], section_path, tree.title)
                    )
                    ordinal += 1
                continue

            if pending_tokens + block_tokens > self._target and pending:
                flush()
            pending.append(block)
            pending_tokens += block_tokens

        flush()
        return specs

    # ── helpers ──────────────────────────────────────────────────────────────
    def _make_spec(
        self,
        ordinal: int,
        content: str,
        blocks: list[DocumentBlock],
        section_path: list[str],
        title: str,
    ) -> ChunkSpec:
        prefix = self._prefix(title, section_path)
        embedding_input = f"{prefix}{content}" if prefix else content
        if self._count(embedding_input) > self._profile.max_tokens:
            content = self._truncate_to_budget(content, prefix)
            embedding_input = f"{prefix}{content}" if prefix else content

        pages = [b.page_no for b in blocks if b.page_no is not None]
        return ChunkSpec(
            ordinal=ordinal,
            content=content,
            embedding_input=embedding_input,
            token_count=self._count(embedding_input),
            section_path=list(section_path),
            page_no=pages[0] if pages else None,
            page_span_low=min(pages) if pages else None,
            page_span_high=max(pages) if pages else None,
            char_start=blocks[0].char_start,
            char_end=blocks[-1].char_end,
        )

    def _prefix(self, title: str, section_path: list[str]) -> str:
        parts = [title, *section_path[:2]]
        parts = [p for p in parts if p]
        if not parts:
            return ""
        return " > ".join(parts) + "\n\n"

    def _truncate_to_budget(self, content: str, prefix: str) -> str:
        budget = self._profile.max_tokens - self._count(prefix) - 1
        lo, hi = 0, len(content)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._count(content[:mid]) <= budget:
                lo = mid
            else:
                hi = mid - 1
        return content[:lo].rstrip()

    def _tail(self, text: str) -> str:
        if self._overlap <= 0:
            return ""
        sentences = _SENTENCE.split(text)
        tail: list[str] = []
        tokens = 0
        for sentence in reversed(sentences):
            t = self._count(sentence)
            if tokens + t > self._overlap and tail:
                break
            tail.insert(0, sentence)
            tokens += t
        return " ".join(tail).strip()

    def _split_block(self, block: DocumentBlock) -> list[DocumentBlock]:
        sentences = _SENTENCE.split(block.text)
        pieces: list[DocumentBlock] = []
        buf: list[str] = []
        buf_tokens = 0
        for sentence in sentences:
            t = self._count(sentence)
            if buf and buf_tokens + t > self._target:
                pieces.append(self._block_like(block, " ".join(buf)))
                buf, buf_tokens = [], 0
            if t > self._target:
                # a single monster sentence: hard character split
                for part in self._hard_split(sentence):
                    pieces.append(self._block_like(block, part))
                continue
            buf.append(sentence)
            buf_tokens += t
        if buf:
            pieces.append(self._block_like(block, " ".join(buf)))
        return pieces

    def _hard_split(self, text: str) -> list[str]:
        approx_chars = max(200, self._target * 4)
        return [text[i : i + approx_chars] for i in range(0, len(text), approx_chars)]

    @staticmethod
    def _block_like(block: DocumentBlock, text: str) -> DocumentBlock:
        return DocumentBlock(
            kind=block.kind,
            text=text.strip(),
            level=block.level,
            page_no=block.page_no,
            char_start=block.char_start,
            char_end=block.char_end,
        )
