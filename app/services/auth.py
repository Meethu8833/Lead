"""
app/services/auth.py

Defines the Authentication service implementation.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import uuid
import secrets
import hashlib
import logging
import jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.exceptions import UnauthorizedException, BadRequestException
from app.models.employee import Employee
from app.models.session import UserSession
from app.models.audit_log import AuditLog, AuditAction
from app.schemas.employee import LoginRequest, TokenResponse
from app.repositories.employee import EmployeeRepository

logger = logging.getLogger(__name__)


# ==========================
# SECURE PASSWORD UTILITIES (BCRYPT)
# ==========================

import bcrypt

def hash_password(password: str) -> str:
    """
    Hashes a plain text password using bcrypt.
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain text password against a bcrypt hash.
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# ==========================
# SECURE TOKEN UTILITIES
# ==========================

def create_access_token(employee_id: uuid.UUID, expires_delta: timedelta = None) -> str:
    """
    Generates a JWT access token for an employee.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": str(employee_id),
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """
    Decodes and validates a JWT access token.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def generate_opaque_token() -> str:
    """
    Generates an opaque, high-entropy random refresh token.
    Provides at least 256 bits of entropy.
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """
    Hashes a token using SHA-256. Used for storing refresh tokens securely.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ==========================
# AUTHENTICATION SERVICE
# ==========================

