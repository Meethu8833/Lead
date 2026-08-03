"""
app/repositories/order_item.py

This file implements the OrderItemRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0) for the OrderItem entity.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.order_item import OrderItem, ProductionStage


import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.order_item import OrderItem, ProductionStage


class OrderItemRepository:
    """
    OrderItem Repository.
    Handles CRUD operations and retrieval of line items for a specific order.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, order_item: OrderItem) -> OrderItem:
        """
        Persists a new OrderItem record to the database.
        """
        db.add(order_item)
        await db.commit()
        await db.refresh(order_item)
        return order_item

    async def update(self, db: AsyncSession, db_obj: OrderItem, update_data: dict) -> OrderItem:
        """
        Updates an order item's attributes and commits changes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: OrderItem) -> bool:
        """
        Soft deletes an order item from the database.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        await db.commit()
        return True

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None) -> OrderItem | None:
        """
        Fetches a single OrderItem by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        if inc:
            return await db.get(OrderItem, id)
        
        query = select(OrderItem).where(OrderItem.id == id, OrderItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all_by_order_id(
        self, db: AsyncSession, order_id: uuid.UUID, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[OrderItem]:
        """
        Fetches all order items belonging to a specific order with pagination.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = (
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .offset(skip)
            .limit(limit)
        )
        if not inc:
            query = query.where(OrderItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_items_by_stage(
        self, db: AsyncSession, stage: ProductionStage, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[OrderItem]:
        """
        Fetches all order items in a specific production stage.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(OrderItem).where(OrderItem.production_stage == stage).offset(skip).limit(limit)
        if not inc:
            query = query.where(OrderItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_items_assigned_employee(
        self, db: AsyncSession, employee_id: uuid.UUID, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[OrderItem]:
        """
        Fetches all order items assigned to a specific employee.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(OrderItem).where(OrderItem.assigned_employee == employee_id).offset(skip).limit(limit)
        if not inc:
            query = query.where(OrderItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_ready_for_delivery(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, include_deleted: bool | None = None
    ) -> Sequence[OrderItem]:
        """
        Fetches all order items in the READY production stage.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(OrderItem).where(OrderItem.production_stage == ProductionStage.READY).offset(skip).limit(limit)
        if not inc:
            query = query.where(OrderItem.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().all()

    async def production_dashboard(self, db: AsyncSession, include_deleted: bool | None = None) -> dict:
        """
        Aggregates production workflow metrics:
        - Items per stage
        - Items delayed
        - Items ready
        - Items delivered today
        """
        from sqlalchemy import func
        from datetime import datetime, time, timezone
        from app.models.order import Order

        inc = include_deleted if include_deleted is not None else self.include_deleted

        # 1. Items per stage (group by stage)
        stage_counts_query = select(OrderItem.production_stage, func.count(OrderItem.id))
        if not inc:
            stage_counts_query = stage_counts_query.where(OrderItem.is_deleted == False)
        stage_counts_query = stage_counts_query.group_by(OrderItem.production_stage)
        stage_counts_result = await db.execute(stage_counts_query)
        
        # Populate all stages with 0 by default
        items_per_stage = {stage.value: 0 for stage in ProductionStage}
        for stage, count in stage_counts_result.all():
            stage_str = stage.value if hasattr(stage, 'value') else stage
            items_per_stage[stage_str] = count

        # 2. Items delayed
        now = datetime.now(timezone.utc)
        delayed_query = (
            select(func.count(OrderItem.id))
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                OrderItem.production_stage != ProductionStage.DELIVERED,
                OrderItem.production_stage != ProductionStage.CANCELLED,
                Order.expected_delivery_date < now
            )
        )
        if not inc:
            delayed_query = delayed_query.where(OrderItem.is_deleted == False, Order.is_deleted == False)
        delayed_result = await db.execute(delayed_query)
        items_delayed = delayed_result.scalar() or 0

        # 3. Items ready
        ready_query = select(func.count(OrderItem.id)).where(OrderItem.production_stage == ProductionStage.READY)
        if not inc:
            ready_query = ready_query.where(OrderItem.is_deleted == False)
        ready_result = await db.execute(ready_query)
        items_ready = ready_result.scalar() or 0

        # 4. Items delivered today
        today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        delivered_today_query = (
            select(func.count(OrderItem.id))
            .where(
                OrderItem.production_stage == ProductionStage.DELIVERED,
                OrderItem.completed_at >= today_start
            )
        )
        if not inc:
            delivered_today_query = delivered_today_query.where(OrderItem.is_deleted == False)
        delivered_today_result = await db.execute(delivered_today_query)
        items_delivered_today = delivered_today_result.scalar() or 0

        return {
            "items_per_stage": items_per_stage,
            "items_delayed": items_delayed,
            "items_ready": items_ready,
            "items_delivered_today": items_delivered_today
        }


class AdminOrderItemRepository(OrderItemRepository):
    """
    OrderItem Repository that includes soft-deleted items by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)


