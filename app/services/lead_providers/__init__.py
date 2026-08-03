"""
app/services/lead_providers/__init__.py

Package entry point for the Lead Collection Engine's provider layer.

Importing this package registers every shipped adapter with the registry in `base.py`, so
`get_provider("csv")` works after a single `import app.services.lead_providers`. The
concrete adapter modules are imported here *for their registration side effect* — that is
why they are imported but not all re-exported, and why the import order does not matter.

Adding a provider: create a module in this package, decorate the class with
`@register_provider`, and add one import line below. Nothing else in the codebase changes.
"""

from app.services.lead_providers.base import (
    LeadProvider,
    PlannedProvider,
    ProviderCollectionError,
    ProviderContext,
    MAX_COLLECTION_LIMIT,
    get_provider,
    list_providers,
    register_provider,
    registered_provider_keys,
)
from app.services.lead_providers.normalized import (
    NormalizedLead,
    normalize_business_key,
    normalize_email,
    normalize_instagram,
    normalize_phone,
    normalize_url,
)

# Imported for their @register_provider side effects.
from app.services.lead_providers.mock import MockLeadProvider  # noqa: F401
from app.services.lead_providers.csv_provider import CsvLeadProvider  # noqa: F401
from app.services.lead_providers.google_maps import GoogleMapsLeadProvider  # noqa: F401
from app.services.lead_providers.instagram import InstagramLeadProvider  # noqa: F401
from app.services.lead_providers import planned  # noqa: F401

__all__ = [
    "LeadProvider",
    "PlannedProvider",
    "ProviderCollectionError",
    "ProviderContext",
    "MAX_COLLECTION_LIMIT",
    "get_provider",
    "list_providers",
    "register_provider",
    "registered_provider_keys",
    "NormalizedLead",
    "normalize_business_key",
    "normalize_email",
    "normalize_instagram",
    "normalize_phone",
    "normalize_url",
    "MockLeadProvider",
    "CsvLeadProvider",
    "GoogleMapsLeadProvider",
    "InstagramLeadProvider",
]
