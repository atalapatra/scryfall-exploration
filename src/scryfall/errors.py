"""Exceptions raised by the Scryfall client."""

from __future__ import annotations

from typing import Any


class ScryfallError(Exception):
    """Base class for all errors raised by this package."""


class ScryfallAPIError(ScryfallError):
    """Raised when Scryfall returns an ``error`` object.

    See https://scryfall.com/docs/api/errors
    """

    def __init__(
        self,
        status: int,
        code: str,
        details: str,
        *,
        type: str | None = None,
        warnings: list[str] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"[{status} {code}] {details}")
        self.status = status
        self.code = code
        self.details = details
        self.type = type
        self.warnings = warnings or []
        self.raw = raw or {}

    @classmethod
    def from_response(cls, status: int, payload: dict[str, Any]) -> "ScryfallAPIError":
        error_cls = NotFoundError if status == 404 else RateLimitError if status == 429 else cls
        return error_cls(
            status=payload.get("status", status),
            code=payload.get("code", "unknown"),
            details=payload.get("details", "No details provided"),
            type=payload.get("type"),
            warnings=payload.get("warnings"),
            raw=payload,
        )


class NotFoundError(ScryfallAPIError):
    """HTTP 404 - the requested object (or any search result) does not exist."""


class RateLimitError(ScryfallAPIError):
    """HTTP 429 - too many requests, even after retrying."""
