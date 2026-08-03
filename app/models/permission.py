"""
app/models/permission.py

Defines the SQLAlchemy model for the Permission entity and the role_permissions association table.
Under Clean Architecture, this resides in the Enterprise Domain Model layer.
"""

import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, Column, ForeignKey, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.role import Role


# Association table for Many-to-Many relationship between Roles and Permissions
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        doc="Reference to the associated Role"
    ),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        doc="Reference to the associated Permission"
    ),
)


class Permission(Base):
    """
    Permission database model representing fine-grained modules and actions.
    Examples:
    - module: "orders", action: "view"
    - module: "payments", action: "create"
    """
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the permission (UUIDv4)"
    )

    module: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Target module (e.g. orders, payments, dashboard, inventory, *)"
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Allowed action (e.g. create, update, delete, view, *)"
    )

    # Relationships
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
        doc="Roles assigned with this permission"
    )

    # Unique constraint to prevent duplicate permission rows
    __table_args__ = (
        UniqueConstraint("module", "action", name="uq_permission_module_action"),
    )
