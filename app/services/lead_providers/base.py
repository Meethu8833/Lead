"""
app/services/lead_providers/base.py

This file defines the provider abstraction for lead collection: the abstract
`LeadProvider` port, the `ProviderContext` describing one run's inputs, and the registry
that resolves a provider key to an implementation.

Under Clean Architecture the ABC here is the *port*: `LeadImportService` depends on this
interface and never on a concrete source. Google Maps, Justdial, Facebook, Instagram,
IndiaMART, wedding directories and CSV are *adapters* — sibling modules implementing this
interface and registering themselves. Adding one is a new file plus a `register_provider`
call; no existing file changes, which is the extensibility requirement this module exists
to satisfy.

The three-method contract
-------------------------
`search(query)` — record the intent to collect, and validate that this provider can service
the request at all (a search provider needs a query; the CSV provider needs a file). It
returns a `ProviderContext`, so an invalid request fails before a job is marked RUNNING.

`collect()` — obtain raw records from the source. This is the only method that touches the
outside world, and therefore the only one that is `async`. It returns *raw* provider-shaped
dicts, not normalized leads, so that what the source actually said is preserved for
diagnosis.

`normalize(raw)` — map one raw record onto a `NormalizedLead`. Kept separate from
`collect()` because mapping is the part that differs most between sources and the part
worth testing without any network at all. `collect_normalized()` composes the two and is
what the import service actually calls.

Failure contract
----------------
`normalize` must NOT raise for an ordinary bad record. It returns a `NormalizedLead` whose
`is_valid()` is False, so the run counts one failed record and carries on. Raising is
reserved for source-level faults (bad credentials, source unreachable) which abort the run
and mark the job FAILED. This mirrors the failure contract already established for
`WhatsAppProvider` in app/services/whatsapp_provider.py.

Scraping
--------
No adapter in this codebase performs real scraping. The concrete adapters shipped here are
`MockLeadProvider` (deterministic fixtures) and `CsvLeadProvider` (operator-supplied file).
The remaining sources are declared as `PlannedProvider` subclasses so that they are
discoverable, listed by the API, and validated against — but refuse to run until a real,
compliant integration is implemented behind them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.core.exceptions import BadRequestException
from app.services.lead_providers.normalized import NormalizedLead

logger = logging.getLogger(__name__)


class ProviderCollectionError(Exception):
    """
    Raised by an adapter for a source-level fault that invalidates the whole run —
    unreachable source, rejected credentials, malformed file that cannot be parsed at all.

    The import service catches this, marks the job FAILED with the message, and stops.
    Per-record problems must NOT use this; they are reported through
    `NormalizedLead.is_valid()` so the rest of the run survives them.
    """


@dataclass
class ProviderContext:
    """
    The validated inputs of one collection run.

    Produced by `search()` and handed back to `collect()`. It exists so that a provider is
    stateless between runs in everything that matters: two concurrent imports through the
    same provider instance cannot read each other's query.

    Attributes:
        query: The search term, for query-driven providers.
        limit: Maximum number of records to collect. Providers must honour this so an
            operator cannot accidentally pull an unbounded scrape into the CRM.
        city / state: Optional geographic narrowing, passed through to sources that
            support it and used as a fallback when a record omits its own location.
        file_content: Raw bytes of an uploaded file, for file-based providers.
        filename: Original name of that file, recorded on the job.
        options: Free-form per-provider extras, so an adapter can accept a parameter no
            other adapter has without widening this dataclass.
    """
    query: str | None = None
    limit: int = 100
    city: str | None = None
    state: str | None = None
    file_content: bytes | None = None
    filename: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


class LeadProvider(ABC):
    """
    Abstract base class every lead-collection adapter must implement.

    Implementations must be safe to construct once and reuse: the import service resolves
    a provider per run, and all run-specific state travels in the `ProviderContext` rather
    than on the instance.
    """

    #: Short stable registry key for this adapter, recorded on the ImportJob's `provider`
    #: column. Must be unique across all registered providers.
    key: str = "abstract"

    #: Human-readable name, for the provider-listing endpoint.
    display_name: str = "Abstract Provider"

    #: The `LeadSource` enum member (by value) that leads from this provider are tagged
    #: with. A string rather than the enum itself so a provider module never has to import
    #: the ORM layer.
    lead_source: str = "OTHER"

    #: Whether this adapter requires a `query`. Search providers do; file providers do not.
    requires_query: bool = True

    #: Whether this adapter requires an uploaded file.
    requires_file: bool = False

    #: Whether this adapter can actually run. `PlannedProvider` sets this False so the
    #: source is discoverable and API-validatable without pretending to be implemented. An
    #: implemented adapter may also compute it — see `GoogleMapsLeadProvider`, which is
    #: unavailable when no API key is configured.
    is_available: bool = True

    @property
    def unavailable_reason(self) -> str:
        """
        Explains why this adapter cannot run, for the 400 raised by `search()` and for the
        provider-listing endpoint.

        Overridable because "cannot run" has more than one cause and the causes have
        different fixes: a planned source needs an implementation, while an implemented one
        may simply need a credential set in the environment. Telling an operator "not yet
        implemented" when the real answer is "set GOOGLE_MAPS_API_KEY" sends them to the
        wrong place entirely.
        """
        return (
            f"Provider '{self.key}' ({self.display_name}) is declared but not yet "
            f"implemented, so it cannot be run."
        )

    def search(self, query: str | None = None, **kwargs: Any) -> ProviderContext:
        """
        Validates a collection request and returns the context `collect()` will run with.

        The default implementation enforces the `requires_query` / `requires_file` flags and
        clamps `limit` to a sane ceiling. Adapters override it only to add their own
        validation, and should call `super().search(...)` to keep the shared checks.

        Raises:
            BadRequestException: the request cannot be serviced by this provider. Raised
                here rather than at collect time so nothing is marked RUNNING first.
        """
        if not self.is_available:
            raise BadRequestException(self.unavailable_reason)

        cleaned_query = query.strip() if isinstance(query, str) else None
        if self.requires_query and not cleaned_query:
            raise BadRequestException(
                f"Provider '{self.key}' requires a non-empty search query."
            )

        file_content = kwargs.get("file_content")
        if self.requires_file and not file_content:
            raise BadRequestException(
                f"Provider '{self.key}' requires an uploaded file."
            )

        # `is None` rather than a falsy check: `limit=0` is an invalid request that must be
        # reported, not silently replaced by the default.
        limit = kwargs.get("limit")
        if limit is None:
            limit = 100
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise BadRequestException("`limit` must be an integer.")
        if limit < 1:
            raise BadRequestException("`limit` must be at least 1.")
        limit = min(limit, MAX_COLLECTION_LIMIT)

        return ProviderContext(
            query=cleaned_query,
            limit=limit,
            city=kwargs.get("city"),
            state=kwargs.get("state"),
            file_content=file_content,
            filename=kwargs.get("filename"),
            options=kwargs.get("options") or {},
        )

    @abstractmethod
    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        """
        Obtains raw records from the source for the given context.

        Returns provider-shaped dicts, deliberately un-normalized, so the untouched source
        record can be attached to a `NormalizedLead.raw` for diagnosis. Must honour
        `context.limit`.

        Raises:
            ProviderCollectionError: source-level fault; the whole run fails.
        """
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        """
        Maps one raw provider record onto the uniform `NormalizedLead` shape.

        Must not raise for a merely bad record — return a record that fails `is_valid()`
        instead, so the run can count it and continue. Implementations should finish by
        returning `lead.normalize()` so cleaning is applied uniformly.
        """
        raise NotImplementedError

    async def collect_normalized(self, context: ProviderContext) -> list[NormalizedLead]:
        """
        Runs `collect()` then `normalize()` over every record, returning the normalized
        batch the import service consumes.

        A `normalize()` implementation that raises despite the contract is contained here:
        the offending record becomes an invalid `NormalizedLead` carrying the exception
        message, so one malformed row cannot abort a two-hundred-record import. The whole
        point of the failed-record counter is that this case is visible rather than fatal.
        """
        raw_records = await self.collect(context)
        normalized: list[NormalizedLead] = []
        for raw in raw_records:
            try:
                normalized.append(self.normalize(raw))
            except Exception as exc:  # noqa: BLE001 - contract containment, see docstring
                logger.warning(
                    "Provider '%s' raised while normalizing a record: %s", self.key, exc
                )
                normalized.append(
                    NormalizedLead(
                        source=self.lead_source,
                        raw={"record": raw, "normalize_error": str(exc)},
                    )
                )
        return normalized

    def describe(self) -> dict[str, Any]:
        """
        Renders this adapter's capabilities, for the provider-listing endpoint. An
        unavailable adapter also carries the reason, so the UI can tell an operator whether
        the fix is a configuration value or a future phase.
        """
        described: dict[str, Any] = {
            "key": self.key,
            "display_name": self.display_name,
            "lead_source": self.lead_source,
            "requires_query": self.requires_query,
            "requires_file": self.requires_file,
            "is_available": self.is_available,
        }
        if not self.is_available:
            described["unavailable_reason"] = self.unavailable_reason
        return described


#: Hard ceiling on records collected in one run, applied in `LeadProvider.search`. A bulk
#: import is a write against the live CRM, so an accidental unbounded pull is a real
#: operational risk; an operator who genuinely wants more runs the import twice.
MAX_COLLECTION_LIMIT = 1000


class PlannedProvider(LeadProvider):
    """
    Base for a source that is part of the plan but has no compliant implementation yet.

    These are registered rather than omitted so that the provider list an operator sees is
    the real roadmap, the API validates provider keys against the full set, and adding the
    real integration later means replacing one class body — not touching the service, the
    endpoints, or the enum.

    `search()` refuses via the `is_available` check, so a request naming one of these gets
    a clear 400 rather than an empty, apparently-successful import. `collect()` is
    implemented only to satisfy the ABC; it is unreachable through the normal path.
    """

    is_available = False

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        raise ProviderCollectionError(
            f"Provider '{self.key}' has no implementation yet."
        )

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        return NormalizedLead(source=self.lead_source, raw=raw).normalize()


# ---------------------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------------------
# Adapters register themselves here at import time. `LeadImportService` resolves providers
# only through `get_provider`, so it has no compile-time knowledge of any concrete source.

_PROVIDER_REGISTRY: dict[str, type[LeadProvider]] = {}


def register_provider(provider_cls: type[LeadProvider]) -> type[LeadProvider]:
    """
    Registers a concrete adapter under its `key`, making it resolvable by `get_provider`.

    Usable as a class decorator. Re-registering the same key overwrites the previous entry,
    which is what makes a test double able to stand in for a real adapter for the duration
    of a test.
    """
    if not provider_cls.key or provider_cls.key == "abstract":
        raise ValueError(
            f"{provider_cls.__name__} must define a unique, non-abstract `key` to be registered."
        )
    _PROVIDER_REGISTRY[provider_cls.key] = provider_cls
    return provider_cls


def get_provider(key: str) -> LeadProvider:
    """
    Resolves a provider adapter by registry key.

    Unlike `get_whatsapp_provider`, an unknown key raises instead of falling back to a
    default. Silently substituting a provider is acceptable when the outcome is a simulated
    message; it is not acceptable when the outcome is writing rows into the CRM under the
    wrong `source` attribution.

    Raises:
        BadRequestException: no adapter is registered under `key`.
    """
    normalized_key = (key or "").strip().lower()
    provider_cls = _PROVIDER_REGISTRY.get(normalized_key)
    if provider_cls is None:
        raise BadRequestException(
            f"Unknown lead provider '{key}'. Registered providers: "
            f"{', '.join(sorted(_PROVIDER_REGISTRY))}."
        )
    return provider_cls()


def list_providers() -> list[dict[str, Any]]:
    """Renders every registered adapter's capabilities, ordered by key."""
    return [_PROVIDER_REGISTRY[key]().describe() for key in sorted(_PROVIDER_REGISTRY)]


def registered_provider_keys() -> list[str]:
    """Returns every registered provider key, for validation and diagnostics."""
    return sorted(_PROVIDER_REGISTRY)
