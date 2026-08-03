"""
tests/test_production.py

Comprehensive integration test suite for the Colour Lab CRM Production Workflow Module.
Verifies stage progression, validation constraints, status calculation, dashboard metrics,
assignments, and notes.
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

# Add the project root to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.photographer import Photographer
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.order_item import OrderItem, ProductionStage
from app.schemas.product import ProductCreate
from app.schemas.order import OrderCreate
from app.schemas.order_item import OrderItemCreate
from app.services.product import ProductService
from app.services.order import OrderService
from app.services.order_item import OrderItemService


async def test_production_workflow():
    product_service = ProductService()
    order_service = OrderService()
    order_item_service = OrderItemService()

    async with AsyncSessionLocal() as db:
        try:
            print("=== [1] SETTING UP TEST PHOTOGRAPHER & PRODUCTS ===")
            result = await db.execute(select(Photographer).limit(1))
            photographer = result.scalars().first()
            if not photographer:
                photographer = Photographer(
                    name="Test Production Photographer",
                    studio_name="Prod Studio",
                    phone="8888888888",
                    email="prod_test@photographer.com",
                    city="Prod City",
                    address="123 Prod Street",
                    category="PREMIUM",
                    is_active=True
                )
                db.add(photographer)
                await db.flush()
            photographer_id = photographer.id

            # Create test products
            unique_suffix = str(uuid.uuid4())[:8]
            prod1 = await product_service.create_product(db, ProductCreate(
                name=f"Acrylic Album {unique_suffix}",
                category="Album",
                size="12x18",
                unit="piece",
                description="Acrylic cover photo album",
                base_price=2000.00,
                is_active=True
            ))
            prod2 = await product_service.create_product(db, ProductCreate(
                name=f"Standard Frame {unique_suffix}",
                category="Frame",
                size="8x10",
                unit="piece",
                description="Wood frame",
                base_price=400.00,
                is_active=True
            ))

            print("\n=== [2] TESTING ORDER STATUS WITH EMPTY ITEMS ===")
            order_create = OrderCreate(
                photographer_id=photographer_id,
                job_name="Test Production Job",
                event_type="Pre-wedding",
                booking_date=datetime.now(timezone.utc),
                expected_delivery_date=datetime.now(timezone.utc) + timedelta(days=5),
                advance_paid=500.00,
                status=OrderStatus.RECEIVED
            )
            order = await order_service.create_order(db, order_create)
            assert order.status == OrderStatus.RECEIVED
            print(f"Order created with status: {order.status}")

            print("\n=== [3] TESTING ORDER ITEM CREATION & INITIAL STATUS ===")
            item1 = await order_item_service.create_item(db, order.id, OrderItemCreate(
                product_id=prod1.id,
                quantity=1,
                discount=100.00
            ))
            item2 = await order_item_service.create_item(db, order.id, OrderItemCreate(
                product_id=prod2.id,
                quantity=2,
                discount=0.00
            ))

            assert item1.production_stage == ProductionStage.RECEIVED
            assert item2.production_stage == ProductionStage.RECEIVED
            assert item1.started_at is None
            assert item1.completed_at is None

            # Reload parent order to check status
            await db.refresh(order)
            assert order.status == OrderStatus.RECEIVED
            print(f"Initial items created at RECEIVED stage. Parent order status: {order.status}")

            print("\n=== [4] TESTING STAGE PROGRESSION (RECEIVED -> DESIGNING) ===")
            # 1. Transition item 1 from RECEIVED to DESIGNING (valid forward transition)
            item1 = await order_item_service.update_production_stage(
                db, item1.id, stage=ProductionStage.DESIGNING
            )
            assert item1.production_stage == ProductionStage.DESIGNING
            assert item1.started_at is not None
            print(f"Item 1 successfully moved to DESIGNING. started_at: {item1.started_at}")

            # Parent status should equal lowest stage: min(DESIGNING, RECEIVED) = RECEIVED
            await db.refresh(order)
            assert order.status == OrderStatus.RECEIVED
            print(f"Parent order status after Item 1 update: {order.status}")

            print("\n=== [5] TESTING INVALID FORWARD TRANSITION (RECEIVED -> READY) ===")
            try:
                await order_item_service.update_production_stage(
                    db, item2.id, stage=ProductionStage.READY
                )
                assert False, "Skipping directly from RECEIVED to READY did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Transition block check passed: RECEIVED -> READY raises: {e}")

            print("\n=== [6] TESTING SEQUENTIAL TRANSITION OF ITEM 2 ===")
            item2 = await order_item_service.update_production_stage(
                db, item2.id, stage=ProductionStage.DESIGNING
            )
            # Both items are now DESIGNING, so parent status must become DESIGNING
            await db.refresh(order)
            assert order.status == OrderStatus.DESIGNING
            print(f"Item 2 moved to DESIGNING. Parent order status: {order.status}")

            print("\n=== [7] TESTING BACKWARD TRANSITION PROTECTION ===")
            try:
                await order_item_service.update_production_stage(
                    db, item1.id, stage=ProductionStage.RECEIVED, allow_backward=False
                )
                assert False, "Backward transition without allow_backward=True did not raise BadRequestException"
            except BadRequestException as e:
                print(f"Backward protection check passed: {e}")

            # Try again with allow_backward=True
            item1 = await order_item_service.update_production_stage(
                db, item1.id, stage=ProductionStage.RECEIVED, allow_backward=True
            )
            assert item1.production_stage == ProductionStage.RECEIVED
            assert item1.started_at is None
            print("Backward transition with allow_backward=True succeeded. started_at was cleared.")

            # Parent status should drop back to RECEIVED (lowest of RECEIVED, DESIGNING)
            await db.refresh(order)
            assert order.status == OrderStatus.RECEIVED
            print(f"Parent order status after Item 1 backward transition: {order.status}")

            print("\n=== [8] TESTING ORDER STATUS AUTO-CALCULATION WHEN ITEMS DELIVERED ===")
            # Move items through to DELIVERED
            # Item 1: RECEIVED -> DESIGNING -> EDITING -> COLOR_CORRECTION -> PRINTING -> LAMINATION -> QUALITY_CHECK -> PACKING -> READY -> DELIVERED
            stages_to_run = [
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
            
            for next_stage in stages_to_run:
                item1 = await order_item_service.update_production_stage(db, item1.id, stage=next_stage)

            assert item1.production_stage == ProductionStage.DELIVERED
            assert item1.completed_at is not None
            print(f"Item 1 reached DELIVERED. completed_at: {item1.completed_at}")

            # Parent status should be Item 2's stage (DESIGNING) since it's the lowest remaining non-delivered active item
            await db.refresh(order)
            assert order.status == OrderStatus.DESIGNING
            print(f"Parent order status with Item 1 DELIVERED and Item 2 DESIGNING: {order.status}")

            # Item 2: DESIGNING -> EDITING -> COLOR_CORRECTION -> PRINTING -> LAMINATION -> QUALITY_CHECK -> PACKING -> READY -> DELIVERED
            stages_for_item2 = [
                ProductionStage.EDITING,
                ProductionStage.COLOR_CORRECTION,
                ProductionStage.PRINTING,
                ProductionStage.LAMINATION,
                ProductionStage.QUALITY_CHECK,
                ProductionStage.PACKING,
                ProductionStage.READY,
                ProductionStage.DELIVERED
            ]
            for next_stage in stages_for_item2:
                item2 = await order_item_service.update_production_stage(db, item2.id, stage=next_stage)

            # Every item is DELIVERED, so Order status should become DELIVERED
            await db.refresh(order)
            assert order.status == OrderStatus.DELIVERED
            assert order.delivered_at is not None
            print(f"Both items DELIVERED. Parent order status: {order.status}, delivered_at: {order.delivered_at}")

            print("\n=== [9] TESTING EMPLOYEE ASSIGNMENT & NOTES ===")
            emp_id = uuid.uuid4()
            item1 = await order_item_service.assign_employee(db, item1.id, emp_id)
            assert item1.assigned_employee == emp_id
            print(f"Assigned employee {emp_id} to Item 1.")

            notes = "Printing completed with glossy finish."
            item1 = await order_item_service.update_production_notes(db, item1.id, notes)
            assert item1.production_notes == notes
            print(f"Notes updated for Item 1: {item1.production_notes}")

            print("\n=== [10] TESTING DASHBOARD AGGREGATIONS ===")
            dashboard = await order_item_service.get_production_dashboard(db)
            print("Dashboard statistics retrieved:")
            print(f"- Items delayed: {dashboard['items_delayed']}")
            print(f"- Items ready: {dashboard['items_ready']}")
            print(f"- Items delivered today: {dashboard['items_delivered_today']}")
            print(f"- Items per stage: {dashboard['items_per_stage']}")

            assert dashboard['items_delivered_today'] >= 2
            assert dashboard['items_per_stage']['DELIVERED'] >= 2

            print("\n=== ALL PRODUCTION WORKFLOW TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            print("\nRolling back all test data changes to keep database clean...")
            await db.rollback()
            print("Rollback successful.")


if __name__ == "__main__":
    asyncio.run(test_production_workflow())
