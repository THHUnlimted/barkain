"""Shared error response helpers.

All error responses use the format:
    {"detail": {"error": {"code": "SNAKE_CASE", "message": "...", "details": {...}}}}
"""

from fastapi import HTTPException


def make_error_detail(code: str, message: str, details: dict | None = None) -> dict:
    """Build the standard error detail dict for HTTPException."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }


def raise_http_error(
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> None:
    """Raise an HTTPException with the standard error format."""
    raise HTTPException(
        status_code=status_code,
        detail=make_error_detail(code, message, details),
    )
