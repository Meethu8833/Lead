"""
tests/test_audit.py

Integration tests for the generic AuditLog module.
Verifies that:
1. Insert, Update, and Delete operations on core entities automatically generate AuditLog entries.
2. The user context (IP, User Agent, Performed By) is correctly captured via ContextVar.
3. old_values and new_values JSONB columns capture the correct delta.
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.context import audit_context
from app.models.photographer import Photographer, LeadStatus
from app.models.audit_log import AuditLog, AuditAction
from app.services.photographer import PhotographerService


async def test_audit_logs():
    print("=== STARTING AUDIT LOG INTEGRATION TESTS ===")
    
    # 1. Initialize context variables to simulate request metadata
    user_id = str(uuid.uuid4())
    audit_context.set({
        "user_id": user_id,
        "ip_address": "192.168.1.100",
        "user_agent": "Mozilla/5.0 (Test Agent)"
    })

    service = PhotographerService()

    async with AsyncSessionLocal() as db:
        try:
            print("\n--- [1] TESTING CREATE AUDIT LOG ---")
            import random
            unique_phone = "".join(random.choices("0123456789", k=10))
            # Create a photographer using service
            from app.schemas.photographer import PhotographerCreate
            schema = PhotographerCreate(
                name="Audit Test Photographer",
                studio_name="Audit Studio",
                phone=unique_phone,
                email="audit_test@studio.com",
                city="Audit City",
                category="REGULAR"
            )
            
            photographer = await service.create_photographer(db, schema)
            
            # Fetch audit logs matching this photographer ID
            query = select(AuditLog).where(AuditLog.entity_id == photographer.id).order_by(AuditLog.created_at.desc())
            result = await db.execute(query)
            logs = result.scalars().all()
            
            assert len(logs) == 1
            create_log = logs[0]
            assert create_log.entity_name == "Photographer"
            assert create_log.action == AuditAction.CREATE
            assert create_log.performed_by == user_id
            assert create_log.ip_address == "192.168.1.100"
            assert create_log.user_agent == "Mozilla/5.0 (Test Agent)"
            assert create_log.old_values is None
            assert create_log.new_values is not None
            assert create_log.new_values["name"] == "Audit Test Photographer"
            print("Create audit log successfully verified!")

            print("\n--- [2] TESTING UPDATE AUDIT LOG ---")
            from app.schemas.photographer import PhotographerUpdate
            update_schema = PhotographerUpdate(
                studio_name="Audit Studio Updated",
                version=photographer.version
            )
            await service.update_photographer(db, photographer.id, update_schema)
            
            # Fetch audit logs matching this photographer ID
            result = await db.execute(query)
            logs = result.scalars().all()
            
            # Should have 2 logs now (Update is newest)
            assert len(logs) == 2
            update_log = logs[0]
            assert update_log.action == AuditAction.UPDATE
            assert update_log.old_values["studio_name"] == "Audit Studio"
            assert update_log.new_values["studio_name"] == "Audit Studio Updated"
            print("Update audit log successfully verified!")

            print("\n--- [3] TESTING DELETE AUDIT LOG ---")
            await service.delete_photographer(db, photographer.id)
            
            # Fetch audit logs matching this photographer ID
            # Note: We soft-delete, which updates is_deleted and deleted_at
            result = await db.execute(query)
            logs = result.scalars().all()
            
            # Soft-delete is technically an UPDATE to is_deleted
            assert len(logs) >= 3
            delete_log = logs[0]
            assert delete_log.action == AuditAction.DELETE
            assert delete_log.new_values["is_deleted"] is True
            print("Soft-delete audit log successfully verified!")

            print("\n=== ALL AUDIT LOG INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        finally:
            # Roll back all changes to keep database clean
            await db.rollback()
            print("Database transaction rolled back.")


if __name__ == "__main__":
    asyncio.run(test_audit_logs())
