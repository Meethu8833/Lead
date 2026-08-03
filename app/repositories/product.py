"""
app/repositories/product.py

This file implements the ProductRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0) for the Product entity.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.product import Product


class ProductRepository:
    """
    Product Repository.
    Handles CRUD operations, search, pagination, and filtering for products in the catalog.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, product: Product) -> Product:
        """
        Persists a new Product record to the database.
        """
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    async def update(self, db: AsyncSession, db_obj: Product, update_data: dict) -> Product:
        """
        Updates a product's attributes and commits changes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Product) -> bool:
        """
        Soft deletes a product from the catalog.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None) -> Product | None:
        """
        Fetches a single Product by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        if inc:
            return await db.get(Product, id)
        
        query = select(Product).where(Product.id == id, Product.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_name(self, db: AsyncSession, name: str, include_deleted: bool | None = None) -> Product | None:
        """
        Fetches a product by its unique name (exact match, case-insensitive).
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Product).where(Product.name.ilike(name.strip()))
        if not inc:
            query = query.where(Product.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100, include_deleted: bool | None = None) -> Sequence[Product]:
        """
        Fetches all products with pagination.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Product).offset(skip).limit(limit)
        if not inc:
            query = query.where(Product.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def search(
        self,
        db: AsyncSession,
        name: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool | None = None,
    ) -> Sequence[Product]:
        """
        Searches products using filters on name, category, and active status.
        Supports case-insensitive partial matching for strings.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Product)
        filters = []
        
        if name:
            filters.append(Product.name.ilike(f"%{name.strip()}%"))
        if category:
            filters.append(Product.category.ilike(f"%{category.strip()}%"))
        if is_active is not None:
            filters.append(Product.is_active == is_active)
        if not inc:
            filters.append(Product.is_deleted == False)
            
        if filters:
            query = query.where(and_(*filters))
            
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()


class AdminProductRepository(ProductRepository):
    """
    Product Repository that includes soft-deleted items by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)

