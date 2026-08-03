"""
app/services/product.py

This file implements the ProductService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases) layer.
It contains the core business logic and orchestrates data retrieval/persistence using the ProductRepository.
"""

import uuid
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate
from app.repositories.product import ProductRepository


class ProductService:
    """
    Service layer containing business logic and orchestrating actions on Products.
    """

    def __init__(self, product_repository: ProductRepository | None = None) -> None:
        self.product_repository = product_repository or ProductRepository()

    async def create_product(self, db: AsyncSession, schema: ProductCreate) -> Product:
        """
        Creates a new product.
        
        Business Rules:
        1. Product name must be unique.
        """
        # Check uniqueness of name
        existing_product = await self.product_repository.get_by_name(db, schema.name)
        if existing_product:
            raise BadRequestException(f"Product with name '{schema.name}' already exists.")

        # Create model instance
        product = Product(
            name=schema.name,
            category=schema.category,
            size=schema.size,
            unit=schema.unit,
            description=schema.description,
            base_price=schema.base_price,
            is_active=schema.is_active,
        )

        return await self.product_repository.create(db, product)

    async def get_product_by_id(self, db: AsyncSession, id: uuid.UUID) -> Product:
        """
        Retrieves a product by ID.
        Raises NotFoundException if the product does not exist.
        """
        product = await self.product_repository.get_by_id(db, id)
        if not product:
            raise NotFoundException(f"Product with ID '{id}' was not found.")
        return product

    async def get_all_products(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Product]:
        """
        Retrieves a paginated list of all products.
        """
        return await self.product_repository.get_all(db, skip=skip, limit=limit)

    async def search_products(
        self,
        db: AsyncSession,
        name: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Product]:
        """
        Searches products using filters.
        """
        return await self.product_repository.search(
            db, name=name, category=category, is_active=is_active, skip=skip, limit=limit
        )

    async def update_product(self, db: AsyncSession, id: uuid.UUID, schema: ProductUpdate) -> Product:
        """
        Updates an existing product.
        
        Business Rules:
        1. If product name is updated, it must be unique.
        2. Validate version for optimistic locking.
        """
        product = await self.product_repository.get_by_id(db, id)
        if not product:
            raise NotFoundException(f"Product with ID '{id}' was not found.")

        # Optimistic locking check
        if schema.version is not None and product.version != schema.version:
            raise ConflictException("Product was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        # Exclude version from database updates since SQLAlchemy increments it automatically
        update_data.pop("version", None)

        # Check unique name if name is updated
        new_name = update_data.get("name")
        if new_name and new_name.lower() != product.name.lower():
            existing_product = await self.product_repository.get_by_name(db, new_name)
            if existing_product:
                raise BadRequestException(f"Product with name '{new_name}' already exists.")

        return await self.product_repository.update(db, db_obj=product, update_data=update_data)

    async def delete_product(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Deletes a product by ID.
        """
        product = await self.product_repository.get_by_id(db, id)
        if not product:
            raise NotFoundException(f"Product with ID '{id}' was not found.")

        await self.product_repository.delete(db, db_obj=product)
