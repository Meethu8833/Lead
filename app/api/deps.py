"""
app/api/deps.py

This file contains dependency injection provider functions for the FastAPI application.
FastAPI's dependency injection system manages resource lifecycles (like database sessions),
enables decoupling, makes testing simpler (by allowing dependency overrides), and keeps
routing functions lightweight.
"""

from typing import AsyncGenerator
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal


# 1. Database Session Dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function that yields a database session.
    It guarantees that:
    - An independent database session is opened per request.
    - If no exception occurs, the transaction is committed (optional but clean).
    - If an error is raised during the request lifecycle, the transaction is rolled back.
    - The database session is always closed at the end of the request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # We don't commit automatically for writing endpoints (which should commit explicitly),
            # but yielding ensures database transaction scopes are tied to request scopes.
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# 2. Advanced Dependency Injection Example (Service Pattern)
# This showcases nested dependency injection in FastAPI.

class MockCRMService:
    """
    A mock business logic service class.
    Shows how a service layer class can be injected with a database session
    and then injected into endpoint handlers, separating business logic from routes.
    """
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_crm_diagnostics(self) -> dict:
        """
        Mock database-dependent service function.
        """
        # In a real service, you would query the database using `self.db`
        # e.g., result = await self.db.execute(select(Photographer))
        return {
            "service_name": "Colour Labs CRM Core Service",
            "active_connections": 1,
            "system_integrity": "Excellent",
            "db_session_id": id(self.db),  # Demonstrates a session exists and is isolated
        }


async def get_crm_service(db: AsyncSession = Depends(get_db)) -> MockCRMService:
    """
    Dependency provider function that constructs MockCRMService.
    This demonstrates dependency chaining: Endpoint -> Depends(get_crm_service) -> Depends(get_db).
    """
    return MockCRMService(db)


from app.services.photographer import PhotographerService
from app.services.order import OrderService
from app.services.product import ProductService
from app.services.order_item import OrderItemService
from app.services.payment import PaymentService
from app.services.invoice import InvoiceService
from app.services.delivery import DeliveryService
from app.services.notification import NotificationService
from app.services.dashboard import DashboardService


async def get_photographer_service() -> PhotographerService:
    """
    Dependency provider function that constructs PhotographerService.
    """
    return PhotographerService()


async def get_order_service() -> OrderService:
    """
    Dependency provider function that constructs OrderService.
    """
    return OrderService()


async def get_product_service() -> ProductService:
    """
    Dependency provider function that constructs ProductService.
    """
    return ProductService()


async def get_order_item_service() -> OrderItemService:
    """
    Dependency provider function that constructs OrderItemService.
    """
    return OrderItemService()


async def get_payment_service() -> PaymentService:
    """
    Dependency provider function that constructs PaymentService.
    """
    return PaymentService()


async def get_invoice_service() -> InvoiceService:
    """
    Dependency provider function that constructs InvoiceService.
    """
    return InvoiceService()


async def get_delivery_service() -> DeliveryService:
    """
    Dependency provider function that constructs DeliveryService.
    """
    return DeliveryService()


async def get_notification_service() -> NotificationService:
    """
    Dependency provider function that constructs NotificationService.
    """
    return NotificationService()


async def get_dashboard_service() -> DashboardService:
    """
    Dependency provider function that constructs DashboardService.
    """
    return DashboardService()


from app.services.inventory import InventoryService

async def get_inventory_service() -> InventoryService:
    """
    Dependency provider function that constructs InventoryService.
    """
    return InventoryService()


from app.services.attachment import AttachmentService

async def get_attachment_service() -> AttachmentService:
    """
    Dependency provider function that constructs AttachmentService.
    """
    return AttachmentService()


from app.services.search import SearchService

async def get_search_service() -> SearchService:
    """
    Dependency provider function that constructs SearchService.
    """
    return SearchService()


import uuid
from app.models.employee import Employee
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.services.auth import decode_access_token
from app.services.cache import permission_cache
from app.services.employee import EmployeeService
from app.services.auth import AuthService

async def get_auth_service() -> AuthService:
    return AuthService()

async def get_employee_service() -> EmployeeService:
    return EmployeeService()

async def get_current_employee(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None, alias="Authorization"),
    employee_service: EmployeeService = Depends(get_employee_service),
) -> Employee:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Missing or invalid authorization header.")
    
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise UnauthorizedException("Invalid or expired access token.")
    
    employee_id_str = payload.get("sub")
    if not employee_id_str:
        raise UnauthorizedException("Invalid access token subject.")
        
    try:
        employee_id = uuid.UUID(employee_id_str)
    except ValueError:
        raise UnauthorizedException("Invalid access token subject format.")
        
    employee = await employee_service.get_employee_by_id(db, employee_id)
    if not employee:
        raise UnauthorizedException("Employee not found.")
    if not employee.is_active:
        raise UnauthorizedException("Employee account is inactive.")
        
    return employee


class RequirePermission:
    """
    FastAPI dependency that validates if the current employee has the requested permission.
    First checks PermissionCache, falls back to Database on cache miss.
    Supports wildcards (e.g. orders:view matches orders:* or *:*) and Administrator bypass.
    """
    def __init__(self, permission_str: str) -> None:
        self.permission_str = permission_str

    async def __call__(
        self,
        db: AsyncSession = Depends(get_db),
        current_employee: Employee = Depends(get_current_employee),
        employee_service: EmployeeService = Depends(get_employee_service),
    ) -> Employee:
        from app.models.role import Role
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        # Refresh employee with role loaded eager
        stmt = select(Employee).options(selectinload(Employee.role)).where(Employee.id == current_employee.id)
        res = await db.execute(stmt)
        emp_with_role = res.scalars().first()
        if not emp_with_role:
            raise UnauthorizedException("Employee profile not found.")
            
        role = emp_with_role.role
        if role and (role.name == "Administrator" or role.is_system):
            return emp_with_role

        # Check Cache
        cached_perms = await permission_cache.get_permissions(current_employee.id)
        if cached_perms is None:
            # Cache miss: load from DB
            role_id, db_perms = await employee_service.get_permissions_from_db(db, current_employee.id)
            await permission_cache.set_permissions(current_employee.id, role_id, db_perms)
            cached_perms = db_perms

        # Validate Permission with Wildcard Support
        req_module, req_action = self.permission_str.split(":")
        has_perm = False
        for perm in cached_perms:
            try:
                p_module, p_action = perm.split(":")
            except ValueError:
                continue
            
            module_match = (p_module == "*" or p_module == req_module)
            action_match = (p_action == "*" or p_action == req_action)
            if module_match and action_match:
                has_perm = True
                break

        if not has_perm:
            raise ForbiddenException(f"Missing required permission: '{self.permission_str}'.")

        return emp_with_role



