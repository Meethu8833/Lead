"""
app/api/v1/endpoints/health.py

This file defines the /health diagnostics API route.
Health check endpoints are critical in production systems for monitoring uptime.
Orchestration tools (like Kubernetes, AWS ECS, or Docker Compose) call this endpoint
periodically to determine if the container is healthy. If the database connection drops,
this endpoint returns an error, triggering orchestrators to restart the container or alert operators.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_crm_service, MockCRMService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def check_health(
    db: AsyncSession = Depends(get_db),
    crm_service: MockCRMService = Depends(get_crm_service),
) -> dict:
    """
    Verifies API and PostgreSQL connection health.
    Executes a simple query 'SELECT 1' to verify database database connection pool integrity.
    Also returns mock diagnostics to show nested dependency injection.
    """
    try:
        # Execute a fast raw SQL query to verify the database connection is alive
        result = await db.execute(text("SELECT 1"))
        await db.commit()  # commit to return connection back to pool cleanly
        
        # Extract scalar value from database response (should be 1)
        db_alive = result.scalar() == 1
        
        if not db_alive:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database returned invalid response."
            )
            
        # Get diagnostics from the injected service layer dependency
        diagnostics = await crm_service.get_crm_diagnostics()

        return {
            "status": "healthy",
            "database": "connected",
            "diagnostics": diagnostics,
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error("Health check failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is unavailable or failed."
        )
