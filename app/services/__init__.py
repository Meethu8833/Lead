"""
app/services/__init__.py

Exposes all service classes.
"""

from app.services.photographer import PhotographerService
from app.services.lead import LeadService
from app.services.lead_activity import LeadActivityService, LeadNoteService
from app.services.order import OrderService
from app.services.product import ProductService
from app.services.order_item import OrderItemService
from app.services.payment import PaymentService
from app.services.invoice import InvoiceService
from app.services.delivery import DeliveryService
from app.services.notification import NotificationService
from app.services.dashboard import DashboardService
from app.services.auth import AuthService
from app.services.employee import EmployeeService
from app.services.cache import permission_cache
from app.services.whatsapp import (
    WhatsAppTemplateService,
    WhatsAppCampaignService,
    CampaignReplyService,
)
from app.services.whatsapp_provider import (
    WhatsAppProvider,
    NoOpWhatsAppProvider,
    ProviderSendResult,
    get_whatsapp_provider,
    register_whatsapp_provider,
)

__all__ = [
    "PhotographerService",
    "LeadService",
    "LeadActivityService",
    "LeadNoteService",
    "OrderService",
    "ProductService",
    "OrderItemService",
    "PaymentService",
    "InvoiceService",
    "DeliveryService",
    "NotificationService",
    "DashboardService",
    "AuthService",
    "EmployeeService",
    "permission_cache",
    "WhatsAppTemplateService",
    "WhatsAppCampaignService",
    "CampaignReplyService",
    "WhatsAppProvider",
    "NoOpWhatsAppProvider",
    "ProviderSendResult",
    "get_whatsapp_provider",
    "register_whatsapp_provider",
]

