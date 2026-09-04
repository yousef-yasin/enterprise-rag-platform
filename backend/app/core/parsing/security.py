"""Parser hardening for archive-based formats (docs/ARCHITECTURE.md §30.1)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from app.core.errors import UnprocessableDocumentError


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_uncompressed_bytes: int
    max_entries: int
    max_ratio: int


def assert_safe_zip(data: bytes, limits: ArchiveLimits) -> None:
    """Reject zip bombs before any XML parsing (docs/ARCHITECTURE.md §30.1)."""

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnprocessableDocumentError("file is not a valid archive", reason="corrupt") from exc

    infos = zf.infolist()
    if len(infos) > limits.max_entries:
        raise UnprocessableDocumentError(
            f"archive has too many entries ({len(infos)})", reason="archive_limits"
        )

    total_uncompressed = 0
    for info in infos:
        total_uncompressed += info.file_size
        if total_uncompressed > limits.max_uncompressed_bytes:
            raise UnprocessableDocumentError(
                "archive expands beyond the allowed size", reason="archive_limits"
            )
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_ratio:
                raise UnprocessableDocumentError(
                    f"archive entry {info.filename!r} has an implausible compression ratio",
                    reason="archive_limits",
                )
