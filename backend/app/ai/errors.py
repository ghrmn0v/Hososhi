from __future__ import annotations

from typing import Any


class AIError(Exception):
    """Base class for every error this layer raises.

    `code` and `http_status` are the values that go into the shared error
    envelope: {"error": {code, message, retryable, request_id}}.
    """

    code = "AI_PROVIDER_UNAVAILABLE"
    http_status = 503
    retryable = True

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_envelope(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "request_id": request_id,
            }
        }


class ProviderUnavailableError(AIError):
    code = "PROVIDER_UNAVAILABLE"
    http_status = 503
    retryable = True


class TimeoutError_(AIError):
    code = "TIMEOUT"
    http_status = 503
    retryable = True


class RateLimitedError(AIError):
    code = "RATE_LIMITED"
    http_status = 429
    retryable = True


class AuthError(AIError):
    code = "AI_PROVIDER_UNAVAILABLE"
    http_status = 503
    retryable = False


class AIOutputInvalidError(AIError):
    code = "AI_OUTPUT_INVALID"
    http_status = 422
    retryable = True


class HallucinatedEvidenceError(AIError):
    """The model cited evidence ids that do not exist in the dataset."""

    code = "AI_OUTPUT_INVALID"
    http_status = 422
    retryable = False


class ContextInsufficientError(AIError):
    """No relevant evidence was retrievable, so the question cannot be answered."""

    code = "AI_OUTPUT_INVALID"
    http_status = 422
    retryable = False


class ProviderNotConfiguredError(AIError):
    code = "PROVIDER_UNAVAILABLE"
    http_status = 503
    retryable = False