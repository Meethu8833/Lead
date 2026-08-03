"""
app/schemas/role.py

Defines the Pydantic schemas/DTOs for Role and Permission management.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class PermissionBase(BaseModel):
    """
    Base properties of a Permission.
    """
    module: str = Field(..., description="Target module (e.g. orders, inventory)")
    action: str = Field(..., description="Target action (e.g. view, create)")


class PermissionCreate(PermissionBase):
    """
    Schema for creating a Permission.
    """
    pass


class PermissionResponse(PermissionBase):
    """
    Schema for returning a Permission.
    """
    id: uuid.UUID

    class Config:
        from_attributes = True


class RoleBase(BaseModel):
    """
    Base properties of a Role.
    """
    name: str = Field(..., min_length=1, description="Name of the role")
    description: str | None = Field(None, description="Description of the role")
    is_system: bool = Field(False, description="System role flag")


class RoleCreate(RoleBase):
    """
    Schema for creating a Role.
    """
    pass


class RoleUpdate(BaseModel):
    """
    Schema for updating a Role.
    """
    name: str | None = Field(None, min_length=1)
    description: str | None = Field(None)
    permissions: list[uuid.UUID] | None = Field(None, description="List of Permission UUIDs to map to this role")


class RoleResponse(RoleBase):
    """
    Schema for returning a Role.
    """
    id: uuid.UUID
    created_at: datetime
    permissions: list[PermissionResponse] = []

    class Config:
        from_attributes = True
