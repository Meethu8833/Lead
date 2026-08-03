"""
app/services/order.py

This file implements the OrderService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases) layer.
It contains the core business logic and orchestrates data retrieval/persistence using the Repositories.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException

from app.models.order import Order, OrderStatus, PaymentStatus
from app.schemas.order import OrderCreate, OrderUpdate
from app.repositories.order import OrderRepository
from app.repositories.photographer import PhotographerRepository


class OrderService:
    """
    Service layer containing business logic and orchestrating actions on Orders.
    """

    def __init__(
        self,
        order_repository: OrderRepository | None = None,
        photographer_repository: PhotographerRepository | None = None,
    ) -> None:
        self.order_repository = order_repository or OrderRepository()
        self.photographer_repository = photographer_repository or PhotographerRepository()

    async def create_order(self, db: AsyncSession, schema: OrderCreate) -> Order:
        """
        Creates a new order.
        
        Business Rules:
        1. Verify photographer exists.
        2. Generate order_number automatically (Format: ORD-YYYY-XXXXXX, e.g. ORD-2026-000001).
        3. Automatically calculate balance_amount = total_amount - advance_paid.
        4. If status is DELIVERED, automatically set delivered_at.
        """
        # 1. Verify photographer exists
        photographer = await self.photographer_repository.get_by_id(db, schema.photographer_id)
        if not photographer:
            raise NotFoundException(f"Photographer with ID '{schema.photographer_id}' was not found.")

        # 2. Generate order_number automatically
        booking_year = schema.booking_date.year
        latest_order = await self.order_repository.get_latest_order_for_year(db, booking_year)
        
        if latest_order:
            # Extract last 6 digits of order number
            try:
                last_seq_str = latest_order.order_number.split("-")[-1]
                last_seq = int(last_seq_str)
            except (ValueError, IndexError):
                last_seq = 0
            new_seq = last_seq + 1
        else:
            new_seq = 1
            
        order_number = f"ORD-{booking_year}-{new_seq:06d}"

        # 3. Set delivered_at if status is DELIVERED
        delivered_at = None
        if schema.status == OrderStatus.DELIVERED:
            delivered_at = datetime.now(timezone.utc)

        # Create model instance
        order = Order(
            photographer_id=schema.photographer_id,
            order_number=order_number,
            job_name=schema.job_name,
            event_type=schema.event_type,
            booking_date=schema.booking_date,
            event_date=schema.event_date,
            expected_delivery_date=schema.expected_delivery_date,
            delivered_at=delivered_at,
            total_amount=0.00,
            advance_paid=schema.advance_paid,
            payment_status=PaymentStatus.PENDING,
            status=schema.status,
            customer_notes=schema.customer_notes,
            internal_notes=schema.internal_notes,
        )

        db_order = await self.order_repository.create(db, order)

        # Seed payment relationship if advance_paid > 0
        if schema.advance_paid > 0.00:
            from app.models.payment import Payment, PaymentMethod
            payment = Payment(
                order_id=db_order.id,
                amount=schema.advance_paid,
                payment_method=PaymentMethod.OTHER,
                reference_number="ADVANCE",
                remarks="Advance Payment",
                received_at=schema.booking_date
            )
            db.add(payment)
            await db.commit()
            
            # Recalculate totals and payment status immediately
            await self.recalculate_order_totals(db, db_order.id)
            await db.refresh(db_order)

        return db_order

    async def get_order_by_id(self, db: AsyncSession, id: uuid.UUID) -> Order:
        """
        Retrieves an order by ID.
        Raises NotFoundException if the order does not exist.
        """
        order = await self.order_repository.get_by_id(db, id)
        if not order:
            raise NotFoundException(f"Order with ID '{id}' was not found.")
        return order

    async def get_all_orders(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Order]:
        """
        Retrieves a paginated list of all orders.
        """
        return await self.order_repository.get_all(db, skip=skip, limit=limit)

    async def get_orders_by_photographer(
        self, db: AsyncSession, photographer_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[Order]:
        """
        Retrieves all orders placed by a specific photographer.
        """
        # Verify photographer exists first
        photographer = await self.photographer_repository.get_by_id(db, photographer_id)
        if not photographer:
            raise NotFoundException(f"Photographer with ID '{photographer_id}' was not found.")
            
        return await self.order_repository.get_by_photographer(
            db, photographer_id=photographer_id, skip=skip, limit=limit
        )

    async def search_orders(
        self,
        db: AsyncSession,
        order_number: str | None = None,
        job_name: str | None = None,
        status: OrderStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Order]:
        """
        Searches orders using filters on order_number, job_name, or status.
        """
        return await self.order_repository.search(
            db, order_number=order_number, job_name=job_name, status=status, skip=skip, limit=limit
        )

    async def update_order(self, db: AsyncSession, id: uuid.UUID, schema: OrderUpdate, commit: bool = True) -> Order:
        """
        Updates an existing order.
        
        Business Rules:
        1. If photographer_id is updated, verify it exists.
        2. Recalculate balance_amount if total_amount or advance_paid changes.
        3. If status becomes DELIVERED, automatically set delivered_at. If changed away from DELIVERED, clear it.
        4. Validate version for optimistic locking.
        """
        order = await self.order_repository.get_by_id(db, id)
        if not order:
            raise NotFoundException(f"Order with ID '{id}' was not found.")

        # Optimistic locking check
        if schema.version is not None and order.version != schema.version:
            raise ConflictException("Order was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        # 1. Verify photographer if it is being changed
        new_photographer_id = update_data.get("photographer_id")
        if new_photographer_id and new_photographer_id != order.photographer_id:
            photographer = await self.photographer_repository.get_by_id(db, new_photographer_id)
            if not photographer:
                raise NotFoundException(f"Photographer with ID '{new_photographer_id}' was not found.")

        # 2. Ensure total_amount is calculated from items, and recalculate balance_amount and payment_status
        total_amount = sum(float(item.subtotal) for item in order.items)
        update_data["total_amount"] = total_amount
        
        # Calculate balance based on current payments in DB from explicit DB query
        from app.models.payment import Payment
        from sqlalchemy import select
        payments_query = select(Payment).where(Payment.order_id == id)
        payments_result = await db.execute(payments_query)
        payments = payments_result.scalars().all()
        total_paid = sum(float(p.amount) for p in payments)
        update_data["_balance_amount"] = round(total_amount - total_paid, 2)

        if total_amount == 0.00:
            update_data["payment_status"] = PaymentStatus.PENDING
        elif total_paid <= 0.00:
            update_data["payment_status"] = PaymentStatus.PENDING
        elif total_paid < total_amount:
            update_data["payment_status"] = PaymentStatus.PARTIALLY_PAID
        elif abs(total_paid - total_amount) <= 0.001:
            update_data["payment_status"] = PaymentStatus.FULLY_PAID
        else:
            update_data["payment_status"] = PaymentStatus.OVERPAID


        # 3. Handle delivered_at logic based on status transition
        new_status = update_data.get("status")
        if new_status and new_status != order.status:
            if new_status == OrderStatus.DELIVERED:
                update_data["delivered_at"] = datetime.now(timezone.utc)
            elif order.status == OrderStatus.DELIVERED:
                update_data["delivered_at"] = None

        return await self.order_repository.update(db, db_obj=order, update_data=update_data, commit=commit)

    async def update_status(self, db: AsyncSession, id: uuid.UUID, status: OrderStatus, commit: bool = True) -> Order:
        """
        Updates only the status of an order.
        """
        update_schema = OrderUpdate(status=status)
        return await self.update_order(db=db, id=id, schema=update_schema, commit=commit)

    async def delete_order(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Deletes an order and cascades soft deletion to its items.
        
        Business Rules:
        1. Do not allow deleting orders that are already DELIVERED.
        """
        order = await self.order_repository.get_by_id(db, id)
        if not order:
            raise NotFoundException(f"Order with ID '{id}' was not found.")

        if order.status == OrderStatus.DELIVERED:
            raise BadRequestException("Cannot delete orders that are already DELIVERED.")

        # Cascade soft delete to all order items
        for item in order.items:
            item.is_deleted = True
            item.deleted_at = datetime.now(timezone.utc)
            db.add(item)

        await self.order_repository.delete(db, db_obj=order)

    async def recalculate_order_totals(self, db: AsyncSession, order_id: uuid.UUID, commit: bool = True) -> Order:
        """
        Recalculates the total_amount, balance_amount, and payment_status of an order.
        total_amount = SUM(item.subtotal)
        balance_amount is computed dynamically using payments property.
        payment_status is determined by total_paid vs total_amount.
        """
        order = await self.order_repository.get_by_id(db, order_id, lock=True)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")

        # Expire the items and payments relationships to get fresh state from DB
        db.expire(order, ['items', 'payments'])

        from app.models.order_item import OrderItem
        from sqlalchemy import select, func

        # Calculate items total
        query = select(func.sum(OrderItem.subtotal)).where(OrderItem.order_id == order_id, OrderItem.is_deleted == False)
        result = await db.execute(query)
        total = float(result.scalar() or 0.0)
        order.total_amount = round(total, 2)

        # Recalculate payment status and update the stored legacy balance_amount
        from app.models.payment import Payment
        payments_query = select(Payment).where(Payment.order_id == order_id)
        payments_result = await db.execute(payments_query)
        payments = payments_result.scalars().all()
        
        total_paid = sum(float(p.amount) for p in payments)
        
        if order.total_amount == 0.00:
            order.payment_status = PaymentStatus.PENDING
        elif total_paid <= 0.00:
            order.payment_status = PaymentStatus.PENDING
        elif total_paid < order.total_amount:
            order.payment_status = PaymentStatus.PARTIALLY_PAID
        elif abs(total_paid - float(order.total_amount)) <= 0.001:
            order.payment_status = PaymentStatus.FULLY_PAID
        else:
            order.payment_status = PaymentStatus.OVERPAID

        # Sync the stored balance field for compatibility/legacy queries
        order._balance_amount = round(order.total_amount - total_paid, 2)

        db.add(order)
        if commit:
            await db.commit()
            await db.refresh(order)
        return order

    async def recalculate_order_status(self, db: AsyncSession, order_id: uuid.UUID) -> Order:
        """
        Automatically recalculates the parent Order overall_status based on the items' production stage.
        Rules:
        - If every active item is DELIVERED -> Order = DELIVERED
        - Else -> Order status equals the lowest completed stage among remaining items.
        - If all items in the order are CANCELLED -> Order = CANCELLED.
        - If there are no items, default to RECEIVED.
        """
        order = await self.order_repository.get_by_id(db, order_id, lock=True)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")

        # Fetch items directly using select to avoid async lazy load issue
        from sqlalchemy import select
        from app.models.order_item import OrderItem
        items_result = await db.execute(
            select(OrderItem).where(OrderItem.order_id == order_id, OrderItem.is_deleted == False)
        )
        items = items_result.scalars().all()
        if not items:
            new_status = OrderStatus.RECEIVED
        else:
            # Filter non-cancelled items
            active_items = [item for item in items if item.production_stage != "CANCELLED"]
            
            if not active_items:
                # All items are CANCELLED
                new_status = OrderStatus.CANCELLED
            elif all(item.production_stage == "DELIVERED" for item in active_items):
                new_status = OrderStatus.DELIVERED
            else:
                # Get remaining active items (non-cancelled and non-delivered)
                remaining_items = [item for item in active_items if item.production_stage != "DELIVERED"]
                
                # Sequence rank for workflow stages
                stage_order = [
                    "RECEIVED",
                    "DESIGNING",
                    "EDITING",
                    "COLOR_CORRECTION",
                    "PRINTING",
                    "LAMINATION",
                    "QUALITY_CHECK",
                    "PACKING",
                    "READY"
                ]
                
                def get_stage_rank(stage_val):
                    try:
                        return stage_order.index(stage_val)
                    except ValueError:
                        return -1
                
                # Find the item with the minimum stage rank
                min_item = min(
                    remaining_items,
                    key=lambda x: get_stage_rank(x.production_stage.value if hasattr(x.production_stage, 'value') else x.production_stage)
                )
                min_stage_str = min_item.production_stage.value if hasattr(min_item.production_stage, 'value') else min_item.production_stage
                new_status = OrderStatus(min_stage_str)

        if order.status != new_status:
            order.status = new_status
            if new_status == OrderStatus.DELIVERED:
                order.delivered_at = datetime.now(timezone.utc)
            else:
                order.delivered_at = None
            db.add(order)
            await db.commit()
            await db.refresh(order)
            
        return order

