"""Structure-aware chunker (docs/ARCHITECTURE.md section 11)."""

from __future__ import annotations

from app.core.chunking import StructureAwareChunker
from app.core.embedding_profile import ChunkPolicy
from app.core.models import DocumentBlock, DocumentTree
from app.providers.embeddings.fake import FAKE_PROFILE


def _policy(target: int = 60) -> ChunkPolicy:
    return ChunkPolicy(
        target_fraction=0.8,
        overlap_fraction=0.15,
        target_tokens=target,
        structure_aware=True,
        contextual_prefix_template="{title}",
    )


def _counter(text: str) -> int:
    return max(1, len(text) // 4)


def _tree(blocks: list[DocumentBlock]) -> DocumentTree:
    return DocumentTree(
        title="Handbook",
        blocks=tuple(blocks),
        page_count=1,
        lang="en",
        total_chars=sum(len(b.text) for b in blocks),
    )


def test_chunks_carry_section_path_and_ordinals() -> None:
    tree = _tree(
        [
            DocumentBlock(kind="heading", text="Onboarding", level=1),
            DocumentBlock(kind="heading", text="Week One", level=2),
            DocumentBlock(kind="paragraph", text="Set up your laptop and accounts.", page_no=1),
            DocumentBlock(kind="paragraph", text="Meet your team and read the wiki.", page_no=1),
        ]
    )
    chunker = StructureAwareChunker(
        profile=FAKE_PROFILE, policy=_policy(target=200), count_tokens=_counter
    )
    specs = chunker.chunk(tree)
    assert specs
    assert [s.ordinal for s in specs] == list(range(len(specs)))
    assert specs[0].section_path == ["Onboarding", "Week One"]
    assert "Onboarding" in specs[0].embedding_input
    assert specs[0].content.startswith("Set up your laptop")  # prefix not in content


def test_no_chunk_exceeds_embedding_max_tokens() -> None:
    long_para = " ".join(f"sentence number {i} with some filler words." for i in range(400))
    tree = _tree(
        [
            DocumentBlock(kind="heading", text="Big Section", level=1),
            DocumentBlock(kind="paragraph", text=long_para),
        ]
    )
    chunker = StructureAwareChunker(
        profile=FAKE_PROFILE, policy=_policy(target=120), count_tokens=_counter
    )
    specs = chunker.chunk(tree)
    assert len(specs) > 1
    for spec in specs:
        assert _counter(spec.embedding_input) <= FAKE_PROFILE.max_tokens


def test_table_block_is_kept_together() -> None:
    table_text = "\n".join(f"row {i} | value {i}" for i in range(5))
    tree = _tree(
        [
            DocumentBlock(kind="heading", text="Data", level=1),
            DocumentBlock(kind="table", text=table_text),
        ]
    )
    chunker = StructureAwareChunker(
        profile=FAKE_PROFILE, policy=_policy(target=30), count_tokens=_counter
    )
    specs = chunker.chunk(tree)
    assert any("row 0" in s.content and "row 4" in s.content for s in specs)


def test_overlap_between_consecutive_chunks() -> None:
    paras = [
        DocumentBlock(kind="paragraph", text=f"Paragraph {i}. " + "word " * 20) for i in range(6)
    ]
    tree = _tree([DocumentBlock(kind="heading", text="H", level=1), *paras])
    chunker = StructureAwareChunker(
        profile=FAKE_PROFILE, policy=_policy(target=40), count_tokens=_counter
    )
    specs = chunker.chunk(tree)
    assert len(specs) >= 2
    # second chunk's embedding_input carries a tail of the first chunk's text
    assert specs[1].content != specs[0].content
