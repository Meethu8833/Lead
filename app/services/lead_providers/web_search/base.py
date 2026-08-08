"""
app/services/lead_providers/web_search/base.py

The **port** for public-web search: `SearchResult`, the `SearchBackend` ABC, its error type,
and the registry that resolves a configured backend key to a class.

Why this is a package of its own
--------------------------------
"Search the web for a business name" and "decide which of these URLs is that business's
official site" are separate concerns with separate failure modes, and they are separated
here: this package knows nothing about leads, and `app/services/website_discovery.py` knows
nothing about HTML SERPs. The seam is `SearchResult` — three strings, no domain types.

That constraint is deliberate and load-bearing. A backend that imported `NormalizedLead`
would make every future backend (Google CSE, Brave, Serper) a lead-aware component and would
make this package untestable without the lead layer. **No lead or database logic belongs in a
backend**: no model, no repository, no session, no scoring, no filtering. A backend answers
"what did the engine say", nothing more.

Why a registry rather than a direct import
------------------------------------------
`WebsiteDiscoveryService` must not name a concrete engine, or swapping engines would edit the
service. It asks `get_search_backend()` for whatever `WEB_SEARCH_BACKEND` names, and adding an
engine is a new module plus a `@register_search_backend` decorator — the same pattern
`lead_providers/base.py` uses for providers, for the same reason.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    """
    One result from a web search: the destination URL plus whatever context the SERP gave.

    Deliberately only the three fields website discovery actually consumes. `title` and
    `snippet` are carried because they are *independent corroborating evidence* during
    validation — a result whose title contains the business name is materially more likely to
    be that business's site than one linked to it only by a fuzzy domain match. Anything
    further (rank metadata, favicons, engine-specific payloads) would be a field one backend
    could populate and others could not, so it is left out.

    Frozen because results are evidence: a scorer must not be able to edit what the engine
    said on its way to a decision.
    """

    url: str
    title: str | None = None
    snippet: str | None = None


class SearchBackendError(Exception):
    """
    Raised when a search could not be *run* — unreachable engine, rejected credential,
    exhausted retries, unparseable response.

    Distinct from "ran and found nothing", which is an empty list. The distinction matters:
    `WebsiteDiscoveryService` returns the lead unchanged either way, but only one of the two
    is an operational fault worth a warning in the logs, and conflating them would hide a
    permanently-broken backend behind what looks like a run of websiteless businesses.
    """


class SearchBackend(ABC):
    """
    Port for a public-web search engine.

    One required method. Everything the caller needs is "give me candidate URLs for this
    query", and keeping the surface at one method is what makes a new engine cheap to add.

    A backend needing a credential it does not have reports `is_available` False rather than
    raising at construction, so an operator can configure one without breaking startup, and
    the service can skip it and leave leads unchanged instead of failing an import.
    """

    key: str = "abstract"
    display_name: str = "Abstract Search Backend"
    requires_credentials: bool = False

    @property
    def is_available(self) -> bool:
        """
        Whether this backend can actually run. Overridden by keyed backends to check their
        credential; the default is True because the shipped default needs nothing.
        """
        return True

    @property
    def unavailable_reason(self) -> str:
        """Explains why this backend cannot run, for logs and `describe()`."""
        return f"Search backend '{self.key}' is not configured."

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        """
        Returns at most `limit` results for `query`, best-ranked first.

        Contract, which every backend must honour and the service relies on:

          * Returns an **empty list** when the engine answered and had nothing. Not an
            exception — "no website exists" is an ordinary outcome, not a fault.
          * Raises **`SearchBackendError`** when the engine could not be consulted at all.
          * Returns **at most `limit`** results. The bound is the caller's, because it is the
            caller that pays for evaluating them.
          * De-duplicates by URL, so a backend cannot inflate its result count with repeats.
        """
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        """Renders this backend's identity and readiness, for diagnostics."""
        described: dict[str, Any] = {
            "key": self.key,
            "display_name": self.display_name,
            "requires_credentials": self.requires_credentials,
            "is_available": self.is_available,
        }
        if not self.is_available:
            described["unavailable_reason"] = self.unavailable_reason
        return described


# ===========================================================================================
# Registry
# ===========================================================================================

_SEARCH_BACKENDS: dict[str, type[SearchBackend]] = {}

_BackendT = TypeVar("_BackendT", bound=type[SearchBackend])


def register_search_backend(cls: _BackendT) -> _BackendT:
    """
    Class decorator registering a backend under its `key`.

    Registration is a decorator rather than a manual dict entry so that a backend cannot be
    written and then silently left unreachable — the declaration and the wiring are the same
    line, in the same file as the class.
    """
    key = (cls.key or "").strip().lower()
    if not key or key == "abstract":
        raise ValueError(f"{cls.__name__} must define a non-empty, non-'abstract' key.")
    if key in _SEARCH_BACKENDS and _SEARCH_BACKENDS[key] is not cls:
        raise ValueError(
            f"Search backend key '{key}' is already registered to "
            f"{_SEARCH_BACKENDS[key].__name__}."
        )
    _SEARCH_BACKENDS[key] = cls
    return cls


def registered_search_backend_keys() -> tuple[str, ...]:
    """Every registered backend key, sorted, for diagnostics and error messages."""
    return tuple(sorted(_SEARCH_BACKENDS))


def get_search_backend(key: str | None = None) -> SearchBackend:
    """
    Resolves a backend by key, defaulting to `settings.WEB_SEARCH_BACKEND`.

    An **unknown key falls back to the default with a warning** rather than raising, which is
    the opposite of `get_provider`'s behaviour and is deliberate. A wrong provider key means
    an operator asked for data we cannot supply and must be told; a wrong search-backend key
    means one *enrichment* step would use a different engine than intended. Since discovery
    writes nothing on its own and a weak result is discarded by the confidence threshold
    anyway, degrading to the free default is strictly better than failing an import run.
    """
    resolved = (key or settings.WEB_SEARCH_BACKEND or "").strip().lower()
    backend_cls = _SEARCH_BACKENDS.get(resolved)
    if backend_cls is None:
        default_cls = _SEARCH_BACKENDS.get(DEFAULT_SEARCH_BACKEND_KEY)
        if default_cls is None:  # pragma: no cover - only if the default is unregistered
            raise SearchBackendError(
                f"No search backend registered under '{resolved}' and the default "
                f"'{DEFAULT_SEARCH_BACKEND_KEY}' is missing. Registered: "
                f"{', '.join(registered_search_backend_keys()) or 'none'}."
            )
        logger.warning(
            "Unknown web-search backend %r; falling back to %r. Registered: %s",
            resolved or "(unset)",
            DEFAULT_SEARCH_BACKEND_KEY,
            ", ".join(registered_search_backend_keys()) or "none",
        )
        backend_cls = default_cls
    return backend_cls()


#: The key of the zero-credential backend every deployment can fall back to. Named here as a
#: constant rather than hardcoded at each use so "what is the default" has one answer.
DEFAULT_SEARCH_BACKEND_KEY = "duckduckgo"


def list_search_backends() -> list[dict[str, Any]]:
    """Describes every registered backend, for a diagnostics endpoint or a CLI."""
    return [_SEARCH_BACKENDS[key]().describe() for key in registered_search_backend_keys()]
