"""
app/core/database.py

This file configures SQLAlchemy 2.0 connection management for PostgreSQL.
It initializes the asynchronous engine and session maker, and defines the declarative
base class that all database models will inherit from.
We use asynchronous engines and sessions (via `asyncpg`) to avoid blocking the main
ASGI thread while waiting for database queries to complete.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

logger = logging.getLogger(__name__)

# 1. Create the Asynchronous Engine
# we disable pool pre-ping (pool_pre_ping=True) to automatically test connections before executing queries.
async_engine = create_async_engine(
    settings.ASYNC_DATABASE_URI,
    echo=False,  # Set to True only when debugging SQL queries locally
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# 2. Create the AsyncSession Factory
# expire_on_commit=False prevents SQLAlchemy from trying to re-fetch loaded objects from database
# after a session commit, which requires synchronous/additional async queries.
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# 3. Base class for all declarative models (SQLAlchemy 2.0 style)
class Base(DeclarativeBase):
    """
    Parent class for database models. Serves as a registry for Alembic and SQLAlchemy.
    """
    pass


# 4. Connection cleanup helper
async def dispose_database_connections() -> None:
    """
    Explicitly disposes the database pool engine, closing active connections.
    Should be called during application shutdown events.
    """
    logger.info("Closing database engine connection pools...")
    await async_engine.dispose()
    logger.info("Database pools safely closed.")
stream = None


# 5. Automated Audit Log Event Listener
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.context import audit_context
from app.models.audit_log import AuditLog, AuditAction
from enum import Enum
from decimal import Decimal
import uuid
from datetime import datetime, date

@event.listens_for(Session, "before_flush")
def receive_before_flush(session, flush_context, instances):
    logs_to_add = []
    
    ctx = audit_context.get()
    performed_by = ctx.get("user_id") if ctx else "SYSTEM"
    ip_address = ctx.get("ip_address") if ctx else None
    user_agent = ctx.get("user_agent") if ctx else None

    # Helper to serialize values
    def serialize_value(val):
        if val is None:
            return None
        if isinstance(val, uuid.UUID):
            return str(val)
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if isinstance(val, Decimal):
            return float(val)
        if isinstance(val, Enum):
            return val.value
        if isinstance(val, (list, dict)):
            return val
        return val

    # Helper to serialize columns
    def serialize_columns(obj, columns_to_serialize=None):
        from sqlalchemy import inspect
        inspected = inspect(obj)
        data = {}
        for attr in inspected.mapper.column_attrs:
            if columns_to_serialize is not None and attr.key not in columns_to_serialize:
                continue
            val = getattr(obj, attr.key)
            data[attr.key] = serialize_value(val)
        return data

    # 1. Process session.new
    for obj in session.new:
        if obj.__class__.__name__ == "AuditLog":
            continue
        entity_name = obj.__class__.__name__
        entity_id = getattr(obj, "id", None)
        if not entity_id:
            entity_id = uuid.uuid4()
            obj.id = entity_id
            
        new_vals = serialize_columns(obj)
        log = AuditLog(
            entity_name=entity_name,
            entity_id=entity_id,
            action=AuditAction.CREATE,
            performed_by=performed_by,
            old_values=None,
            new_values=new_vals,
            ip_address=ip_address,
            user_agent=user_agent
        )
        logs_to_add.append(log)

    # 2. Process session.dirty
    for obj in session.dirty:
        if obj.__class__.__name__ == "AuditLog":
            continue
        entity_name = obj.__class__.__name__
        entity_id = getattr(obj, "id", None)
        if not entity_id:
            continue

        from sqlalchemy import inspect
        inspected = inspect(obj)
        
        old_vals = {}
        new_vals = {}
        has_changes = False
        is_status_change = False
        is_soft_delete = False
        
        status_fields = {"status", "production_stage", "lead_status"}
        
        for attr in inspected.mapper.column_attrs:
            history = inspected.attrs[attr.key].history
            if history.has_changes():
                has_changes = True
                
                # Check status change
                if attr.key in status_fields:
                    is_status_change = True
                    
                # Check soft delete
                if attr.key == "is_deleted" and history.added and history.added[0] is True:
                    is_soft_delete = True

                old_val = history.deleted[0] if history.deleted else None
                new_val = history.added[0] if history.added else None
                
                old_vals[attr.key] = serialize_value(old_val)
                new_vals[attr.key] = serialize_value(new_val)
                
        if has_changes:
            action = AuditAction.UPDATE
            if is_soft_delete:
                action = AuditAction.DELETE
            elif is_status_change:
                action = AuditAction.STATUS_CHANGE
                
            log = AuditLog(
                entity_name=entity_name,
                entity_id=entity_id,
                action=action,
                performed_by=performed_by,
                old_values=old_vals,
                new_values=new_vals,
                ip_address=ip_address,
                user_agent=user_agent
            )
            logs_to_add.append(log)

    # 3. Process session.deleted
    for obj in session.deleted:
        if obj.__class__.__name__ == "AuditLog":
            continue
        entity_name = obj.__class__.__name__
        entity_id = getattr(obj, "id", None)
        if not entity_id:
            continue
            
        old_vals = serialize_columns(obj)
        log = AuditLog(
            entity_name=entity_name,
            entity_id=entity_id,
            action=AuditAction.DELETE,
            performed_by=performed_by,
            old_values=old_vals,
            new_values=None,
            ip_address=ip_address,
            user_agent=user_agent
        )
        logs_to_add.append(log)

    for log in logs_to_add:
        session.add(log)

