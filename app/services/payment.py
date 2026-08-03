"""
app/services/payment.py

Service layer for Payment.
"""

import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.payment import Payment, PaymentMethod
from app.models.notification import NotificationType, NotificationChannel
from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.repositories.payment import PaymentRepository
from app.repositories.order import OrderRepository
from app.services.notification import NotificationService


class PaymentService:
    def __init__(
        self,
        payment_repository: PaymentRepository | None = None,
        order_repository: OrderRepository | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.payment_repository = payment_repository or PaymentRepository()
        self.order_repository = order_repository or OrderRepository()
        self.notification_service = notification_service or NotificationService()

    async def create_payment(self, db: AsyncSession, order_id: uuid.UUID, schema: PaymentCreate) -> Payment:
        """
        Creates a new payment for an order.
        
        Business Rules:
        1. Validate amount > 0 (handled by schema).
        2. Ensure order exists and lock it using FOR UPDATE.
        3. Check for overpayment unless explicitly allowed.
        4. Recalculate order totals, balance, and payment status.
        5. Log PAYMENT_RECEIVED notification.
        6. Entire operation is transactional.
        """
        from app.models.order import Order
        try:
            # 1. Lock the order row to prevent concurrency races on calculations
            query = select(Order).where(Order.id == order_id).with_for_update()
            result = await db.execute(query)
            order = result.scalar_one_or_none()
            if not order:
                raise NotFoundException(f"Order with ID '{order_id}' was not found.")

            # 2. Query payments explicitly using async SELECT inside the lock to avoid lazy loading
            pay_query = select(Payment).where(Payment.order_id == order_id)
            pay_res = await db.execute(pay_query)
            payments = pay_res.scalars().all()

            # 3. Check for overpayment
            total_paid = sum(float(p.amount) for p in payments)
            new_total_paid = total_paid + schema.amount
            order_total = float(order.total_amount)

            if order_total > 0.00 and new_total_paid > order_total and not schema.allow_overpayment:
                raise BadRequestException(
                    f"Payment of {schema.amount} exceeds pending balance. "
                    f"Total Paid: {total_paid}, Order Total: {order_total}. Overpayment not allowed."
                )

            payment = Payment(
                order_id=order_id,
                amount=schema.amount,
                payment_method=schema.payment_method,
                reference_number=schema.reference_number,
                remarks=schema.remarks,
                received_at=schema.received_at,
            )

            # Create payment (do not commit yet)
            db_payment = await self.payment_repository.create(db, payment, commit=False)
            await db.flush()

            # Trigger order recalculation (do not commit yet)
            from app.services.order import OrderService
            order_service = OrderService(order_repository=self.order_repository)
            await order_service.recalculate_order_totals(db, order_id, commit=False)

            # Generate notification (do not commit yet)
            await self.notification_service.log_notification(
                db=db,
                order_id=order_id,
                notification_type=NotificationType.PAYMENT_RECEIVED,
                channel=NotificationChannel.SYSTEM,
                recipient=None,
                message_body=f"Payment of {schema.amount:.2f} received via {schema.payment_method.value} for Order {order.order_number}.",
                commit=False
            )

            # Commit everything atomically
            await db.commit()
            await db.refresh(db_payment)
            return db_payment
        except Exception:
            await db.rollback()
            raise

    async def get_payment_by_id(self, db: AsyncSession, id: uuid.UUID) -> Payment:
        payment = await self.payment_repository.get_by_id(db, id)
        if not payment:
            raise NotFoundException(f"Payment with ID '{id}' was not found.")
        return payment

    async def get_payments_by_order(self, db: AsyncSession, order_id: uuid.UUID) -> Sequence[Payment]:
        order = await self.order_repository.get_by_id(db, order_id)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")
        return await self.payment_repository.get_by_order_id(db, order_id)

    async def get_all_payments(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Payment]:
        return await self.payment_repository.get_all(db, skip=skip, limit=limit)

    async def update_payment(self, db: AsyncSession, id: uuid.UUID, schema: PaymentUpdate) -> Payment:
        from app.models.order import Order
        try:
            payment = await self.payment_repository.get_by_id(db, id)
            if not payment:
                raise NotFoundException(f"Payment with ID '{id}' was not found.")

            # Lock parent order row
            query = select(Order).where(Order.id == payment.order_id).with_for_update()
            result = await db.execute(query)
            order = result.scalar_one_or_none()
            if not order:
                raise NotFoundException(f"Order with ID '{payment.order_id}' was not found.")

            # Query payments explicitly using async SELECT inside the lock to avoid lazy loading
            pay_query = select(Payment).where(Payment.order_id == payment.order_id)
            pay_res = await db.execute(pay_query)
            payments = pay_res.scalars().all()

            update_data = schema.model_dump(exclude_unset=True)

            # If amount is being updated, perform overpayment validation
            if "amount" in update_data:
                new_amount = update_data["amount"]
                # Exclude current payment from sum
                other_payments_sum = sum(float(p.amount) for p in payments if p.id != id)
                new_total_paid = other_payments_sum + new_amount
                order_total = float(order.total_amount)

                if order_total > 0.00 and new_total_paid > order_total:
                    raise BadRequestException(
                        f"Updated payment amount of {new_amount} would exceed order total. "
                        f"Other payments: {other_payments_sum}, Order Total: {order_total}."
                    )

            updated_payment = await self.payment_repository.update(db, db_obj=payment, update_data=update_data, commit=False)
            await db.flush()

            # Trigger order recalculation
            from app.services.order import OrderService
            order_service = OrderService(order_repository=self.order_repository)
            await order_service.recalculate_order_totals(db, payment.order_id, commit=False)

            await db.commit()
            await db.refresh(updated_payment)
            return updated_payment
        except Exception:
            await db.rollback()
            raise

    async def delete_payment(self, db: AsyncSession, id: uuid.UUID) -> None:
        from app.models.order import Order
        try:
            payment = await self.payment_repository.get_by_id(db, id)
            if not payment:
                raise NotFoundException(f"Payment with ID '{id}' was not found.")

            # Lock parent order row
            query = select(Order).where(Order.id == payment.order_id).with_for_update()
            result = await db.execute(query)
            order = result.scalar_one_or_none()
            if not order:
                raise NotFoundException(f"Order with ID '{payment.order_id}' was not found.")

            order_id = payment.order_id
            await self.payment_repository.delete(db, db_obj=payment, commit=False)
            await db.flush()

            # Trigger order recalculation
            from app.services.order import OrderService
            order_service = OrderService(order_repository=self.order_repository)
            await order_service.recalculate_order_totals(db, order_id, commit=False)

            await db.commit()
        except Exception:
            await db.rollback()
            raise
