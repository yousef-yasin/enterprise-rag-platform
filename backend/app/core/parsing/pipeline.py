"""Parse dispatch + the §30.3 edge-case taxonomy (docs/ARCHITECTURE.md §8, §30)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import UnprocessableDocumentError, UnsupportedMediaTypeError
from app.core.models import DocumentBlock, DocumentTree
from app.core.parsing.docx import parse_docx
from app.core.parsing.pdf import parse_pdf
from app.core.parsing.security import ArchiveLimits
from app.core.parsing.text import parse_markdown, parse_plain_text

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".txt", ".md", ".markdown"})

_MAGIC = {
    "pdf": b"%PDF-",
    "zip": b"PK\x03\x04",
}


@dataclass(frozen=True, slots=True)
class ParseLimits:
    max_pages: int
    max_chunks_per_doc: int
    min_text_chars_per_page: int
    min_doc_chars: int
    archive_max_uncompressed_bytes: int
    archive_max_entries: int
    archive_max_ratio: int

    @property
    def archive(self) -> ArchiveLimits:
        return ArchiveLimits(
            max_uncompressed_bytes=self.archive_max_uncompressed_bytes,
            max_entries=self.archive_max_entries,
            max_ratio=self.archive_max_ratio,
        )


def _detect_kind(filename: str, data: bytes) -> str:
    lower = filename.lower()
    ext = lower[lower.rfind(".") :] if "." in lower else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMediaTypeError(f"unsupported file type: {ext or filename!r}")

    if ext == ".pdf":
        if not data.startswith(_MAGIC["pdf"]):
            raise UnsupportedMediaTypeError("file extension is .pdf but content is not a PDF")
        return "pdf"
    if ext == ".docx":
        if not data.startswith(_MAGIC["zip"]):
            raise UnsupportedMediaTypeError("file extension is .docx but content is not a DOCX")
        return "docx"
    if ext in {".md", ".markdown"}:
        return "markdown"
    return "text"


def parse_document(data: bytes, *, filename: str, limits: ParseLimits) -> DocumentTree:
    if len(data) < 1:
        raise UnprocessableDocumentError("file is empty", reason="no_text")

    kind = _detect_kind(filename, data)
    page_count: int | None = None
    lang: str | None = None

    if kind == "pdf":
        blocks, page_count = parse_pdf(data)
    elif kind == "docx":
        blocks = parse_docx(data, limits.archive)
    elif kind == "markdown":
        blocks, _enc = parse_markdown(data)
    else:
        blocks, _enc = parse_plain_text(data)

    blocks = [b for b in blocks if b.text.strip()]
    total_chars = sum(len(b.text) for b in blocks)

    if page_count is not None and page_count > limits.max_pages:
        raise UnprocessableDocumentError(
            f"document has {page_count} pages (limit {limits.max_pages}); split it first",
            reason="too_large",
        )

    if page_count and page_count > 0:
        avg_per_page = total_chars / page_count
        if avg_per_page < limits.min_text_chars_per_page:
            raise UnprocessableDocumentError(
                "no extractable text; OCR is not supported in v1",
                reason="insufficient_text",
            )

    if total_chars < limits.min_doc_chars:
        raise UnprocessableDocumentError("no extractable text", reason="no_text")

    title = _title(blocks, filename)
    lang = _detect_language(blocks)

    return DocumentTree(
        title=title,
        blocks=tuple(blocks),
        page_count=page_count,
        lang=lang,
        total_chars=total_chars,
    )


def _title(blocks: list[DocumentBlock], filename: str) -> str:
    for block in blocks:
        if block.kind == "heading":
            return block.text[:200]
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    return stem[:200] or filename


def _detect_language(blocks: list[DocumentBlock]) -> str | None:
    sample = " ".join(b.text for b in blocks[:20])[:4000]
    if not sample.strip():
        return None
    try:
        import py3langid

        lang, _score = py3langid.classify(sample)
        return str(lang)
    except Exception:  # pragma: no cover
        return None
