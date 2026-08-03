"""
app/services/order_item.py

This file implements the OrderItemService.
Under Clean Architecture, this file belongs to the Application Business Rules (Use Cases) layer.
It contains the core business logic and orchestrates data retrieval/persistence using the OrderItemRepository.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException

from app.models.order_item import OrderItem, ProductionStage
from app.schemas.order_item import OrderItemCreate, OrderItemUpdate
from app.repositories.order_item import OrderItemRepository
from app.repositories.product import ProductRepository
from app.repositories.order import OrderRepository


class OrderItemService:
    """
    Service layer containing business logic and orchestrating actions on OrderItems.
    """

    def __init__(
        self,
        order_item_repository: OrderItemRepository | None = None,
        product_repository: ProductRepository | None = None,
        order_repository: OrderRepository | None = None,
    ) -> None:
        self.order_item_repository = order_item_repository or OrderItemRepository()
        self.product_repository = product_repository or ProductRepository()
        self.order_repository = order_repository or OrderRepository()

    async def create_item(self, db: AsyncSession, order_id: uuid.UUID, schema: OrderItemCreate) -> OrderItem:
        """
        Adds a new OrderItem to an order.
        
        Business Rules:
        1. Verify order exists.
        2. Verify product exists and is active.
        3. Determine unit price (use catalog base_price if schema override is omitted).
        4. Validate that discount does not exceed the line gross amount.
        5. Calculate subtotal = (unit_price * quantity) - discount.
        6. Capture product snapshots: product_name, product_category.
        7. Trigger recalculation of order total_amount and balance_amount.
        """
        # 1. Verify order exists
        order = await self.order_repository.get_by_id(db, order_id)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")

        # 2. Verify product exists and is active
        product = await self.product_repository.get_by_id(db, schema.product_id)
        if not product:
            raise NotFoundException(f"Product with ID '{schema.product_id}' was not found.")
        if not product.is_active:
            raise BadRequestException(f"Product '{product.name}' is inactive and cannot be ordered.")

        # 3. Determine unit price
        unit_price = float(schema.unit_price if schema.unit_price is not None else product.base_price)

        # 4. Validate discount
        discount = float(schema.discount)
        gross_amount = unit_price * schema.quantity
        if discount > gross_amount:
            raise BadRequestException("Discount cannot exceed the gross item amount.")

        # 5. Calculate subtotal
        subtotal = gross_amount - discount

        # 6. Fallback dimensions / defaults
        album_size = schema.album_size if schema.album_size is not None else product.size

        # Create model instance
        order_item = OrderItem(
            order_id=order_id,
            product_id=schema.product_id,
            product_name=product.name,
            product_category=product.category,
            unit_price=unit_price,
            quantity=schema.quantity,
            discount=schema.discount,
            subtotal=subtotal,
            album_size=album_size,
            sheet_type=schema.sheet_type,
            cover_type=schema.cover_type,
            remarks=schema.remarks,
        )

        db_item = await self.order_item_repository.create(db, order_item)

        # 7. Recalculate order totals and status
        from app.services.order import OrderService
        order_service = OrderService(order_repository=self.order_repository)
        await order_service.recalculate_order_totals(db, order_id)
        await order_service.recalculate_order_status(db, order_id)

        # Refresh to get updated values
        await db.refresh(db_item)
        return db_item

    async def get_items_by_order(self, db: AsyncSession, order_id: uuid.UUID, skip: int = 0, limit: int = 100) -> Sequence[OrderItem]:
        """
        Retrieves all items belonging to a specific order.
        """
        order = await self.order_repository.get_by_id(db, order_id)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")
        return await self.order_item_repository.get_all_by_order_id(db, order_id, skip=skip, limit=limit)

    async def get_item_by_id(self, db: AsyncSession, id: uuid.UUID) -> OrderItem:
        """
        Retrieves a single order item by its ID.
        """
        order_item = await self.order_item_repository.get_by_id(db, id)
        if not order_item:
            raise NotFoundException(f"Order item with ID '{id}' was not found.")
        return order_item

    async def update_item(self, db: AsyncSession, id: uuid.UUID, schema: OrderItemUpdate) -> OrderItem:
        """
        Updates an existing order item.
        
        Business Rules:
        1. Recalculate subtotal if quantity, unit_price, or discount changes.
        2. Recalculate order totals after updates.
        3. Validate version for optimistic locking.
        """
        order_item = await self.order_item_repository.get_by_id(db, id)
        if not order_item:
            raise NotFoundException(f"Order item with ID '{id}' was not found.")

        # Optimistic locking check
        if schema.version is not None and order_item.version != schema.version:
            raise ConflictException("OrderItem was modified by another process. Please reload.")

        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("version", None)

        # Merging with existing values for calculation
        qty = int(update_data.get("quantity", order_item.quantity))
        price = float(update_data.get("unit_price", order_item.unit_price))
        disc = float(update_data.get("discount", order_item.discount))

        if "quantity" in update_data or "unit_price" in update_data or "discount" in update_data:
            gross = price * qty
            if disc > gross:
                raise BadRequestException("Discount cannot exceed the gross item amount.")
            update_data["subtotal"] = gross - disc
            if "unit_price" in update_data:
                update_data["unit_price"] = price
            if "discount" in update_data:
                update_data["discount"] = disc

        updated_item = await self.order_item_repository.update(db, db_obj=order_item, update_data=update_data)

        # Recalculate parent order totals and status
        from app.services.order import OrderService
        order_service = OrderService(order_repository=self.order_repository)
        await order_service.recalculate_order_totals(db, updated_item.order_id)
        await order_service.recalculate_order_status(db, updated_item.order_id)

        # Refresh
        await db.refresh(updated_item)
        return updated_item

    async def delete_item(self, db: AsyncSession, id: uuid.UUID) -> None:
        """
        Deletes an order item.
        """
        order_item = await self.order_item_repository.get_by_id(db, id)
        if not order_item:
            raise NotFoundException(f"Order item with ID '{id}' was not found.")

        order_id = order_item.order_id
        await self.order_item_repository.delete(db, db_obj=order_item)

        # Recalculate parent order totals and status
        from app.services.order import OrderService
        order_service = OrderService(order_repository=self.order_repository)
        await order_service.recalculate_order_totals(db, order_id)
        await order_service.recalculate_order_status(db, order_id)

    async def update_production_stage(
        self, db: AsyncSession, id: uuid.UUID, stage: ProductionStage, allow_backward: bool = False, version: int | None = None
    ) -> OrderItem:
        """
        Updates the production stage of an OrderItem with validation.
        
        Rules:
        - Moving backwards requires allow_backward=True.
        - Cannot skip directly from RECEIVED to READY.
        - Changing to DELIVERED sets completed_at.
        - Changing from RECEIVED sets started_at.
        - Triggers parent order overall_status recalculation.
        - Validate version for optimistic locking.
        """
        from datetime import timezone
        
        order_item = await self.order_item_repository.get_by_id(db, id)
        if not order_item:
            raise NotFoundException(f"Order item with ID '{id}' was not found.")

        # Optimistic locking check
        if version is not None and order_item.version != version:
            raise ConflictException("OrderItem was modified by another process. Please reload.")


        current = order_item.production_stage
        new = stage

        if current != new:
            # 1. Validation
            # Cancelled transition logic
            if current == ProductionStage.DELIVERED and new != ProductionStage.DELIVERED:
                if not allow_backward:
                    raise BadRequestException("Cannot move backwards from DELIVERED unless allow_backward=True")
            
            if new == ProductionStage.CANCELLED:
                if current == ProductionStage.DELIVERED:
                    raise BadRequestException("Cannot cancel a delivered item.")
            elif current == ProductionStage.CANCELLED:
                if not allow_backward:
                    raise BadRequestException("Cannot transition away from CANCELLED unless allow_backward=True")
                if new != ProductionStage.RECEIVED:
                    raise BadRequestException("From CANCELLED, can only transition back to RECEIVED first.")
            else:
                # Sequence order
                workflow_stages = [
                    ProductionStage.RECEIVED,
                    ProductionStage.DESIGNING,
                    ProductionStage.EDITING,
                    ProductionStage.COLOR_CORRECTION,
                    ProductionStage.PRINTING,
                    ProductionStage.LAMINATION,
                    ProductionStage.QUALITY_CHECK,
                    ProductionStage.PACKING,
                    ProductionStage.READY,
                    ProductionStage.DELIVERED
                ]
                
                try:
                    idx_curr = workflow_stages.index(current)
                    idx_new = workflow_stages.index(new)
                except ValueError:
                    raise BadRequestException("Invalid stage value.")
                
                # Check backward
                if idx_new < idx_curr:
                    if not allow_backward:
                        raise BadRequestException(f"Cannot transition backward from {current.value} to {new.value} unless allow_backward=True")
                # Check forward skip (strictly sequential or check for invalid RECEIVED -> READY skip)
                elif idx_new > idx_curr:
                    if current == ProductionStage.RECEIVED and new in [ProductionStage.READY, ProductionStage.DELIVERED]:
                        raise BadRequestException("Cannot skip directly from RECEIVED to READY or DELIVERED.")
                    if idx_new > idx_curr + 1:
                        raise BadRequestException(f"Invalid transition from {current.value} to {new.value}. Must follow workflow step-by-step.")

            # 2. Update timestamps
            update_data = {"production_stage": new}
            if current == ProductionStage.RECEIVED and new != ProductionStage.RECEIVED:
                update_data["started_at"] = datetime.now(timezone.utc)
            elif new == ProductionStage.RECEIVED:
                update_data["started_at"] = None

            if new == ProductionStage.DELIVERED and current != ProductionStage.DELIVERED:
                update_data["completed_at"] = datetime.now(timezone.utc)
            elif current == ProductionStage.DELIVERED and new != ProductionStage.DELIVERED:
                update_data["completed_at"] = None

            order_item = await self.order_item_repository.update(db, db_obj=order_item, update_data=update_data)

            # 3. Recalculate parent order status
            from app.services.order import OrderService
            order_service = OrderService(order_repository=self.order_repository)
            await order_service.recalculate_order_status(db, order_item.order_id)
            
        return order_item

    async def assign_employee(self, db: AsyncSession, id: uuid.UUID, employee_id: uuid.UUID | None) -> OrderItem:
        """
        Assigns an employee to the order item.
        """
        order_item = await self.order_item_repository.get_by_id(db, id)
        if not order_item:
            raise NotFoundException(f"Order item with ID '{id}' was not found.")
            
        update_data = {"assigned_employee": employee_id}
        return await self.order_item_repository.update(db, db_obj=order_item, update_data=update_data)

    async def update_production_notes(self, db: AsyncSession, id: uuid.UUID, notes: str | None) -> OrderItem:
        """
        Updates the production notes of an order item.
        """
        order_item = await self.order_item_repository.get_by_id(db, id)
        if not order_item:
            raise NotFoundException(f"Order item with ID '{id}' was not found.")
            
        update_data = {"production_notes": notes}
        return await self.order_item_repository.update(db, db_obj=order_item, update_data=update_data)

    async def get_items_by_stage(
        self, db: AsyncSession, stage: ProductionStage, skip: int = 0, limit: int = 100
    ) -> Sequence[OrderItem]:
        """
        Retrieves all items in a specific production stage.
        """
        return await self.order_item_repository.get_items_by_stage(db, stage, skip=skip, limit=limit)

    async def get_items_by_employee(
        self, db: AsyncSession, employee_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[OrderItem]:
        """
        Retrieves all items assigned to a specific employee.
        """
        return await self.order_item_repository.get_items_assigned_employee(db, employee_id, skip=skip, limit=limit)

    async def get_production_dashboard(self, db: AsyncSession) -> dict:
        """
        Returns the production metrics dashboard.
        """
        return await self.order_item_repository.production_dashboard(db)

