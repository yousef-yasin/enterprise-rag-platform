"""PDF parsing via pypdf (docs/ARCHITECTURE.md §8.2, §30.3)."""

from __future__ import annotations

import io

from app.core.errors import UnprocessableDocumentError
from app.core.models import DocumentBlock
from app.core.parsing.normalize import normalize_text, strip_repeated_lines


def parse_pdf(data: bytes) -> tuple[list[DocumentBlock], int]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, OSError, ValueError) as exc:
        raise UnprocessableDocumentError("could not read PDF", reason="corrupt") from exc

    if reader.is_encrypted:
        # pypdf can transparently open empty-password encryption; a real password fails.
        try:
            if reader.decrypt("") == 0:  # 0 == failed
                raise UnprocessableDocumentError(
                    "PDF is password-protected; remove the password and re-upload",
                    reason="encrypted",
                )
        except NotImplementedError as exc:
            raise UnprocessableDocumentError(
                "PDF uses unsupported encryption", reason="encrypted"
            ) from exc

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")

    pages = strip_repeated_lines(pages)
    blocks: list[DocumentBlock] = []
    offset = 0
    for page_no, page_text in enumerate(pages, start=1):
        text = normalize_text(page_text)
        for para in _paragraphs(text):
            block = _classify(para, page_no, offset)
            blocks.append(block)
            offset = block.char_end + 1
    return blocks, len(pages)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _classify(para: str, page_no: int, offset: int) -> DocumentBlock:
    end = offset + len(para)
    stripped = para.strip()
    is_heading = (
        len(stripped) <= 80
        and "\n" not in stripped
        and not stripped.endswith((".", ",", ";", ":"))
        and (stripped.isupper() or stripped.istitle() or stripped[:1].isdigit())
    )
    kind = "heading" if is_heading else "paragraph"
    return DocumentBlock(
        kind=kind,  # type: ignore[arg-type]
        text=stripped,
        level=1 if is_heading else 0,
        page_no=page_no,
        char_start=offset,
        char_end=end,
    )
