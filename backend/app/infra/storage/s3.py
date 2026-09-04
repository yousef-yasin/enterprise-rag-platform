"""S3-compatible object storage (opt-in: ``pip install '.[s3]'``, docs/ARCHITECTURE.md §5.1)."""

from __future__ import annotations

import importlib.util

from app.core.errors import StorageError

_HAS_AIOBOTO3 = importlib.util.find_spec("aioboto3") is not None


class S3ObjectStorage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str | None,
        secret_key: str | None,
    ) -> None:
        if not _HAS_AIOBOTO3:
            raise StorageError("STORAGE_BACKEND=s3 requires the 's3' extra: pip install '.[s3]'")
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key

    def _session(self) -> object:
        import aioboto3

        return aioboto3.Session(
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
        )

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        async with self._session().client("s3", endpoint_url=self._endpoint_url) as client:  # type: ignore[attr-defined]
            await client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )

    async def get(self, key: str) -> bytes:
        async with self._session().client("s3", endpoint_url=self._endpoint_url) as client:  # type: ignore[attr-defined]
            try:
                resp = await client.get_object(Bucket=self._bucket, Key=key)
            except Exception as exc:
                raise StorageError(f"object {key!r} not found") from exc
            async with resp["Body"] as stream:
                data: bytes = await stream.read()
            return data

    async def delete(self, key: str) -> None:
        async with self._session().client("s3", endpoint_url=self._endpoint_url) as client:  # type: ignore[attr-defined]
            await client.delete_object(Bucket=self._bucket, Key=key)
