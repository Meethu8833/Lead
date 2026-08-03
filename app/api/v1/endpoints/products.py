"""
app/api/v1/endpoints/products.py

This file defines the API routes (Endpoints) for the Product entity.
Under Clean Architecture, this file resides in the API Layer (Interface Adapters).
It handles parsing requests, invoking the ProductService, and returning Pydantic responses.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_product_service
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.services.product import ProductService

router = APIRouter()


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new catalog product",
    description="Registers a new reusable product in the CRM catalog. Enforces name uniqueness."
)
async def create_product(
    schema: ProductCreate,
    db: AsyncSession = Depends(get_db),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return await service.create_product(db=db, schema=schema)


@router.get(
    "",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all products",
    description="Fetches a paginated list of all catalog products."
)
async def get_products(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: ProductService = Depends(get_product_service),
) -> List[ProductResponse]:
    return await service.get_all_products(db=db, skip=skip, limit=limit)


@router.get(
    "/search",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Search catalog products",
    description="Searches catalog products using filters on name, category, and active status."
)
async def search_products(
    name: str | None = Query(None, description="Partial match for product name"),
    category: str | None = Query(None, description="Partial match for product category"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    service: ProductService = Depends(get_product_service),
) -> List[ProductResponse]:
    return await service.search_products(
        db=db, name=name, category=category, is_active=is_active, skip=skip, limit=limit
    )


@router.get(
    "/{id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a product by ID",
    description="Retrieves product details matching the given UUID."
)
async def get_product(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return await service.get_product_by_id(db=db, id=id)


@router.put(
    "/{id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a product",
    description="Updates catalog product details (e.g. price, size, status). Enforces name uniqueness rules."
)
async def update_product(
    id: uuid.UUID,
    schema: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return await service.update_product(db=db, id=id, schema=schema)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product",
    description="Deletes a product record from the catalog."
)
async def delete_product(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: ProductService = Depends(get_product_service),
) -> None:
    await service.delete_product(db=db, id=id)
