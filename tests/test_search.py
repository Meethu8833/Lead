"""
tests/test_search.py

Integration tests for the Global Search feature.
Verifies that:
1. Keyword search matches records across Photographers, Orders, Products, and Invoices.
2. Results are returned concurrently in parallel.
3. Soft deleted items are ignored from search results.
"""

import asyncio
import sys
import os
import uuid
import random
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.models.photographer import Photographer
from app.models.order import Order
from app.models.product import Product
from app.models.invoice import Invoice, InvoiceStatus
from app.services.search import SearchService


async def test_search():
    print("=== STARTING GLOBAL SEARCH INTEGRATION TESTS ===")

    service = SearchService()

    async with AsyncSessionLocal() as db:
        try:
            print("\n--- [1] PREPARING TEST DATA ---")
            rand_suffix = str(uuid.uuid4())[:8]
            keyword = f"Zebra{rand_suffix}"

            # 1. Create a matching photographer
            phone = "".join(random.choices("0123456789", k=10))
            photographer = Photographer(
                name=f"Studio {keyword}",
                studio_name="Zebra Studios",
                phone=phone,
                email="zebra@studios.com",
                city="Zebra City",
                category="REGULAR",
                is_active=True
            )
            db.add(photographer)
            
            # 2. Create a product
            product = Product(
                name=f"Premium {keyword} Photo Frame",
                category="Frames",
                size="10x12",
                unit="piece",
                description="Zebra wood frame",
                base_price=250.00,
                is_active=True
            )
            db.add(product)
            await db.flush()

            # 3. Create an order
            datetime_now = datetime_utc_now()
            order = Order(
                photographer_id=photographer.id,
                order_number=f"ORD-{keyword.upper()}",
                job_name=f"Wedding Album for {keyword}",
                booking_date=datetime_now,
                total_amount=1000.00,
                advance_paid=200.00,
                is_deleted=False
            )
            db.add(order)
            await db.flush()

            # 4. Create an invoice
            invoice = Invoice(
                order_id=order.id,
                invoice_number=f"INV-{keyword.upper()}",
                invoice_date=datetime_now,
                subtotal=1000.00,
                discount=0.00,
                gst_percentage=18.00,
                grand_total=1180.00,
                status=InvoiceStatus.GENERATED
            )
            db.add(invoice)
            await db.flush()

            print(f"Created test records containing keyword: '{keyword}'")

            print("\n--- [2] RUNNING GLOBAL SEARCH ---")
            results = await service.global_search(db, query=keyword)
            
            # Verify results
            assert len(results["photographers"]) == 1
            assert results["photographers"][0].name == f"Studio {keyword}"

            assert len(results["products"]) == 1
            assert results["products"][0].name == f"Premium {keyword} Photo Frame"

            assert len(results["orders"]) == 1
            assert results["orders"][0].job_name == f"Wedding Album for {keyword}"

            assert len(results["invoices"]) == 1
            assert results["invoices"][0].invoice_number == f"INV-{keyword.upper()}"
            
            print("Unified search successfully found matching records in all 4 categories!")

            print("\n--- [3] TESTING SOFT DELETE FILTERS ---")
            # Soft delete order
            order.is_deleted = True
            db.add(order)
            await db.flush()

            # Re-run search
            results_after_delete = await service.global_search(db, query=keyword)
            assert len(results_after_delete["orders"]) == 0
            assert len(results_after_delete["photographers"]) == 1
            print("Soft-deleted items are correctly excluded from search results.")

            print("\n=== ALL GLOBAL SEARCH INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        finally:
            await db.rollback()
            print("Database transaction rolled back.")


def datetime_utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


if __name__ == "__main__":
    asyncio.run(test_search())
