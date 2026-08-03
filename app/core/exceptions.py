"""
app/core/exceptions.py

This file defines the application's global exception hierarchy and custom handlers.
In production APIs, it is important to return consistent, clean, and safe error responses.
Instead of exposing raw tracebacks or database errors (which present security risks and
bad UX), this module translates standard exceptions, database exceptions, and schema
validation failures into structured, standard JSON responses.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError


logger = logging.getLogger(__name__)


class AppException(Exception):
    """
    Base class for all domain-specific application exceptions.
    """
    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: str = "An unexpected error occurred",
        error_code: Optional[str] = "INTERNAL_SERVER_ERROR",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.headers = headers
        super().__init__(detail)


class NotFoundException(AppException):
    """
    Raised when a requested resource is not found.
    """
    def __init__(self, detail: str = "Resource not found", error_code: str = "RESOURCE_NOT_FOUND") -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            error_code=error_code,
        )


class BadRequestException(AppException):
    """
    Raised when a client request contains bad syntax or invalid business parameters.
    """
    def __init__(self, detail: str = "Bad request", error_code: str = "BAD_REQUEST") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code=error_code,
        )


class ConflictException(AppException):
    """
    Raised when an optimistic locking version mismatch or state conflict occurs.
    """
    def __init__(self, detail: str = "Version conflict. The resource has been updated by another process. Please reload and try again.", error_code: str = "VERSION_CONFLICT") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code=error_code,
        )


class DatabaseException(AppException):
    """
    Raised when database operations fail to execute safely.
    """
    def __init__(self, detail: str = "Database operation failed", error_code: str = "DATABASE_ERROR") -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code=error_code,
        )


class UnauthorizedException(AppException):
    """
    Raised when credentials or token are invalid or missing.
    """
    def __init__(self, detail: str = "Unauthorized", error_code: str = "UNAUTHORIZED") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code=error_code,
        )


class ForbiddenException(AppException):
    """
    Raised when the authenticated user does not have sufficient permissions.
    """
    def __init__(self, detail: str = "Forbidden", error_code: str = "FORBIDDEN") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code=error_code,
        )


# Global Exception Handlers


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Handles custom domain exceptions, outputting a structured error payload.
    """
    logger.warning(
        "Application exception on %s: %s (Code: %s, Status: %d)",
        request.url.path,
        exc.detail,
        exc.error_code,
        exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": exc.error_code,
            "detail": exc.detail,
        },
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handles Pydantic validation errors (invalid body, query params, path parameters).
    Hides internal traceback and returns specific validation details.
    """
    logger.warning("Validation failure on %s: %s", request.url.path, exc.errors())
    
    # Format the Pydantic error list to make it cleaner for api consumers
    formatted_errors = []
    for error in exc.errors():
        loc = " -> ".join(str(x) for x in error.get("loc", []))
        formatted_errors.append({
            "field": loc,
            "issue": error.get("msg"),
            "type": error.get("type"),
        })

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error_code": "VALIDATION_ERROR",
            "detail": "Request body or query parameters failed validation.",
            "errors": formatted_errors,
        },
    )


async def db_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """
    Intercepts unhandled database errors (integrity constraints, connection timeouts)
    and hides database internals from the API response to prevent leaking vulnerabilities.
    """
    logger.error("Unhandled Database exception on %s", request.url.path, exc_info=exc)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error_code": "DATABASE_ERROR",
            "detail": "A database operation encountered a critical failure.",
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    A catch-all handler that catches any unhandled system exceptions.
    Prevents raw Python traceback crashes and returns a standard HTTP 500.
    """
    logger.critical("Unhandled critical system exception on %s", request.url.path, exc_info=exc)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "An unexpected server error occurred.",
        },
    )


async def stale_data_exception_handler(request: Request, exc: StaleDataError) -> JSONResponse:
    """
    Intercepts SQLAlchemy StaleDataError (optimistic lock fail) and returns HTTP 409 Conflict.
    """
    logger.warning("Optimistic lock conflict on %s: %s", request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "success": False,
            "error_code": "VERSION_CONFLICT",
            "detail": "The resource has been modified by another user. Please reload and try again.",
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Registers the exception handlers on the FastAPI app instance.
    Should be called inside app main.py file.
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StaleDataError, stale_data_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(SQLAlchemyError, db_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
