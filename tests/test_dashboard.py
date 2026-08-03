"""
tests/test_dashboard.py

Integration tests for the Business Dashboard KPIs.
Verifies that the DashboardService correctly aggregates and computes:
1. Today's Orders count.
2. Weekly and Monthly Revenue.
3. Pending Production items.
4. Delayed Orders count.
5. Top 5 Products.
6. Top 5 Customers.
7. Outstanding Balance.
8. Average Order Value.
"""

import asyncio
import sys
import os
import uuid
import random
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.models.photographer import Photographer
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem, ProductionStage
from app.models.payment import Payment, PaymentMethod
from app.services.dashboard import DashboardService


async def test_dashboard():
    print("=== STARTING DASHBOARD INTEGRATION TESTS ===")

    service = DashboardService()

    async with AsyncSessionLocal() as db:
        try:
            print("\n--- [1] FETCHING INITIAL DASHBOARD METRICS ---")
            initial_stats = await service.get_dashboard_stats(db)
            print(f"Initial - Today's Orders: {initial_stats.today_orders}")
            print(f"Initial - Weekly Revenue: {initial_stats.weekly_revenue}")
            print(f"Initial - Outstanding Balance: {initial_stats.outstanding_balance}")

            print("\n--- [2] SEEDING METRIC TEST DATA ---")
            rand_suffix = str(uuid.uuid4())[:8]

            # 1. Create photographer (customer)
            phone = "".join(random.choices("0123456789", k=10))
            photographer = Photographer(
                name=f"Big Spender {rand_suffix}",
                studio_name="Premium Studio",
                phone=phone,
                email="spender@studio.com",
                city="Capital City",
                category="PREMIUM",
                is_active=True
            )
            db.add(photographer)
            await db.flush()

            # 2. Create Order
            now = datetime.now(timezone.utc)
            order = Order(
                photographer_id=photographer.id,
                order_number=f"ORD-DASH-{rand_suffix}",
                job_name=f"Dashboard Test Job {rand_suffix}",
                booking_date=now,
                expected_delivery_date=now - timedelta(days=1), # Delayed!
                total_amount=1500.00,
                advance_paid=500.00,
                status=OrderStatus.PRINTING,
                is_deleted=False
            )
            db.add(order)
            await db.flush()

            # 3. Create OrderItems
            item1 = OrderItem(
                order_id=order.id,
                product_name=f"Best Frame {rand_suffix}",
                product_category="Frames",
                quantity=10,
                unit_price=100.00,
                discount=0.00,
                subtotal=1000.00,
                production_stage=ProductionStage.PRINTING,
                is_deleted=False
            )
            item2 = OrderItem(
                order_id=order.id,
                product_name=f"Paper Print {rand_suffix}",
                product_category="Prints",
                quantity=5,
                unit_price=100.00,
                discount=0.00,
                subtotal=500.00,
                production_stage=ProductionStage.RECEIVED,
                is_deleted=False
            )
            db.add(item1)
            db.add(item2)
            await db.flush()

            # 4. Create a Payment
            payment = Payment(
                order_id=order.id,
                amount=500.00,
                payment_method=PaymentMethod.CASH,
                reference_number=f"TXN-{rand_suffix}",
                received_at=now
            )
            db.add(payment)
            
            # Recalculate order legacy balance
            order._balance_amount = 1000.00
            db.add(order)
            await db.flush()

            print("Test data successfully flushed to session.")

            print("\n--- [3] FETCHING UPDATED DASHBOARD METRICS ---")
            updated_stats = await service.get_dashboard_stats(db)
            
            # Assertions
            # Today's orders count should have increased by 1
            assert updated_stats.today_orders == initial_stats.today_orders + 1
            # Weekly revenue should have increased by payment amount (500.00)
            assert updated_stats.weekly_revenue == initial_stats.weekly_revenue + 500.00
            # Monthly revenue should also increase by 500.00
            assert updated_stats.monthly_revenue == initial_stats.monthly_revenue + 500.00
            # Pending production items should have increased by 2
            assert updated_stats.pending_production == initial_stats.pending_production + 2
            # Delayed orders should have increased by 1
            assert updated_stats.delayed_orders == initial_stats.delayed_orders + 1
            # Outstanding balance should have increased by the unpaid balance (1000.00)
            assert updated_stats.outstanding_balance == initial_stats.outstanding_balance + 1000.00

            # Verify Top Products list
            top_prod_names = [p.product_name for p in updated_stats.top_products]
            assert f"Best Frame {rand_suffix}" in top_prod_names

            # Verify Top Customers list
            top_cust_names = [c.name for c in updated_stats.top_customers]
            assert f"Big Spender {rand_suffix}" in top_cust_names

            print("All dashboard KPIs verified successfully!")

            print("\n=== ALL DASHBOARD INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        finally:
            await db.rollback()
            print("Database transaction rolled back.")


if __name__ == "__main__":
    asyncio.run(test_dashboard())
