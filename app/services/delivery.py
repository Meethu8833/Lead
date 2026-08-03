"""
app/services/delivery.py

Service layer for Delivery.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import OrderStatus
from app.models.notification import NotificationType, NotificationChannel
from app.schemas.delivery import DeliveryCreate, DeliveryUpdate
from app.repositories.delivery import DeliveryRepository
from app.repositories.order import OrderRepository
from app.services.notification import NotificationService


class DeliveryService:
    def __init__(
        self,
        delivery_repository: DeliveryRepository | None = None,
        order_repository: OrderRepository | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.delivery_repository = delivery_repository or DeliveryRepository()
        self.order_repository = order_repository or OrderRepository()
        self.notification_service = notification_service or NotificationService()

    async def create_delivery(self, db: AsyncSession, order_id: uuid.UUID, schema: DeliveryCreate) -> Delivery:
        """
        Creates delivery details for an order.
        """
        try:
            order = await self.order_repository.get_by_id(db, order_id)
            if not order:
                raise NotFoundException(f"Order with ID '{order_id}' was not found.")

            # Check if delivery already exists for this order
            existing_delivery = await self.delivery_repository.get_by_order_id(db, order_id)
            if existing_delivery:
                raise BadRequestException(f"Order '{order_id}' already has a delivery record.")

            delivered_date = None
            if schema.status == DeliveryStatus.DELIVERED:
                delivered_date = datetime.now(timezone.utc)

            delivery = Delivery(
                order_id=order_id,
                delivery_method=schema.delivery_method,
                dispatch_date=schema.dispatch_date,
                expected_delivery=schema.expected_delivery,
                delivered_date=delivered_date,
                tracking_number=schema.tracking_number,
                courier_name=schema.courier_name,
                remarks=schema.remarks,
                status=schema.status,
            )

            db_delivery = await self.delivery_repository.create(db, delivery, commit=False)
            await db.flush()

            # Apply side-effects if status is DELIVERED
            if schema.status == DeliveryStatus.DELIVERED:
                await self._handle_delivered_workflow(db, order_id)

            await db.commit()
            await db.refresh(db_delivery)
            return db_delivery
        except Exception:
            await db.rollback()
            raise

    async def get_delivery_by_id(self, db: AsyncSession, id: uuid.UUID) -> Delivery:
        delivery = await self.delivery_repository.get_by_id(db, id)
        if not delivery:
            raise NotFoundException(f"Delivery with ID '{id}' was not found.")
        return delivery

    async def get_delivery_by_order(self, db: AsyncSession, order_id: uuid.UUID) -> Delivery:
        order = await self.order_repository.get_by_id(db, order_id)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")
        delivery = await self.delivery_repository.get_by_order_id(db, order_id)
        if not delivery:
            raise NotFoundException(f"Delivery record for Order '{order_id}' was not found.")
        return delivery

    async def get_all_deliveries(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Delivery]:
        return await self.delivery_repository.get_all(db, skip=skip, limit=limit)

    async def update_delivery(self, db: AsyncSession, id: uuid.UUID, schema: DeliveryUpdate) -> Delivery:
        """
        Updates delivery details.
        Handles transitions to DELIVERED, updating parent order status and logging notifications.
        """
        try:
            delivery = await self.delivery_repository.get_by_id(db, id)
            if not delivery:
                raise NotFoundException(f"Delivery with ID '{id}' was not found.")

            update_data = schema.model_dump(exclude_unset=True)

            new_status = update_data.get("status")
            old_status = delivery.status

            if new_status and new_status != old_status:
                if new_status == DeliveryStatus.DELIVERED:
                    update_data["delivered_date"] = datetime.now(timezone.utc)
                elif old_status == DeliveryStatus.DELIVERED:
                    update_data["delivered_date"] = None

            updated_delivery = await self.delivery_repository.update(db, db_obj=delivery, update_data=update_data, commit=False)
            await db.flush()

            # If status transitioned to DELIVERED, execute workflow
            if new_status == DeliveryStatus.DELIVERED and old_status != DeliveryStatus.DELIVERED:
                await self._handle_delivered_workflow(db, delivery.order_id)

            await db.commit()
            await db.refresh(updated_delivery)
            return updated_delivery
        except Exception:
            await db.rollback()
            raise

    async def delete_delivery(self, db: AsyncSession, id: uuid.UUID) -> None:
        try:
            delivery = await self.delivery_repository.get_by_id(db, id)
            if not delivery:
                raise NotFoundException(f"Delivery with ID '{id}' was not found.")
            await self.delivery_repository.delete(db, db_obj=delivery, commit=False)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def _handle_delivered_workflow(self, db: AsyncSession, order_id: uuid.UUID) -> None:
        """
        Helper method to run DELIVERED updates:
        - Update Order.status to DELIVERED.
        - Update Order.delivered_at to now.
        - Log ORDER_DELIVERED notification.
        """
        from app.services.order import OrderService
        order_service = OrderService(order_repository=OrderRepository())
        order = await order_service.get_order_by_id(db, order_id)

        # Update order status (do not commit yet)
        await order_service.update_status(db, order_id, OrderStatus.DELIVERED, commit=False)

        # Log notification (do not commit yet)
        await self.notification_service.log_notification(
            db=db,
            order_id=order_id,
            notification_type=NotificationType.ORDER_DELIVERED,
            channel=NotificationChannel.SYSTEM,
            recipient=None,
            message_body=f"Order {order.order_number} has been successfully delivered.",
            commit=False
        )
