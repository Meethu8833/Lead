"""
app/repositories/order.py

This file implements the OrderRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0) and translates database rows
into rich objects (or models) that can be consumed by the business logic (Services).
By isolating SQL statements here, we keep services free of data access technologies.
"""

import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.order import Order, OrderStatus


class OrderRepository:
    """
    Order Repository.
    Handles CRUD operations and advanced querying on the orders database table.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, order: Order, commit: bool = True) -> Order:
        """
        Persists a new Order record to the database.
        """
        db.add(order)
        if commit:
            await db.commit()
            await db.refresh(order)
        return order

    async def update(self, db: AsyncSession, db_obj: Order, update_data: dict, commit: bool = True) -> Order:
        """
        Updates an order's attributes and commits changes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Order, commit: bool = True) -> bool:
        """
        Soft deletes an order record from the database.
        Note: Checks for deletion safety (e.g. status) are handled in the Service layer.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        if commit:
            await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None, lock: bool = False) -> Order | None:
        """
        Fetches a single Order by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Order).where(Order.id == id)
        if not inc:
            query = query.where(Order.is_deleted == False)
        if lock:
            query = query.with_for_update()
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100, include_deleted: bool | None = None) -> Sequence[Order]:
        """
        Fetches all orders with pagination.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Order).offset(skip).limit(limit)
        if not inc:
            query = query.where(Order.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_by_photographer(
        self, db: AsyncSession, photographer_id: uuid.UUID, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[Order]:
        """
        Fetches all orders placed by a specific photographer with pagination.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = (
            select(Order)
            .where(Order.photographer_id == photographer_id)
            .offset(skip)
            .limit(limit)
        )
        if not inc:
            query = query.where(Order.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def search(
        self,
        db: AsyncSession,
        order_number: str | None = None,
        job_name: str | None = None,
        status: OrderStatus | None = None,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool | None = None,
    ) -> Sequence[Order]:
        """
        Searches orders using filters on order_number, job_name, and status.
        Supports case-insensitive partial matching for strings.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Order)
        filters = []
        
        if order_number:
            filters.append(Order.order_number.ilike(f"%{order_number.strip()}%"))
        if job_name:
            filters.append(Order.job_name.ilike(f"%{job_name.strip()}%"))
        if status:
            filters.append(Order.status == status)
        if not inc:
            filters.append(Order.is_deleted == False)
            
        if filters:
            query = query.where(and_(*filters))
            
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_latest_order_for_year(self, db: AsyncSession, year: int, include_deleted: bool | None = None) -> Order | None:
        """
        Fetches the latest order created in a specific calendar year.
        Used to determine the next increment value for the automatic order number generator.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = (
            select(Order)
            .where(Order.order_number.like(f"ORD-{year}-%"))
            .order_by(Order.order_number.desc())
        )
        if not inc:
            query = query.where(Order.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()


class AdminOrderRepository(OrderRepository):
    """
    Order Repository that includes soft-deleted items by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)

