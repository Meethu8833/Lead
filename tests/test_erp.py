"""
tests/test_erp.py

Comprehensive integration test suite for the Colour Lab CRM Normalized ERP design.
Verifies:
1. Product catalog CRUD & uniqueness constraints.
2. Order creation and initial empty total.
3. OrderItem addition & automatic subtotal/order total calculations.
4. Quantity and discount updates with auto-recalculation.
5. Item deletion with auto-recalculation.
6. Historical snapshot preservation (Product name/price changes do not affect order items).
7. Pagination and search.
8. Relationship integrity.

This test suite runs within an isolated database transaction block that rolls back upon completion,
keeping the PostgreSQL database completely clean.
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, text

# Add the project root to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.photographer import Photographer
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.order_item import OrderItem
from app.schemas.product import ProductCreate, ProductUpdate
from app.schemas.order import OrderCreate
from app.schemas.order_item import OrderItemCreate, OrderItemUpdate
from app.services.product import ProductService
from app.services.order import OrderService
from app.services.order_item import OrderItemService


async def test_suite():
    # Instantiate services
    product_service = ProductService()
    order_service = OrderService()
    order_item_service = OrderItemService()

    async with AsyncSessionLocal() as db:
        # Start a nested transaction (savepoint) or regular transaction
        # To roll back all changes, we do not commit to the main database.
        # SQLAlchemy sessions start transactions automatically. We will simply rollback at the end.
        try:
            print("=== [1] SETTING UP TEST PHOTOGRAPHER ===")
            # Get or create a photographer to associate with our orders
            result = await db.execute(select(Photographer).limit(1))
            photographer = result.scalars().first()
            if not photographer:
                photographer = Photographer(
                    name="Test Photographer",
                    studio_name="Test Studio",
                    phone="9999999999",
                    email="test@photographer.com",
                    city="Test City",
                    address="123 Test Street",
                    category="PREMIUM",
                    is_active=True
                )
                db.add(photographer)
                await db.flush()
                print(f"Created a new test photographer ID: {photographer.id}")
            else:
                print(f"Using existing photographer ID: {photographer.id}")

            photographer_id = photographer.id

            print("\n=== [2] TESTING PRODUCT CATALOG CRUD & UNIQUENESS ===")
            unique_suffix = str(uuid.uuid4())[:8]
            prod_name_1 = f"Test Premium Frame {unique_suffix}"
            prod_name_2 = f"Test Canvas Print {unique_suffix}"
            prod_name_3 = f"Test Inactive Album {unique_suffix}"
            prod_name_1_updated = f"Premium Frame Updated Name {unique_suffix}"

            # 1. Create a product
            prod_create_1 = ProductCreate(
                name=prod_name_1,
                category="Frame",
                size="12x18",
                unit="piece",
                description="High-quality synthetic frame",
                base_price=500.00,
                is_active=True
            )
            product1 = await product_service.create_product(db, prod_create_1)
            assert product1.id is not None
            assert product1.name == prod_name_1
            assert product1.base_price == 500.00
            print(f"Successfully created product: {product1.name} (ID: {product1.id})")

            # 2. Verify duplicate name constraint throws BadRequestException
            try:
                await product_service.create_product(db, prod_create_1)
                assert False, "Duplicate product name did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Uniqueness check passed (raised BadRequestException): {e}")

            # 3. Create a second product
            prod_create_2 = ProductCreate(
                name=prod_name_2,
                category="Canvas",
                size="16x24",
                unit="piece",
                description="Matte finish canvas",
                base_price=1200.00,
                is_active=True
            )
            product2 = await product_service.create_product(db, prod_create_2)
            print(f"Successfully created product: {product2.name} (ID: {product2.id})")

            # 4. Create an inactive product to test selection validation
            prod_create_3 = ProductCreate(
                name=prod_name_3,
                category="Album",
                size="12x36",
                unit="piece",
                description="Older discontinued album",
                base_price=3000.00,
                is_active=False
            )
            product3 = await product_service.create_product(db, prod_create_3)
            print(f"Successfully created inactive product: {product3.name} (ID: {product3.id})")

            print("\n=== [3] TESTING ORDER CREATION (INITIAL EMPTY TOTAL) ===")
            order_create = OrderCreate(
                photographer_id=photographer_id,
                job_name="Test Normalization Job",
                event_type="Wedding",
                booking_date=datetime.now(timezone.utc),
                event_date=datetime.now(timezone.utc),
                advance_paid=200.00,
                status=OrderStatus.RECEIVED
            )
            order = await order_service.create_order(db, order_create)
            assert order.id is not None
            assert float(order.total_amount) == 0.00
            # balance = total - advance = 0 - 200 = -200
            assert float(order.balance_amount) == -200.00
            print(f"Successfully created order: {order.order_number} (ID: {order.id})")
            print(f"Initial Total: {order.total_amount}, Balance: {order.balance_amount}")

            print("\n=== [4] TESTING ADDING ORDER ITEMS & AUTOMATIC RECALCULATION ===")
            # 1. Add first item (Frame): Qty 2, Unit Price 500.00, Discount 100.00
            # Subtotal = (500 * 2) - 100 = 900.00
            item_create_1 = OrderItemCreate(
                product_id=product1.id,
                quantity=2,
                discount=100.00
                # unit_price omitted, defaults to product base_price (500.00)
            )
            item1 = await order_item_service.create_item(db, order.id, item_create_1)
            assert item1.unit_price == 500.00
            assert item1.subtotal == 900.00
            assert item1.product_name == prod_name_1
            print(f"Added item 1: {item1.product_name}, Qty: {item1.quantity}, Subtotal: {item1.subtotal}")

            # Reload order to verify recalculated total: 900.00, Balance: 900 - 200 = 700.00
            await db.refresh(order)
            assert float(order.total_amount) == 900.00
            assert float(order.balance_amount) == 700.00
            print(f"After Item 1 -> Order Total: {order.total_amount}, Balance: {order.balance_amount}")

            # 2. Add second item (Canvas): Qty 1, Unit Price 1200.00, Discount 0.00
            # Subtotal = 1200.00
            item_create_2 = OrderItemCreate(
                product_id=product2.id,
                quantity=1,
                discount=0.00
            )
            item2 = await order_item_service.create_item(db, order.id, item_create_2)
            assert item2.subtotal == 1200.00
            print(f"Added item 2: {item2.product_name}, Qty: {item2.quantity}, Subtotal: {item2.subtotal}")

            # Reload order: total should be 900 + 1200 = 2100.00, Balance: 2100 - 200 = 1900.00
            await db.refresh(order)
            assert float(order.total_amount) == 2100.00
            assert float(order.balance_amount) == 1900.00
            print(f"After Item 2 -> Order Total: {order.total_amount}, Balance: {order.balance_amount}")

            # 3. Verify selection of inactive product raises BadRequestException
            try:
                item_create_inactive = OrderItemCreate(
                    product_id=product3.id,
                    quantity=1,
                    discount=0.00
                )
                await order_item_service.create_item(db, order.id, item_create_inactive)
                assert False, "Selecting inactive product did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Selection of inactive product block passed: {e}")

            print("\n=== [5] TESTING UPDATING QUANTITIES & RECALCULATION ===")
            # Update Item 1 quantity to 3. New subtotal = (500 * 3) - 100 = 1400.00
            # Order total should become 1400 + 1200 = 2600.00, Balance: 2600 - 200 = 2400.00
            item_update = OrderItemUpdate(quantity=3)
            await order_item_service.update_item(db, item1.id, item_update)
            
            await db.refresh(order)
            assert float(order.total_amount) == 2600.00
            assert float(order.balance_amount) == 2400.00
            print(f"After Updating Item 1 Qty to 3 -> Order Total: {order.total_amount}, Balance: {order.balance_amount}")

            print("\n=== [6] TESTING DELETING ITEM & RECALCULATION ===")
            # Delete Item 2 (Canvas, subtotal 1200.00).
            # Order total should become 2600 - 1200 = 1400.00, Balance: 1400 - 200 = 1200.00
            await order_item_service.delete_item(db, item2.id)

            await db.refresh(order)
            assert float(order.total_amount) == 1400.00
            assert float(order.balance_amount) == 1200.00
            print(f"After Deleting Item 2 -> Order Total: {order.total_amount}, Balance: {order.balance_amount}")

            print("\n=== [7] TESTING HISTORICAL PRODUCT SNAPSHOT INTEGRITY ===")
            # Change the catalog product Frame's price and name
            prod_update = ProductUpdate(
                name=prod_name_1_updated,
                base_price=999.00
            )
            await product_service.update_product(db, product1.id, prod_update)

            # Reload Item 1 from DB
            db_item1 = await order_item_service.get_item_by_id(db, item1.id)
            # Assert snapshots are NOT changed!
            assert db_item1.product_name == prod_name_1
            assert float(db_item1.unit_price) == 500.00
            print(f"Snapshot Check Passed:")
            print(f"- Current Catalog Product Name: {prod_name_1_updated}, Price: 999.00")
            print(f"- Existing Order Item Snapshot Name: {db_item1.product_name}, Snapshot Price: {db_item1.unit_price}")

            print("\n=== [8] TESTING SEARCH AND PAGINATION ===")
            # Search catalog products
            search_res = await product_service.search_products(db, name=prod_name_1_updated, is_active=True)
            assert len(search_res) >= 1
            print(f"Search results for '{prod_name_1_updated}': Found {len(search_res)} products")

            # Check pagination on products list
            paginated_res = await product_service.get_all_products(db, skip=0, limit=1)
            assert len(paginated_res) == 1
            print("Pagination check passed.")

            print("\n=== [9] RELATIONSHIP INTEGRITY ===")
            # Reload order with items relationship loaded
            await db.refresh(order)
            assert len(order.items) == 1
            assert order.items[0].id == item1.id
            print(f"Order items count: {len(order.items)}")
            print("Relationship integrity checks passed.")

            print("\n=== ALL ERP UNIT TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # ROLLBACK to keep the database clean
            print("\nRolling back all test data changes to keep the database clean...")
            await db.rollback()
            print("Rollback successful.")


if __name__ == "__main__":
    asyncio.run(test_suite())
