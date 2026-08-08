"""
app/services/lead_providers/web_search/__init__.py

Package entry point for the pluggable web-search layer used by `WebsiteDiscoveryService`.

Importing this package registers every shipped backend, so `get_search_backend()` resolves
after a single `import app.services.lead_providers.web_search`. Concrete backend modules are
imported here for their `@register_search_backend` side effect.

Adding a backend: create a module in this package, decorate the class with
`@register_search_backend`, add one import line below, and set `WEB_SEARCH_BACKEND` to its
key. `WebsiteDiscoveryService` does not change — that is the point of the seam.
"""

from app.services.lead_providers.web_search.base import (
    DEFAULT_SEARCH_BACKEND_KEY,
    SearchBackend,
    SearchBackendError,
    SearchResult,
    get_search_backend,
    list_search_backends,
    register_search_backend,
    registered_search_backend_keys,
)

# Imported for its @register_search_backend side effect.
from app.services.lead_providers.web_search.duckduckgo import (  # noqa: F401
    DuckDuckGoSearchBackend,
)

__all__ = [
    "DEFAULT_SEARCH_BACKEND_KEY",
    "SearchBackend",
    "SearchBackendError",
    "SearchResult",
    "get_search_backend",
    "list_search_backends",
    "register_search_backend",
    "registered_search_backend_keys",
    "DuckDuckGoSearchBackend",
]
