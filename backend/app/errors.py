"""Typed API errors that serialise into the contract's error envelope."""

from fastapi import HTTPException, Request

VALIDATION_ERROR = "VALIDATION_ERROR"
NOT_FOUND = "NOT_FOUND"
INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
AI_OUTPUT_INVALID = "AI_OUTPUT_INVALID"
RATE_LIMITED = "RATE_LIMITED"
INTERNAL_ERROR = "INTERNAL_ERROR"


def error_body(code: str, message: str, retryable: bool, request_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
        }
    }


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "req_unassigned"


class ApiError(HTTPException):
    """Carries a contract error code; rendered by the handler registered in main.py."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.retryable = retryable


def validation_error(message: str) -> ApiError:
    return ApiError(400, VALIDATION_ERROR, message)


def not_found(message: str) -> ApiError:
    return ApiError(404, NOT_FOUND, message)


def invalid_transition(message: str) -> ApiError:
    return ApiError(409, INVALID_STATE_TRANSITION, message)


def conflict(message: str) -> ApiError:
    """Same status as an invalid transition; used for lost idempotency races."""
    return ApiError(409, INVALID_STATE_TRANSITION, message)