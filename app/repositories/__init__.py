"""
app/repositories/__init__.py

Exposes all repository classes.
"""

from app.repositories.photographer import PhotographerRepository
from app.repositories.lead import LeadRepository, AdminLeadRepository
from app.repositories.lead_activity import LeadActivityRepository, LeadNoteRepository, AdminLeadNoteRepository
from app.repositories.order import OrderRepository
from app.repositories.product import ProductRepository
from app.repositories.order_item import OrderItemRepository
from app.repositories.payment import PaymentRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.delivery import DeliveryRepository
from app.repositories.notification import NotificationRepository
from app.repositories.inventory import InventoryItemRepository, InventoryTransactionRepository
from app.repositories.attachment import AttachmentRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.role import RoleRepository
from app.repositories.whatsapp import (
    WhatsAppTemplateRepository,
    AdminWhatsAppTemplateRepository,
    WhatsAppCampaignRepository,
    AdminWhatsAppCampaignRepository,
    CampaignRecipientRepository,
)

__all__ = [
    "PhotographerRepository",
    "LeadRepository",
    "AdminLeadRepository",
    "LeadActivityRepository",
    "LeadNoteRepository",
    "AdminLeadNoteRepository",
    "OrderRepository",
    "ProductRepository",
    "OrderItemRepository",
    "PaymentRepository",
    "InvoiceRepository",
    "DeliveryRepository",
    "NotificationRepository",
    "InventoryItemRepository",
    "InventoryTransactionRepository",
    "AttachmentRepository",
    "EmployeeRepository",
    "RoleRepository",
    "WhatsAppTemplateRepository",
    "AdminWhatsAppTemplateRepository",
    "WhatsAppCampaignRepository",
    "AdminWhatsAppCampaignRepository",
    "CampaignRecipientRepository",
]

