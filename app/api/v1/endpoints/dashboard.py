"""
app/api/v1/endpoints/dashboard.py

API endpoints for Business Dashboard.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_dashboard_service
from app.schemas.dashboard import DashboardStatsResponse
from app.services.dashboard import DashboardService

router = APIRouter()


@router.get(
    "/dashboard",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Business Dashboard Statistics",
    description="Calculates and returns today and month-to-date business performance statistics, payment totals, pending deliveries, and notification logs."
)
async def get_dashboard_statistics(
    db: AsyncSession = Depends(get_db),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardStatsResponse:
    return await service.get_dashboard_stats(db=db)
