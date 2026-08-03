"""
app/api/v1/endpoints/search.py

This file defines the API routes (Endpoints) for the Search feature.
Under Clean Architecture, this resides in the API Layer (Interface Adapters).
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_search_service
from app.schemas.search import GlobalSearchResponse
from app.services.search import SearchService

router = APIRouter()


@router.get(
    "",
    response_model=GlobalSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Global keyword search",
    description="Searches across photographers, orders, products, and invoices simultaneously, returning grouped results."
)
async def global_search(
    q: str = Query(..., description="The search keyword/phrase", min_length=1),
    limit: int = Query(10, description="Max results returned per category"),
    db: AsyncSession = Depends(get_db),
    service: SearchService = Depends(get_search_service),
) -> GlobalSearchResponse:
    return await service.global_search(db=db, query=q, limit=limit)
