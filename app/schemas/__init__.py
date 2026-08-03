"""
app/schemas/__init__.py

Exposes schemas for use across the application.
"""

from app.schemas.photographer import (
    PhotographerCreate,
    PhotographerUpdate,
    PhotographerResponse,
)
from app.schemas.order import (
    OrderCreate,
    OrderResponse,
    OrderUpdate,
)
from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.schemas.order_item import (
    OrderItemCreate,
    OrderItemResponse,
    OrderItemUpdate,
)
from app.schemas.payment import (
    PaymentCreate,
    PaymentUpdate,
    PaymentResponse,
)
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceUpdate,
    InvoiceResponse,
)
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryUpdate,
    DeliveryResponse,
)
from app.schemas.notification import (
    NotificationLogResponse,
)
from app.schemas.dashboard import (
    DashboardStatsResponse,
)
from app.schemas.search import GlobalSearchResponse
from app.schemas.attachment import (
    AttachmentCreate,
    AttachmentResponse,
)
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryItemResponse,
    InventoryTransactionCreate,
    InventoryTransactionResponse,
)
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeUpdate,
    EmployeeResponse,
    LoginRequest,
    TokenResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    PhoneUpdateRequest,
    EmailUpdateRequest,
)
from app.schemas.role import (
    RoleCreate,
    RoleUpdate,
    RoleResponse,
    PermissionCreate,
    PermissionResponse,
)

__all__ = [
    "PhotographerCreate",
    "PhotographerUpdate",
    "PhotographerResponse",
    "OrderCreate",
    "OrderResponse",
    "OrderUpdate",
    "ProductCreate",
    "ProductResponse",
    "ProductUpdate",
    "OrderItemCreate",
    "OrderItemResponse",
    "OrderItemUpdate",
    "PaymentCreate",
    "PaymentUpdate",
    "PaymentResponse",
    "InvoiceCreate",
    "InvoiceUpdate",
    "InvoiceResponse",
    "DeliveryCreate",
    "DeliveryUpdate",
    "DeliveryResponse",
    "NotificationLogResponse",
    "DashboardStatsResponse",
    "GlobalSearchResponse",
    "AttachmentCreate",
    "AttachmentResponse",
    "InventoryItemCreate",
    "InventoryItemUpdate",
    "InventoryItemResponse",
    "InventoryTransactionCreate",
    "InventoryTransactionResponse",
    "EmployeeCreate",
    "EmployeeUpdate",
    "EmployeeResponse",
    "LoginRequest",
    "TokenResponse",
    "ChangePasswordRequest",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "PhoneUpdateRequest",
    "EmailUpdateRequest",
    "RoleCreate",
    "RoleUpdate",
    "RoleResponse",
    "PermissionCreate",
    "PermissionResponse",
]
