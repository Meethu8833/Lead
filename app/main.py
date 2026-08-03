"""
app/main.py

This is the main entrypoint file for the Colour Labs Photographer CRM backend application.
It initializes the FastAPI instance, manages application lifecycle events (via lifespan context),
configures CORS middleware, hooks global exception handlers, and mounts versioned API routers.
Run this file locally using a command like:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.context import audit_context

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import register_exception_handlers
from app.core.database import dispose_database_connections
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI Lifespan context manager.
    Handles startup events (pre-request phase) and shutdown events (cleanup phase).
    Using lifespan is the modern, recommended way instead of deprecated `@app.on_event("startup")`.
    """
    # 1. Startup phase
    setup_logging()  # Initialize custom logger formatters and levels
    
    # Warm up the permission cache
    from app.core.database import AsyncSessionLocal
    from app.services.employee import EmployeeService
    try:
        async with AsyncSessionLocal() as db:
            employee_service = EmployeeService()
            await employee_service.warm_cache(db)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to warm permission cache on startup: {e}")
        
    yield  # Handover to request processing loops

    
    # 2. Shutdown phase
    await dispose_database_connections()  # Safely disconnect SQLAlchemy engine connection pools


# Instantiate the FastAPI Application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade Backend API for the Photographer CRM (Colour Labs)",
    version="1.0.0",
    # Version openapi schema dynamically based on project settings prefix
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Configure Cross-Origin Resource Sharing (CORS) Middleware
# Ensures secure communication between frontend and backend hosts.
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],  # Allow all HTTP verbs (GET, POST, PUT, DELETE, etc.)
        allow_headers=["*"],  # Allow all standard request headers
    )

# Register Custom Global Exception Handlers
register_exception_handlers(app)

# Audit context middleware to populate user ID, IP address, and User Agent
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    user_id = request.headers.get("x-user-id") or request.headers.get("x-performed-by")
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    token = audit_context.set({
        "user_id": user_id,
        "ip_address": ip_address,
        "user_agent": user_agent
    })
    try:
        response = await call_next(request)
        return response
    finally:
        audit_context.reset(token)

# Register Main Router under the API version prefix (/api/v1)
app.include_router(api_router, prefix=settings.API_V1_STR)
