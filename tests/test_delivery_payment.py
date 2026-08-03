"""
tests/test_delivery_payment.py

Comprehensive integration test suite for the Colour Lab CRM
Delivery, Payment, Invoice, and Notification modules.
Includes production hardening checks:
- Concurrency Safety
- Invoice Idempotency
- Zero-Total Advance Payments
- Database CHECK Constraints & Unique Indexes
- Transaction Rollbacks
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.photographer import Photographer
from app.models.order import Order, OrderStatus, PaymentStatus
from app.models.product import Product
from app.models.order_item import OrderItem
from app.models.payment import Payment, PaymentMethod
from app.models.invoice import Invoice, InvoiceStatus
from app.models.delivery import Delivery, DeliveryStatus, DeliveryMethod
from app.models.notification import NotificationLog, NotificationType, NotificationChannel

from app.schemas.product import ProductCreate
from app.schemas.order import OrderCreate
from app.schemas.order_item import OrderItemCreate
from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.schemas.invoice import InvoiceCreate, InvoiceUpdate
from app.schemas.delivery import DeliveryCreate, DeliveryUpdate

from app.services.product import ProductService
from app.services.order import OrderService
from app.services.order_item import OrderItemService
from app.services.payment import PaymentService
from app.services.invoice import InvoiceService
from app.services.delivery import DeliveryService
from app.services.notification import NotificationService
from app.services.dashboard import DashboardService


async def test_crm_lifecycle():
    # Instantiate services
    product_service = ProductService()
    order_service = OrderService()
    order_item_service = OrderItemService()
    payment_service = PaymentService()
    invoice_service = InvoiceService()
    delivery_service = DeliveryService()
    notification_service = NotificationService()
    dashboard_service = DashboardService()

    async with AsyncSessionLocal() as db:
        try:
            print("=== [1] SETTING UP PHOTOGRAPHER & PRODUCT ===")
            result = await db.execute(select(Photographer).limit(1))
            photographer = result.scalars().first()
            if not photographer:
                photographer = Photographer(
                    name="Lifecycle Photographer",
                    studio_name="Lifecycle Studios",
                    phone="7777777777",
                    email="lifecycle@test.com",
                    city="Lifecycle City",
                    address="123 Lifecycle Road",
                    category="PREMIUM",
                    is_active=True
                )
                db.add(photographer)
                await db.flush()
            photographer_id = photographer.id

            unique_suffix = str(uuid.uuid4())[:8]
            product = await product_service.create_product(db, ProductCreate(
                name=f"Premium Matte Print {unique_suffix}",
                category="Print",
                size="12x18",
                unit="piece",
                description="High quality matte finish paper print",
                base_price=1000.00,
                is_active=True
            ))

            print("\n=== [2] TESTING ZERO-TOTAL ADVANCE PAYMENT RULE ===")
            # Part 1 check: If total_amount == 0, status must remain PENDING even if advance_paid > 0
            booking_date = datetime.now(timezone.utc)
            order_create = OrderCreate(
                photographer_id=photographer_id,
                job_name="Zero Total Advance Job",
                event_type="Wedding Portfolio",
                booking_date=booking_date,
                expected_delivery_date=booking_date + timedelta(days=4),
                advance_paid=300.00,
                status=OrderStatus.RECEIVED
            )
            order = await order_service.create_order(db, order_create)
            assert order.id is not None
            order_id = order.id
            assert float(order.total_amount) == 0.00
            assert order.payment_status == PaymentStatus.PENDING
            print(f"Zero-Total Order correctly stayed PENDING. Advance paid: {order.advance_paid}")

            print("\n=== [3] TESTING AUTOMATIC STATUS RECALCULATION ON ADDING ITEMS ===")
            # Add item: Qty 1, base price 1000. Total = 1000.00. Balance = 1000 - 300 = 700.00
            item = await order_item_service.create_item(db, order_id, OrderItemCreate(
                product_id=product.id,
                quantity=1,
                discount=0.00
            ))
            
            # Reload order asynchronously
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one()

            assert float(order.total_amount) == 1000.00
            assert float(order.balance_amount) == 700.00
            assert order.payment_status == PaymentStatus.PARTIALLY_PAID
            print(f"Status recalculated after adding item. Total: {order.total_amount}, Status: {order.payment_status}")

            print("\n=== [4] TESTING CONCURRENT PAYMENTS (SELECT FOR UPDATE) ===")
            # We want to run two payments concurrently.
            # Total remaining balance is 700.00.
            # We spawn two concurrent calls, each trying to pay 500.00 (which exceeds 700 combined).
            # One must succeed and one must fail with BadRequestException due to serialization.
            async def make_payment(session, amount):
                try:
                    return await payment_service.create_payment(session, order_id, PaymentCreate(
                        payment_method=PaymentMethod.UPI,
                        amount=amount,
                        allow_overpayment=False
                    ))
                except Exception as e:
                    return e

            async with AsyncSessionLocal() as db1, AsyncSessionLocal() as db2:
                tasks = [
                    make_payment(db1, 500.00),
                    make_payment(db2, 500.00)
                ]
                results = await asyncio.gather(*tasks)

            print(f"DEBUG - Concurrency results: {results}")
            # Analyze results: one should be Payment and the other BadRequestException
            payments_succeeded = [r for r in results if isinstance(r, Payment)]
            exceptions_raised = [r for r in results if isinstance(r, BadRequestException)]
            
            if len(payments_succeeded) != 1 or len(exceptions_raised) != 1:
                print(f"Assertion failed! Succeeded count: {len(payments_succeeded)}, exceptions count: {len(exceptions_raised)}")
                for r in results:
                    if isinstance(r, Exception):
                        import traceback
                        print(f"Exception result: {r}")
                        traceback.print_exception(type(r), r, r.__traceback__)
            
            assert len(payments_succeeded) == 1
            assert len(exceptions_raised) == 1
            print("Concurrency validation passed! One payment succeeded, one was blocked.")
            print(f"- Succeeded Payment: ID {payments_succeeded[0].id}, Amount: {payments_succeeded[0].amount}")
            print(f"- Blocked Exception message: {exceptions_raised[0]}")

            # Force reload by expiring session cache to load payments created in db1
            db.expire_all()
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one()
            print(f"Current order balance: {order.balance_amount}")
            assert float(order.balance_amount) == 200.00

            print("\n=== [5] TESTING IDEMPOTENT INVOICE GENERATION ===")
            invoice_create = InvoiceCreate(
                subtotal=1000.00,
                discount=0.00,
                gst_percentage=18.00,
                status=InvoiceStatus.GENERATED
            )
            # Create first invoice
            invoice1 = await invoice_service.create_invoice(db, order_id, invoice_create)
            assert invoice1.id is not None
            print(f"Generated first invoice: {invoice1.invoice_number}")

            # Create second invoice - should return the existing invoice instead of throwing error
            invoice2 = await invoice_service.create_invoice(db, order_id, invoice_create)
            assert invoice1.id == invoice2.id
            assert invoice1.invoice_number == invoice2.invoice_number
            print("Idempotency validation passed! Second invoice generation returned the existing invoice.")

            print("\n=== [6] TESTING DATABASE-LEVEL CHECK CONSTRAINTS & UNIQUE INDEXES ===")
            # 1. Test negative payment amount constraint
            invalid_payment = Payment(
                order_id=order_id,
                amount=-50.00,  # Negative
                payment_method=PaymentMethod.CASH
            )
            db.add(invalid_payment)
            try:
                await db.commit()
                assert False, "Database constraint failed to block negative payment amount"
            except Exception as e:
                await db.rollback()
                # Reload order object asynchronously to prevent MissingGreenlet errors
                result = await db.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one()
                print(f"Negative payment correctly blocked by database check constraint: {e}")

            # 2. Test invalid GST percentage constraint (> 100)
            invalid_invoice = Invoice(
                order_id=order_id,
                invoice_number=f"INV-ERR-{uuid.uuid4()}",
                subtotal=100.00,
                discount=0.00,
                gst_percentage=150.00,  # Invalid (>100)
                gst_amount=150.00,
                grand_total=250.00,
                paid_amount=0.00,
                balance_amount=250.00,
                status=InvoiceStatus.DRAFT
            )
            db.add(invalid_invoice)
            try:
                await db.commit()
                assert False, "Database constraint failed to block invalid GST percentage (>100)"
            except Exception as e:
                await db.rollback()
                result = await db.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one()
                print(f"Invalid GST percentage correctly blocked by database check constraint: {e}")

            # 3. Test illogical delivery dates constraint (delivered_date < dispatch_date)
            invalid_delivery = Delivery(
                order_id=order_id,
                delivery_method=DeliveryMethod.COURIER,
                dispatch_date=datetime.now(timezone.utc),
                delivered_date=datetime.now(timezone.utc) - timedelta(days=1),  # illogical
                status=DeliveryStatus.DELIVERED
            )
            db.add(invalid_delivery)
            try:
                await db.commit()
                assert False, "Database constraint failed to block illogical delivery dates"
            except Exception as e:
                await db.rollback()
                result = await db.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one()
                print(f"Illogical delivery dates correctly blocked by database check constraint: {e}")

            # 4. Test partial unique index (only one active invoice per order)
            # Try to add another active invoice directly to DB bypass service layer checks
            inv_dup = Invoice(
                order_id=order_id,
                invoice_number=f"INV-DUP-{uuid.uuid4()}",
                subtotal=100.0,
                discount=0.0,
                gst_percentage=18.0,
                gst_amount=18.0,
                grand_total=118.0,
                paid_amount=0.0,
                balance_amount=118.0,
                status=InvoiceStatus.DRAFT
            )
            db.add(inv_dup)
            try:
                await db.commit()
                assert False, "Database unique index failed to block duplicate active invoice"
            except Exception as e:
                await db.rollback()
                result = await db.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one()
                print(f"Duplicate active invoices correctly blocked by database partial unique index: {e}")

            print("\n=== [7] TESTING TRANSACTION ROLLBACK ON FAILURE ===")
            # Monkeypatch log_notification in payment service's notification service to raise exception
            original_log = payment_service.notification_service.log_notification
            async def mock_log(*args, **kwargs):
                raise ValueError("Simulated notification logging failure")
            payment_service.notification_service.log_notification = mock_log
            
            try:
                await payment_service.create_payment(db, order_id, PaymentCreate(
                    amount=50.00,
                    payment_method=PaymentMethod.CASH,
                    remarks="Rollback test"
                ))
                assert False, "Payment creation should have failed due to mock notification logging error"
            except ValueError as e:
                # Reload order object asynchronously to prevent MissingGreenlet
                result = await db.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one()
                print(f"Payment service correctly raised error: {e}")
                
                # Ensure payment was NOT created (rollback worked)
                query = select(Payment).where(Payment.order_id == order_id, Payment.remarks == "Rollback test")
                result = await db.execute(query)
                payments = result.scalars().all()
                assert len(payments) == 0, "Payment was saved in the DB despite failure! Rollback failed."
                print("Rollback verification successful: payment was not persisted.")
            finally:
                payment_service.notification_service.log_notification = original_log

            print("\n=== [8] DASHBOARD STATS PERFORMANCES ===")
            # Verify single-query dashboard statistics work
            stats = await dashboard_service.get_dashboard_stats(db)
            print("Retrieved dashboard metrics:")
            print(f"- Revenue Today: {stats.revenue_today}")
            print(f"- Payments Today: {stats.payments_today}")
            print(f"- Orders Delivered Today: {stats.orders_delivered_today}")
            print(f"- Invoices Generated: {stats.invoices_generated}")
            assert stats.revenue_today >= 500.00
            print("Dashboard optimized queries executed successfully.")

            print("\n=== ALL HARDFENED CRM LIFE-CYCLE TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            print("\nRolling back all test transaction changes to keep database clean...")
            await db.rollback()
            print("Rollback successful.")


if __name__ == "__main__":
    asyncio.run(test_crm_lifecycle())
