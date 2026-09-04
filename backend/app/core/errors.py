"""Application exception hierarchy (docs/ARCHITECTURE.md §31, §23.3).

Every :class:`AppError` carries a stable ``code`` (the API error-envelope enum) and
the HTTP ``status_code`` the API boundary returns. Stack traces are logged, never
serialised.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for deliberate, handled application errors."""

    code: str = "internal"
    status_code: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ValidationError(AppError):
    code = "validation_error"
    status_code = 422


class AuthError(AppError):
    code = "unauthorized"
    status_code = 401


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = 403


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class RateLimitError(AppError):
    code = "rate_limited"
    status_code = 429

    def __init__(self, message: str, *, retry_after: int = 60) -> None:
        super().__init__(message, details={"retry_after": retry_after})
        self.retry_after = retry_after


class PayloadTooLargeError(AppError):
    code = "payload_too_large"
    status_code = 413


class UnsupportedMediaTypeError(AppError):
    code = "unsupported_media_type"
    status_code = 415


class UnprocessableDocumentError(AppError):
    """Parsing failed for a known, reportable reason (docs/ARCHITECTURE.md §30.3)."""

    code = "unprocessable_document"
    status_code = 422

    def __init__(self, message: str, *, reason: str, details: dict[str, Any] | None = None) -> None:
        merged = {"reason": reason, **(details or {})}
        super().__init__(message, details=merged)
        self.reason = reason


class DependencyUnavailableError(AppError):
    """A required infrastructure dependency (Postgres / Qdrant / Redis) is unreachable."""

    code = "internal"
    status_code = 503


class ProviderError(AppError):
    code = "provider_error"
    status_code = 502


class LLMError(ProviderError):
    pass


class LLMStreamError(LLMError):
    pass


class EmbeddingError(ProviderError):
    pass


class RerankError(ProviderError):
    pass


class RetrievalError(AppError):
    code = "internal"
    status_code = 500


class IngestionError(AppError):
    code = "internal"
    status_code = 500

    def __init__(self, message: str, *, stage: str, details: dict[str, Any] | None = None) -> None:
        merged = {"stage": stage, **(details or {})}
        super().__init__(message, details=merged)
        self.stage = stage


class StorageError(AppError):
    code = "internal"
    status_code = 500
