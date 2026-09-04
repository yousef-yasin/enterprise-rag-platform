"""Object storage adapters (docs/ARCHITECTURE.md §3.2, §5.1)."""

from __future__ import annotations

from app.config import Settings, StorageBackend
from app.core.interfaces.storage import ObjectStorage


def build_object_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend is StorageBackend.LOCAL:
        from app.infra.storage.local import LocalObjectStorage

        return LocalObjectStorage(settings.storage_local_path)

    from app.infra.storage.s3 import S3ObjectStorage

    assert settings.s3_bucket is not None
    return S3ObjectStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key.get_secret_value() if settings.s3_access_key else None,
        secret_key=settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None,
    )
