"""
app/models/__init__.py

Exposes all database models to SQLAlchemy and Alembic.
Importing models here registers them on the DeclarativeBase 'Base' class metadata.
"""

from app.models.photographer import Photographer
from app.models.order import Order, OrderStatus, PaymentStatus
from app.models.product import Product
from app.models.order_item import OrderItem, ProductionStage
from app.models.payment import Payment, PaymentMethod
from app.models.invoice import Invoice, InvoiceStatus
from app.models.delivery import Delivery, DeliveryMethod, DeliveryStatus
from app.models.notification import NotificationLog, NotificationType, NotificationChannel, NotificationStatus
from app.models.audit_log import AuditLog, AuditAction
from app.models.inventory import InventoryItem, InventoryTransaction, InventoryTransactionType
from app.models.attachment import Attachment
from app.models.role import Role
from app.models.permission import Permission, role_permissions
from app.models.employee import Employee
from app.models.session import UserSession

__all__ = [
    "Photographer",
    "Order",
    "OrderStatus",
    "PaymentStatus",
    "Product",
    "OrderItem",
    "ProductionStage",
    "Payment",
    "PaymentMethod",
    "Invoice",
    "InvoiceStatus",
    "Delivery",
    "DeliveryMethod",
    "DeliveryStatus",
    "NotificationLog",
    "NotificationType",
    "NotificationChannel",
    "NotificationStatus",
    "AuditLog",
    "AuditAction",
    "InventoryItem",
    "InventoryTransaction",
    "InventoryTransactionType",
    "Attachment",
    "Role",
    "Permission",
    "role_permissions",
    "Employee",
    "UserSession",
]


