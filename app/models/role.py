"""
app/models/role.py

Defines the SQLAlchemy model for the Role entity.
Under Clean Architecture, this resides in the Enterprise Domain Model layer.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.permission import Permission


class Role(Base):
    """
    Role database model representing system or custom security roles.
    """
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the role (UUIDv4)"
    )

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique name of the role (e.g. Administrator, Designer)"
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Human-readable description of the role"
    )

    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Flag indicating if this is a built-in system role that cannot be deleted"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp representing when the role was created"
    )

    # Relationships
    employees: Mapped[list["Employee"]] = relationship(
        "Employee",
        back_populates="role",
        doc="Employees assigned to this role"
    )

    permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary="role_permissions",
        back_populates="roles",
        doc="Permissions associated with this role"
    )
