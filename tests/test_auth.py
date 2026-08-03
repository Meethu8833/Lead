"""
tests/test_auth.py

Integration tests for the hardened Authentication system.
Verifies:
1. Successful logins and token returns.
2. Failed login attempt tracking and account locking.
3. Refresh Token Hashing (tokens stored only as SHA-256).
4. Refresh Token Rotation (RTR) on token exchange.
5. Replay Attack detection (reusing rotated token revokes all sessions).
6. Logout and Logout All.
7. Expired Session Cleanup.
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.exceptions import BadRequestException, UnauthorizedException
from app.models.employee import Employee
from app.models.session import UserSession
from app.models.audit_log import AuditLog, AuditAction
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, LoginRequest
from app.services.auth import AuthService, hash_token, verify_password
from app.services.employee import EmployeeService


async def test_auth_suite():
    print("=== STARTING AUTHENTICATION HARDENING INTEGRATION TESTS ===")

    auth_service = AuthService()
    employee_service = EmployeeService()

    async with AsyncSessionLocal() as db:
        try:
            # 1. SETUP TEST EMPLOYEE
            print("\n--- [1] CREATING TEST EMPLOYEE ---")
            import random
            unique_id = str(uuid.uuid4())[:8]
            email = f"auth_test_{unique_id}@colourlabs.com"
            phone = "".join(random.choices("0123456789", k=10))
            password = "SecurePassword123!"


            # Create employee create schema
            create_schema = EmployeeCreate(
                first_name="AuthTest",
                last_name="Staff",
                email=email,
                phone=phone,
                password=password,
                department="IT",
                designation="Security QA",
                role_id=None
            )
            employee = await employee_service.create_employee(db, create_schema)
            assert employee.id is not None
            assert employee.employee_code.startswith("EMP-")
            print(f"Created employee {employee.email} with code {employee.employee_code}")

            # 2. VERIFY PASSWORD HASHING
            print("\n--- [2] VERIFYING BCRYPT PASSWORD HASHING ---")
            assert employee.password_hash != password
            assert verify_password(password, employee.password_hash) is True
            print("Password successfully hashed and verified.")

            # 3. VERIFY LOGIN SUCCESS & OPAQUE TOKEN HASHING
            print("\n--- [3] VERIFYING LOGIN SUCCESS & OPAQUE TOKEN HASHING ---")
            login_payload = LoginRequest(email=email, password=password)
            tokens = await auth_service.login(db, login_payload, ip_address="127.0.0.1", user_agent="PyTest")
            
            assert tokens.access_token is not None
            assert tokens.refresh_token is not None
            assert tokens.token_type == "bearer"
            print("Received access and refresh tokens.")

            # Verify that the refresh token is stored only as SHA-256
            stored_token_hash = hash_token(tokens.refresh_token)
            stmt = select(UserSession).where(UserSession.token_hash == stored_token_hash)
            res = await db.execute(stmt)
            session = res.scalars().first()
            
            assert session is not None
            assert session.employee_id == employee.id
            assert session.ip_address == "127.0.0.1"
            assert session.user_agent == "PyTest"
            assert session.is_used is False
            print("Refresh token is stored securely as a SHA-256 hash.")

            # Verify we can't find it in plaintext in DB
            stmt_plain = select(UserSession).where(UserSession.token_hash == tokens.refresh_token)
            res_plain = await db.execute(stmt_plain)
            assert res_plain.scalars().first() is None
            print("Plaintext refresh token is never stored.")

            # 4. VERIFY LOGIN FAILED ATTEMPTS AND LOCKOUT
            print("\n--- [4] VERIFYING LOGIN FAILED ATTEMPTS & LOCKOUT ---")
            bad_login = LoginRequest(email=email, password="WrongPassword1!")
            
            # Trigger 4 failures
            for i in range(4):
                try:
                    await auth_service.login(db, bad_login)
                except BadRequestException:
                    pass
            
            # Fetch employee to verify attempts count
            await db.refresh(employee)
            assert employee.failed_login_attempts == 4
            assert employee.lock_until is None
            print(f"Failed attempts correctly incremented to {employee.failed_login_attempts}")

            # 5th failure triggers lockout
            try:
                await auth_service.login(db, bad_login)
            except BadRequestException as ex:
                assert ex.error_code == "INVALID_CREDENTIALS"

            await db.refresh(employee)
            assert employee.failed_login_attempts == 5
            assert employee.lock_until is not None

            print(f"5th failure correctly locked account. Lock until: {employee.lock_until}")

            # Attempting login with CORRECT password must fail due to lock
            try:
                await auth_service.login(db, login_payload)
                assert False, "Should have failed due to account lock"
            except BadRequestException as ex:
                assert ex.error_code == "ACCOUNT_LOCKED"
                print("Locked account blocks correct password login.")

            # Reset lock to continue testing
            await employee_service.update_employee(db, employee.id, EmployeeUpdate(
                is_active=True,
                version=employee.version
            ))
            # Directly clear lock columns in DB for testing
            employee.lock_until = None
            employee.failed_login_attempts = 0
            db.add(employee)
            await db.commit()

            # 5. VERIFY REFRESH TOKEN ROTATION (RTR)
            print("\n--- [5] VERIFYING REFRESH TOKEN ROTATION (RTR) ---")
            # Get clean new tokens
            login_tokens = await auth_service.login(db, login_payload)
            old_refresh = login_tokens.refresh_token
            
            # Perform rotation
            rotated_tokens = await auth_service.refresh(db, old_refresh, ip_address="127.0.0.1")
            assert rotated_tokens.access_token is not None
            assert rotated_tokens.refresh_token is not None
            assert rotated_tokens.refresh_token != old_refresh
            print("Successfully rotated refresh token.")

            # Verify old token session in DB is marked as used and revoked
            old_hash = hash_token(old_refresh)
            stmt = select(UserSession).where(UserSession.token_hash == old_hash)
            res = await db.execute(stmt)
            old_session = res.scalars().first()
            assert old_session.is_used is True
            assert old_session.is_revoked is True
            print("Old refresh token marked as used and revoked.")

            # 6. VERIFY REPLAY ATTACK DETECTION
            print("\n--- [6] VERIFYING REPLAY ATTACK DETECTION ---")
            # Reuse old_refresh token (representing a stolen token replay)
            try:
                await auth_service.refresh(db, old_refresh)
                assert False, "Should have thrown exception on token reuse"
            except UnauthorizedException as ex:
                assert ex.error_code == "TOKEN_REPLAY_DETECTED"
                print("Replay attack successfully blocked.")

            # Verify that ALL sessions for this employee were deleted
            stmt_active = select(UserSession).where(UserSession.employee_id == employee.id)
            res_active = await db.execute(stmt_active)
            active_sessions = res_active.scalars().all()
            assert len(active_sessions) == 0
            print("Replay attack triggered immediate revocation of ALL active sessions.")

            # 7. VERIFY LOGOUT
            print("\n--- [7] VERIFYING LOGOUT ---")
            new_login = await auth_service.login(db, login_payload)
            ref_token = new_login.refresh_token
            
            await auth_service.logout(db, ref_token)
            stmt_logout = select(UserSession).where(UserSession.token_hash == hash_token(ref_token))
            res_logout = await db.execute(stmt_logout)
            assert res_logout.scalars().first() is None
            print("Logout successfully deleted session from DB.")

            # 8. VERIFY LOGOUT ALL
            print("\n--- [8] VERIFYING LOGOUT ALL ---")
            # Create two sessions (multiple devices)
            s1 = await auth_service.login(db, login_payload, device_name="Device 1")
            s2 = await auth_service.login(db, login_payload, device_name="Device 2")
            
            stmt_dev = select(UserSession).where(UserSession.employee_id == employee.id)
            res_dev = await db.execute(stmt_dev)
            assert len(res_dev.scalars().all()) == 2
            print("Multiple device sessions successfully created.")

            # Logout all
            await auth_service.logout_all(db, employee.id)
            
            res_dev_after = await db.execute(stmt_dev)
            assert len(res_dev_after.scalars().all()) == 0
            print("Logout all successfully deleted all device sessions.")

            # 9. VERIFY EXPIRED SESSION CLEANUP
            print("\n--- [9] VERIFYING EXPIRED SESSION CLEANUP ---")
            now = datetime.now(timezone.utc)
            # Add an expired session manually
            expired_session = UserSession(
                employee_id=employee.id,
                token_hash=hash_token(generate_opaque_token()),

                issued_at=now - timedelta(days=10),
                expires_at=now - timedelta(days=3),
                last_used_at=now - timedelta(days=3),
                is_revoked=False,
                is_used=False
            )
            db.add(expired_session)
            await db.commit()

            cleaned = await auth_service.delete_expired_sessions(db)
            assert cleaned == 1
            print("Expired sessions successfully pruned.")

            print("\n=== ALL AUTHENTICATION HARDENING TESTS COMPLETED SUCCESSFULLY ===")

        finally:
            # Clean up/rollback changes
            await db.rollback()
            print("Database transaction rolled back successfully.")


def generate_opaque_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    asyncio.run(test_auth_suite())