class AuthService:
    """
    Service class handling Employee login, session management, logout, and token rotation.
    """

    def __init__(self, employee_repo: EmployeeRepository | None = None) -> None:
        self.employee_repo = employee_repo or EmployeeRepository()

    async def login(
        self,
        db: AsyncSession,
        payload: LoginRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> TokenResponse:
        """
        Handles Employee login.
        Includes failed login attempts tracking, lockouts, and auditing.
        """
        now = datetime.now(timezone.utc)
        employee = await self.employee_repo.get_by_email(db, payload.email)

        # 1. Handle Account Lockout Check
        if employee and employee.lock_until and employee.lock_until > now:
            minutes_left = int((employee.lock_until - now).total_seconds() / 60) + 1
            await self._audit_auth(
                db,
                employee_id=employee.id,
                email=payload.email,
                action=AuditAction.LOGIN_FAILURE,
                reason=f"Account locked out. Remaining: {minutes_left} mins",
                ip_address=ip_address,
                user_agent=user_agent
            )
            raise BadRequestException(
                f"Account is temporarily locked due to multiple failed login attempts. Try again in {minutes_left} minutes.",
                error_code="ACCOUNT_LOCKED"
            )

        # 2. Verify Credentials
        if not employee or not verify_password(payload.password, employee.password_hash) or not employee.is_active:
            # Handle failure
            if employee and employee.is_active:
                # Update failed attempts
                failed_attempts = employee.failed_login_attempts + 1
                lock_until = None
                if failed_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                    lock_until = now + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
                    logger.warning(f"Locking account {employee.email} due to excessive failures.")

                await self.employee_repo.update(
                    db,
                    employee,
                    {
                        "failed_login_attempts": failed_attempts,
                        "last_failed_login": now,
                        "lock_until": lock_until
                    }
                )
                
                await self._audit_auth(
                    db,
                    employee_id=employee.id,
                    email=employee.email,
                    action=AuditAction.LOGIN_FAILURE,
                    reason="Invalid password. Attempt count: " + str(failed_attempts),
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            else:
                # Audit log for non-existent or inactive user
                await self._audit_auth(
                    db,
                    employee_id=uuid.UUID(int=0),
                    email=payload.email,
                    action=AuditAction.LOGIN_FAILURE,
                    reason="Invalid credentials or account inactive.",
                    ip_address=ip_address,
                    user_agent=user_agent
                )

            raise BadRequestException("Invalid email or password.", error_code="INVALID_CREDENTIALS")

        # 3. Successful Login: Reset attempts and generate tokens
        await self.employee_repo.update(
            db,
            employee,
            {
                "failed_login_attempts": 0,
                "last_failed_login": None,
                "lock_until": None,
                "last_login": now
            }
        )

        access_token = create_access_token(employee.id)
        raw_refresh_token = generate_opaque_token()
        token_hash = hash_token(raw_refresh_token)

        # 4. Save Session
        session = UserSession(
            employee_id=employee.id,
            token_hash=token_hash,
            issued_at=now,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            last_used_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            is_revoked=False,
            is_used=False
        )
        await self.employee_repo.create_session(db, session)

        await self._audit_auth(
            db,
            employee_id=employee.id,
            email=employee.email,
            action=AuditAction.LOGIN_SUCCESS,
            reason="Login successful",
            ip_address=ip_address,
            user_agent=user_agent
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer"
        )

    async def refresh(
        self,
        db: AsyncSession,
        refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse:
        """
        Refreshes access and refresh tokens (RTR).
        Detects replay attacks and revokes all active sessions for that employee.
        """
        now = datetime.now(timezone.utc)
        incoming_hash = hash_token(refresh_token)

        # 1. Fetch Session
        session = await self.employee_repo.get_session_by_hash(db, incoming_hash)
        if not session:
            logger.warning("Attempt to refresh with non-existent or invalid refresh token.")
            raise UnauthorizedException("Invalid refresh token.", error_code="INVALID_REFRESH_TOKEN")

        # 2. Check for Replay Attack
        if session.is_used or session.is_revoked or session.expires_at < now:
            if session.is_used or session.is_revoked:
                # Possible replay attack! Revoke all sessions for this employee
                logger.critical(
                    f"Possible refresh token reuse/replay attack detected! Revoking all sessions for employee {session.employee_id}."
                )
                await self.employee_repo.delete_all_sessions_for_employee(db, session.employee_id)
                
                # Fetch employee details to audit
                employee = await self.employee_repo.get_by_id(db, session.employee_id)
                email = employee.email if employee else "UNKNOWN"
                await self._audit_auth(
                    db,
                    employee_id=session.employee_id,
                    email=email,
                    action=AuditAction.LOGIN_FAILURE,
                    reason="Replay attack detected. Revoked all active sessions.",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                # Invalidate permission cache
                from app.services.cache import permission_cache
                await permission_cache.invalidate_employee(session.employee_id)
                
                raise UnauthorizedException(
                    "Token reuse detected. All active sessions have been revoked for security.",
                    error_code="TOKEN_REPLAY_DETECTED"
                )
            
            # Simple expired token
            logger.info(f"Session {session.id} expired.")
            await self.employee_repo.delete_session(db, session)
            raise UnauthorizedException("Refresh token has expired.", error_code="REFRESH_TOKEN_EXPIRED")

        # 3. Mark old session as used & revoked (so it cannot be used again)
        session.is_used = True
        session.is_revoked = True
        session.last_used_at = now
        await self.employee_repo.update_session(db, session)

        # 4. Create new rotated pair
        access_token = create_access_token(session.employee_id)
        raw_refresh_token = generate_opaque_token()
        new_token_hash = hash_token(raw_refresh_token)

        new_session = UserSession(
            employee_id=session.employee_id,
            token_hash=new_token_hash,
            issued_at=now,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            last_used_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=session.device_name,
            is_revoked=False,
            is_used=False
        )
        await self.employee_repo.create_session(db, new_session)

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer"
        )

    async def logout(self, db: AsyncSession, refresh_token: str, ip_address: str | None = None, user_agent: str | None = None) -> None:
        """
        Invalidates a specific session by refresh token.
        """
        incoming_hash = hash_token(refresh_token)
        session = await self.employee_repo.get_session_by_hash(db, incoming_hash)
        if session:
            employee = await self.employee_repo.get_by_id(db, session.employee_id)
            email = employee.email if employee else "UNKNOWN"

            await self.employee_repo.delete_session(db, session)
            
            await self._audit_auth(
                db,
                employee_id=session.employee_id,
                email=email,
                action=AuditAction.LOGOUT,
                reason="Logout successful",
                ip_address=ip_address,
                user_agent=user_agent
            )

    async def logout_all(self, db: AsyncSession, employee_id: uuid.UUID, ip_address: str | None = None, user_agent: str | None = None) -> None:
        """
        Invalidates all sessions for an employee.
        """
        employee = await self.employee_repo.get_by_id(db, employee_id)
        email = employee.email if employee else "UNKNOWN"

        await self.employee_repo.delete_all_sessions_for_employee(db, employee_id)

        await self._audit_auth(
            db,
            employee_id=employee_id,
            email=email,
            action=AuditAction.LOGOUT,
            reason="Logged out of all devices",
            ip_address=ip_address,
            user_agent=user_agent
        )

        # Invalidate permission cache
        from app.services.cache import permission_cache
        await permission_cache.invalidate_employee(employee_id)

    async def delete_expired_sessions(self, db: AsyncSession) -> int:
        """
        Cleans up expired or revoked sessions from the database.
        """
        return await self.employee_repo.delete_expired_sessions(db)

    # ==========================
    # AUDITING HELPER
    # ==========================

    async def _audit_auth(
        self,
        db: AsyncSession,
        employee_id: uuid.UUID,
        email: str,
        action: AuditAction,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> None:
        """
        Internal helper to write auth-related events to the database AuditLog.
        """
        audit = AuditLog(
            entity_name="Employee",
            entity_id=employee_id,
            action=action,
            performed_by=email,
            old_values=None,
            new_values={"event_reason": reason, "email": email},
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(audit)
        await db.commit()
