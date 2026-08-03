"""
app/services/invoice.py

Service layer for Invoice.
"""

import uuid
from datetime import datetime
from typing import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.invoice import Invoice, InvoiceStatus
from app.models.notification import NotificationType, NotificationChannel
from app.schemas.invoice import InvoiceCreate, InvoiceUpdate
from app.repositories.invoice import InvoiceRepository
from app.repositories.order import OrderRepository
from app.services.notification import NotificationService


class InvoiceService:
    def __init__(
        self,
        invoice_repository: InvoiceRepository | None = None,
        order_repository: OrderRepository | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.invoice_repository = invoice_repository or InvoiceRepository()
        self.order_repository = order_repository or OrderRepository()
        self.notification_service = notification_service or NotificationService()

    async def create_invoice(self, db: AsyncSession, order_id: uuid.UUID, schema: InvoiceCreate) -> Invoice:
        """
        Creates a new Invoice for an order.
        
        Business Rules:
        1. Ensure order exists.
        2. Idempotency: If there is an active (non-cancelled) invoice, return it.
        3. Generate a unique invoice number (Format: INV-YYYY-XXXXXX).
        4. Auto-calculate GST, Grand Total, and Balance based on order payments snapshot.
        5. Log INVOICE_GENERATED notification.
        """
        try:
            order = await self.order_repository.get_by_id(db, order_id)
            if not order:
                raise NotFoundException(f"Order with ID '{order_id}' was not found.")

            # Check for active invoice (Idempotent return)
            active_invoice = await self.invoice_repository.get_active_by_order_id(db, order_id)
            if active_invoice:
                return active_invoice

            # Generate invoice number
            invoice_year = datetime.utcnow().year
            latest = await self.invoice_repository.get_latest_invoice_for_year(db, invoice_year)
            if latest:
                try:
                    last_seq_str = latest.invoice_number.split("-")[-1]
                    last_seq = int(last_seq_str)
                except (ValueError, IndexError):
                    last_seq = 0
                new_seq = last_seq + 1
            else:
                new_seq = 1

            invoice_number = f"INV-{invoice_year}-{new_seq:06d}"

            # Calculations
            subtotal = float(schema.subtotal)
            discount = float(schema.discount)
            gst_percentage = float(schema.gst_percentage)

            taxable_amount = subtotal - discount
            gst_amount = round(taxable_amount * (gst_percentage / 100.0), 2)
            grand_total = round(taxable_amount + gst_amount, 2)

            # Paid amount snapshot from explicit DB query
            from app.models.payment import Payment
            from sqlalchemy import select
            pay_query = select(Payment).where(Payment.order_id == order_id)
            pay_res = await db.execute(pay_query)
            payments = pay_res.scalars().all()
            paid_amount = sum(float(p.amount) for p in payments)
            balance_amount = round(grand_total - paid_amount, 2)

            invoice = Invoice(
                order_id=order_id,
                invoice_number=invoice_number,
                subtotal=subtotal,
                discount=discount,
                gst_percentage=gst_percentage,
                gst_amount=gst_amount,
                grand_total=grand_total,
                paid_amount=paid_amount,
                balance_amount=balance_amount,
                status=schema.status,
                pdf_path=schema.pdf_path,
            )

            db_invoice = await self.invoice_repository.create(db, invoice, commit=False)
            await db.flush()

            # Generate notification
            await self.notification_service.log_notification(
                db=db,
                order_id=order_id,
                notification_type=NotificationType.INVOICE_GENERATED,
                channel=NotificationChannel.SYSTEM,
                recipient=None,
                message_body=f"Invoice {invoice_number} generated for Order {order.order_number}. Total: {grand_total:.2f}.",
                commit=False
            )

            await db.commit()
            await db.refresh(db_invoice)
            return db_invoice
        except Exception:
            await db.rollback()
            raise

    async def get_invoice_by_id(self, db: AsyncSession, id: uuid.UUID) -> Invoice:
        invoice = await self.invoice_repository.get_by_id(db, id)
        if not invoice:
            raise NotFoundException(f"Invoice with ID '{id}' was not found.")
        return invoice

    async def get_invoices_by_order(self, db: AsyncSession, order_id: uuid.UUID) -> Sequence[Invoice]:
        order = await self.order_repository.get_by_id(db, order_id)
        if not order:
            raise NotFoundException(f"Order with ID '{order_id}' was not found.")
        return await self.invoice_repository.get_by_order_id(db, order_id)

    async def get_all_invoices(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[Invoice]:
        return await self.invoice_repository.get_all(db, skip=skip, limit=limit)

    async def update_invoice(self, db: AsyncSession, id: uuid.UUID, schema: InvoiceUpdate) -> Invoice:
        """
        Updates an invoice and recalculates amounts if financial values are modified.
        """
        try:
            invoice = await self.invoice_repository.get_by_id(db, id)
            if not invoice:
                raise NotFoundException(f"Invoice with ID '{id}' was not found.")

            order = await self.order_repository.get_by_id(db, invoice.order_id)
            if not order:
                raise NotFoundException(f"Order with ID '{invoice.order_id}' was not found.")

            update_data = schema.model_dump(exclude_unset=True)

            # Check if financial fields are updated
            subtotal = float(update_data.get("subtotal", invoice.subtotal))
            discount = float(update_data.get("discount", invoice.discount))
            gst_percentage = float(update_data.get("gst_percentage", invoice.gst_percentage))

            if "subtotal" in update_data or "discount" in update_data or "gst_percentage" in update_data:
                taxable_amount = subtotal - discount
                gst_amount = round(taxable_amount * (gst_percentage / 100.0), 2)
                grand_total = round(taxable_amount + gst_amount, 2)

                update_data["gst_amount"] = gst_amount
                update_data["grand_total"] = grand_total

                # Recalculate balance using snapshot from DB query
                from app.models.payment import Payment
                from sqlalchemy import select
                pay_query = select(Payment).where(Payment.order_id == invoice.order_id)
                pay_res = await db.execute(pay_query)
                payments = pay_res.scalars().all()
                paid_amount = sum(float(p.amount) for p in payments)
                update_data["paid_amount"] = paid_amount
                update_data["balance_amount"] = round(grand_total - paid_amount, 2)

            elif "status" in update_data:
                # If status becomes PAID or CANCELLED, we may want to update paid snapshot
                from app.models.payment import Payment
                from sqlalchemy import select
                pay_query = select(Payment).where(Payment.order_id == invoice.order_id)
                pay_res = await db.execute(pay_query)
                payments = pay_res.scalars().all()
                paid_amount = sum(float(p.amount) for p in payments)
                update_data["paid_amount"] = paid_amount
                update_data["balance_amount"] = round(float(invoice.grand_total) - paid_amount, 2)

            updated_invoice = await self.invoice_repository.update(db, db_obj=invoice, update_data=update_data, commit=False)
            await db.commit()
            await db.refresh(updated_invoice)
            return updated_invoice
        except Exception:
            await db.rollback()
            raise

    async def delete_invoice(self, db: AsyncSession, id: uuid.UUID) -> None:
        try:
            invoice = await self.invoice_repository.get_by_id(db, id)
            if not invoice:
                raise NotFoundException(f"Invoice with ID '{id}' was not found.")
            await self.invoice_repository.delete(db, db_obj=invoice, commit=False)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
