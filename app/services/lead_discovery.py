"""
app/services/lead_discovery.py

This file implements `LeadDiscoveryService` — the use case that turns a city name into
saved leads by running the collection pipeline end to end.

The pipeline
------------
    city
      ↓  OverpassLeadProvider          businesses on the map near that city
      ↓  WebsiteDiscoveryService       find the official site of the ones without one
      ↓  ContactExtractorService       visit those sites, read the published contacts
      ↓  ContactNormalizationService   canonicalise phones/emails/handles/URLs
      ↓  LeadDeduplicationService      classify each record: new / merge / duplicate
      ↓  persistence                   insert the new ones, enrich the mergeable ones
    summary

What this class is, and is not
------------------------------
It is **only** an orchestrator. Every stage above already exists as its own service with its
own test suite, and this file contains no scraping, no HTTP, no parsing, no scoring, no
matching rules and no normalisation logic. What it contributes is the *order* of the stages,
the handling of a stage that comes back empty, and the reconciliation of the counters into
one summary.

That constraint is load-bearing rather than stylistic. The moment a matching rule or a
cleanup regex is copied into this file it exists twice — once here and once in the service
that owns it — and the two drift. So the rule for changing this file is: if the change is
about *what a stage does*, it belongs in that stage's module; only a change about *which
stage runs when* belongs here. `test_lead_discovery.py` asserts this structurally, by
checking that this module imports no `httpx`, no `re`-based extraction and no parser.

Dependency injection
--------------------
Every collaborator is a constructor argument defaulting to the real implementation:

    LeadDiscoveryService(
        provider=..., website_discovery=..., contact_extractor=...,
        contact_normalizer=..., deduplication_service=...,
        lead_repository=..., activity_service=...,
    )

Production callers construct it with no arguments and get the shipped pipeline. Tests pass
stubs for the three network-touching stages and drive the whole pipeline offline against a
real database session — which is what makes an integration test of this class possible at
all without a live Overpass endpoint and a live public web.

The stages are injected as *objects*, not resolved from the registry inside the run, for
the same reason `LeadImportService.run_import` accepts a `provider` argument: a service that
reaches out to a global registry mid-run cannot be tested without mutating that global.

Enrichment is best-effort, persistence is not
---------------------------------------------
Discovery and extraction are enrichment stages. Both are specified never to raise — a lead
whose website cannot be found or whose site is unreachable simply passes through unchanged —
so neither can fail a run. This service preserves that: it does not wrap them in a
try/except that would mask a genuine bug, but it also does not treat "no website found" as
a failure. It is not a failure; it is a lead with no website, which is the state it arrived
in.

Persistence is different. A record that cannot be written is a real loss and is counted in
`failed`, with the session rolled back so the remaining records still have a usable
transaction — the same per-record isolation `LeadImportService._process_records` uses, and
for the same reason: one bad row must not cost a run of two hundred.

The summary
-----------
`run()` returns a `DiscoverySummary` whose `to_dict()` is exactly the contract asked for::

    {"found": …, "imported": …, "merged": …, "duplicates": …, "failed": …}

  found       records the provider returned, before any filtering. The denominator.
  imported    new Lead rows written.
  merged      existing leads enriched with at least one previously-empty field.
  duplicates  records that matched an existing lead and added nothing.
  failed      records that could not be stored: invalid (no business name, no phone) or
              a write that raised.

These five always reconcile: `imported + merged + duplicates + failed == found`. That
identity is what makes the summary trustworthy — a record cannot be silently dropped
between two stages without the totals disagreeing, and the integration suite asserts it on
every scenario it runs.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadSource, LeadStatus
from app.repositories.lead import LeadRepository
from app.services.contact_extractor import ContactExtractorService
from app.services.contact_normalization import ContactNormalizationService
from app.services.lead_activity import LeadActivityService
from app.services.lead_deduplication import (
    DeduplicationResult,
    LeadDeduplicationService,
)
from app.services.lead_providers.base import (
    LeadProvider,
    ProviderCollectionError,
    ProviderContext,
    get_provider,
)
from app.services.lead_providers.normalized import NormalizedLead
from app.services.website_discovery import WebsiteDiscoveryService

logger = logging.getLogger(__name__)


#: The provider this pipeline collects from. Overpass rather than Google Places because the
#: pipeline's first stage takes a *city*, which is precisely the input Overpass geocodes,
#: and because it needs no credential — a discovery run must work on a fresh checkout.
DEFAULT_PROVIDER_KEY = "overpass"

#: The query handed to the provider when the caller supplies only a city. Overpass requires
#: a non-empty query (`requires_query = True`) even though its own collection is driven by
#: the geocoded city and its photography tag filter, so this is what makes "city in, leads
#: out" an honest single-argument call rather than something the caller has to know to pad.
DEFAULT_QUERY = "photography"


@dataclass
class StageStats:
    """
    What one enrichment stage did to the batch, for the run's diagnostics.

    Recorded because the stages themselves are silent about aggregate effect — each returns
    leads, not counts — and an operator asking "why did this city yield so few contacts"
    needs to see whether discovery found no sites or extraction found no details on them.
    Purely informational: nothing in the summary's five counters is derived from it.
    """
    name: str
    records_in: int = 0
    records_enriched: int = 0
    #: Optional per-stage breakdown, e.g. `{"no_contact_found": 3, "robots_blocked": 1}` for
    #: contact extraction. Additive: consumers that only read the three counters above are
    #: unaffected, and a stage that has nothing extra to say omits the key entirely.
    detail: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.name,
            "records_in": self.records_in,
            "records_enriched": self.records_enriched,
        }
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass
class DiscoveredLeadRecord:
    """
    A lead this run created or enriched, captured at the moment it was written.

    Recorded here rather than reconstructed by the caller from `created_lead_ids`. The
    alternative — hand back ids and let the endpoint re-query them — costs a round trip per
    run and, for a merge, cannot recover `enriched_fields` at all: the changes dict only
    exists during planning. Capturing at the write site is the only place all of it is in
    scope at once.
    """

    id: uuid.UUID
    business_name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    website: str | None = None

    #: The contact channels the results table columns. Projected from the written row rather
    #: than from the incoming record, so what the operator sees is what was actually stored —
    #: a merge that declined to overwrite a populated field shows the *kept* value, not the
    #: rejected one.
    whatsapp: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    youtube: str | None = None
    source: str | None = None

    #: Fields this run filled in on an existing lead. Empty for a newly created lead.
    enriched_fields: list[str] = field(default_factory=list)

    @property
    def is_whatsapp_ready(self) -> bool:
        """
        Whether this lead can be messaged on WhatsApp.

        True only when a number is stored in the `whatsapp` column specifically. An ordinary
        `phone` is deliberately *not* treated as a WhatsApp number: the pipeline only
        promotes a number to `whatsapp` when a source said so (a `wa.me` link, a labelled
        WhatsApp number), and assuming otherwise would produce dead conversations.
        """
        return bool(self.whatsapp and self.whatsapp.strip())

    @property
    def contact_quality(self) -> str:
        """
        Priority band for outreach, derived only from what is actually stored.

        HIGH    a reachable number *and* a second channel to verify the business by.
        MEDIUM  a reachable number and nothing else.
        LOW     no number at all — only a website or social presence to work from.
        NONE    nothing actionable.

        Computed, never persisted: it is a view of the other columns, so storing it would
        create a value that silently goes stale the moment one of them changes.
        """
        has_number = bool(
            (self.phone and self.phone.strip()) or (self.whatsapp and self.whatsapp.strip())
        )
        has_web = bool(
            (self.website and self.website.strip()) or (self.email and self.email.strip())
        )
        has_social = bool(
            (self.instagram and self.instagram.strip())
            or (self.facebook and self.facebook.strip())
            or (self.youtube and self.youtube.strip())
        )

        if has_number and (has_web or has_social):
            return "HIGH"
        if has_number:
            return "MEDIUM"
        if has_web or has_social:
            return "LOW"
        return "NONE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "business_name": self.business_name,
            "phone": self.phone,
            "email": self.email,
            "city": self.city,
            "website": self.website,
            "whatsapp": self.whatsapp,
            "instagram": self.instagram,
            "facebook": self.facebook,
            "youtube": self.youtube,
            "source": self.source,
            "is_whatsapp_ready": self.is_whatsapp_ready,
            "contact_quality": self.contact_quality,
            "enriched_fields": list(self.enriched_fields),
        }

    @classmethod
    def from_lead(
        cls, lead: "Lead", enriched_fields: list[str] | None = None
    ) -> "DiscoveredLeadRecord":
        """Projects a written Lead down to the fields the results tables show."""
        source = getattr(lead, "source", None)
        return cls(
            id=lead.id,
            business_name=getattr(lead, "business_name", None),
            phone=getattr(lead, "phone", None),
            email=getattr(lead, "email", None),
            city=getattr(lead, "city", None),
            website=getattr(lead, "website", None),
            whatsapp=getattr(lead, "whatsapp", None),
            instagram=getattr(lead, "instagram", None),
            facebook=getattr(lead, "facebook", None),
            youtube=getattr(lead, "youtube", None),
            # The enum's value, so the payload stays JSON-native and the UI does not have to
            # know about Python enum repr.
            source=getattr(source, "value", source),
            enriched_fields=list(enriched_fields or []),
        )


@dataclass
class DiscoveryFailedRecord:
    """
    A record that could not be stored, with its reason.

    Carries the business name as its own attribute so a table can column it, while
    `to_line()` reproduces the "name: reason" string the summary's `errors` list has always
    held. Both exist because `errors` is asserted on by the existing integration suite.
    """

    reason: str
    business_name: str | None = None

    def to_line(self) -> str:
        return f"{self.business_name or 'record'}: {self.reason}"

    def to_dict(self) -> dict[str, Any]:
        return {"business_name": self.business_name, "reason": self.reason}


@dataclass
class EnrichmentStats:
    """
    How much contact information this run actually landed.

    Every counter here is measured over the leads the run **wrote** — the rows in
    `imported_records` and `merged_records` — not over what a stage claimed to find. That
    distinction is the whole point: a phone number extracted from a website but then dropped
    because the lead already had one is not a phone number this run delivered, and counting
    it would tell the operator the run achieved something it did not.

    `websites_discovered` and `contacts_extracted` are the exception and come from the stage
    statistics, because they describe work done rather than data stored: a site that was
    found for a lead that later turned out to be a duplicate was still found.

    Nothing here is persisted. These are derived at the end of a run for the response only,
    which is why this phase needs no schema change to report them.
    """

    websites_discovered: int = 0
    contacts_extracted: int = 0
    emails_found: int = 0
    phones_found: int = 0
    whatsapp_found: int = 0
    instagram_found: int = 0
    facebook_found: int = 0
    youtube_found: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "websites_discovered": self.websites_discovered,
            "contacts_extracted": self.contacts_extracted,
            "emails_found": self.emails_found,
            "phones_found": self.phones_found,
            "whatsapp_found": self.whatsapp_found,
            "instagram_found": self.instagram_found,
            "facebook_found": self.facebook_found,
            "youtube_found": self.youtube_found,
        }


@dataclass
class DiscoverySummary:
    """
    The outcome of one discovery run.

    `to_dict()` is the five-key contract this service was specified to return; the extra
    attributes carry the diagnostics that make a surprising number explainable, and are not
    part of that contract.
    """

    found: int = 0
    imported: int = 0
    merged: int = 0
    duplicates: int = 0
    failed: int = 0

    #: The city this run collected for, echoed back so a caller batching several cities can
    #: attribute a summary without tracking it alongside.
    city: str | None = None

    #: Registry key of the provider that produced the records.
    provider: str | None = None

    #: Ids of the leads created, so a caller can immediately act on them (start a WhatsApp
    #: sequence, assign an owner) without re-querying for "leads created just now".
    created_lead_ids: list[uuid.UUID] = field(default_factory=list)

    #: Ids of the existing leads that were enriched.
    merged_lead_ids: list[uuid.UUID] = field(default_factory=list)

    #: The created and enriched leads themselves, captured at their write sites. These
    #: carry what a results table needs; the id lists above remain for callers that only
    #: want to act on ids. Each list stays in step with its counter.
    imported_records: list[DiscoveredLeadRecord] = field(default_factory=list)
    merged_records: list[DiscoveredLeadRecord] = field(default_factory=list)

    #: Structured twin of `errors`. Same failures, split into name and reason so the UI can
    #: column them; `errors` keeps the flat "name: reason" lines its existing consumers read.
    failed_records: list[DiscoveryFailedRecord] = field(default_factory=list)

    #: Per-stage effect, in pipeline order.
    stages: list[StageStats] = field(default_factory=list)

    #: What the run actually collected, counted over the records it wrote.
    enrichment: "EnrichmentStats" = field(default_factory=lambda: EnrichmentStats())

    #: One line per record that could not be stored, with the reason.
    errors: list[str] = field(default_factory=list)

    def record_failure(self, reason: str, business_name: str | None = None) -> None:
        """
        Counts one unstorable record, writing it to both failure views.

        A single entry point because the two must not drift: every `failed` increment has a
        matching line in `errors` and a matching row in `failed_records`, which is what lets
        the response promise that `len(failed_records) == failed`.
        """
        self.failed += 1
        record = DiscoveryFailedRecord(reason=reason, business_name=business_name)
        self.failed_records.append(record)
        self.errors.append(record.to_line())

    @property
    def accounted_for(self) -> int:
        """
        Records that reached a terminal classification. Always equals `found` for a
        completed run — see the module docstring on why that identity matters.
        """
        return self.imported + self.merged + self.duplicates + self.failed

    @property
    def reconciles(self) -> bool:
        """Whether every collected record was accounted for exactly once."""
        return self.accounted_for == self.found

    def to_dict(self) -> dict[str, int]:
        """
        Renders the five-key summary this service's contract specifies.

        Deliberately only those five: the diagnostics above are attributes for a caller that
        wants them, and adding them here would change a documented response shape.
        """
        return {
            "found": self.found,
            "imported": self.imported,
            "merged": self.merged,
            "duplicates": self.duplicates,
            "failed": self.failed,
        }

    def to_detailed_dict(self) -> dict[str, Any]:
        """The summary plus its diagnostics, for logging and a debug endpoint."""
        detailed: dict[str, Any] = dict(self.to_dict())
        detailed.update({
            "city": self.city,
            "provider": self.provider,
            "created_lead_ids": [str(i) for i in self.created_lead_ids],
            "merged_lead_ids": [str(i) for i in self.merged_lead_ids],
            "stages": [s.to_dict() for s in self.stages],
            "errors": list(self.errors),
            "reconciles": self.reconciles,
        })
        return detailed

    def to_response_dict(self) -> dict[str, Any]:
        """
        The five counters plus the record-level detail `DiscoveryRunResponse` serializes.

        Separate from `to_detailed_dict` on purpose: that one is for logs and may carry
        anything useful, while this one is the API projection and changes only the way a
        response model changes. `created_lead_ids` and `merged_lead_ids` are omitted here —
        `imported_records` and `merged_records` carry the same ids with the fields a caller
        actually renders.
        """
        response: dict[str, Any] = dict(self.to_dict())
        response.update({
            "city": self.city,
            "provider": self.provider,
            "imported_records": [r.to_dict() for r in self.imported_records],
            "merged_records": [r.to_dict() for r in self.merged_records],
            "failed_records": [r.to_dict() for r in self.failed_records],
            "stages": [s.to_dict() for s in self.stages],
            "enrichment": self.enrichment.to_dict(),
        })
        return response

    def compute_enrichment(self) -> None:
        """
        Fills `enrichment` by counting over the records this run wrote.

        Called once, after persistence. Counting here rather than incrementing during the
        run is deliberate: the write is the only moment the *stored* value is known, and an
        incremental counter would have to guess whether a merge's proposed value survived
        the never-overwrite rule.
        """
        written = self.imported_records + self.merged_records

        def count(attr: str) -> int:
            total = 0
            for record in written:
                value = getattr(record, attr, None)
                if value and str(value).strip():
                    total += 1
            return total

        stage_enriched = {stage.name: stage.records_enriched for stage in self.stages}

        self.enrichment = EnrichmentStats(
            websites_discovered=stage_enriched.get("website_discovery", 0),
            contacts_extracted=stage_enriched.get("contact_extraction", 0),
            emails_found=count("email"),
            phones_found=count("phone"),
            whatsapp_found=count("whatsapp"),
            instagram_found=count("instagram"),
            facebook_found=count("facebook"),
            youtube_found=count("youtube"),
        )


class LeadDiscoveryService:
    """
    Runs the city → leads pipeline by composing the six stage services.

    Holds no run state: the city, the limit and the batch all travel as arguments, so one
    instance is safe to reuse across concurrent runs. The stage services it holds are
    themselves documented as safe to share, and two of them (the Overpass rate limiter, the
    extractor's per-host limiter) are shared *on purpose* so concurrent runs queue against
    the public endpoints rather than burst.

    Contains no scraping logic. See the module docstring.
    """

    def __init__(
        self,
        provider: LeadProvider | None = None,
        website_discovery: WebsiteDiscoveryService | None = None,
        contact_extractor: ContactExtractorService | None = None,
        contact_normalizer: ContactNormalizationService | None = None,
        deduplication_service: LeadDeduplicationService | None = None,
        lead_repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
        provider_key: str = DEFAULT_PROVIDER_KEY,
    ) -> None:
        """
        Args:
            provider: The collection adapter. Defaults to the registry's Overpass provider.
                Injected in tests and available to a caller that wants a different source —
                the pipeline downstream of collection is provider-agnostic, because every
                adapter returns `NormalizedLead`.
            website_discovery / contact_extractor / contact_normalizer: The three enrichment
                stages. The first two touch the network; injecting stubs is what lets the
                integration suite run the real pipeline offline.
            deduplication_service: Classifies records against the CRM. Reads the database,
                writes nothing.
            lead_repository / activity_service: The persistence stage. The activity service
                is what makes a discovered lead appear on its own timeline, exactly as an
                imported one does.
            provider_key: Registry key resolved when `provider` is not supplied. Resolution
                is deferred to first use rather than done here, so constructing this service
                never depends on provider registration order at import time.
        """
        self._provider = provider
        self._provider_key = provider_key
        self.website_discovery = website_discovery or WebsiteDiscoveryService()
        self.contact_extractor = contact_extractor or ContactExtractorService()
        self.contact_normalizer = contact_normalizer or ContactNormalizationService()
        self.deduplication_service = deduplication_service or LeadDeduplicationService()
        self.lead_repository = lead_repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()

    @property
    def provider(self) -> LeadProvider:
        """
        The collection adapter, resolved from the registry on first use if one was not
        injected. Cached so a run does not construct a new adapter — and therefore a new
        rate limiter — per call, which would defeat the politeness gap entirely.
        """
        if self._provider is None:
            self._provider = get_provider(self._provider_key)
        return self._provider

    # -----------------------------------------------------------------------------------
    # The pipeline
    # -----------------------------------------------------------------------------------

    async def run(
        self,
        db: AsyncSession,
        city: str,
        query: str | None = None,
        limit: int = 100,
        state: str | None = None,
        options: dict[str, Any] | None = None,
        discover_websites: bool = True,
        extract_contacts: bool = True,
    ) -> DiscoverySummary:
        """
        Runs the full pipeline for one city and returns its summary.

        Stages run as whole-batch passes rather than per-record, because that is what lets
        discovery and extraction fan out across leads concurrently (`discover_many` and
        `extract_many` each hold a semaphore) instead of serialising a hundred round trips.

        Args:
            city: The city to collect in. Required — it is the pipeline's only real input,
                and the Overpass provider geocodes it to get coordinates.
            query: Search term. Defaults to `DEFAULT_QUERY` so a caller can pass a city and
                nothing else.
            limit: Maximum records to collect. Clamped by the provider's own ceiling.
            state: Optional geographic narrowing, passed through to the provider.
            options: Free-form per-provider extras — `radius_km` for Overpass.
            discover_websites / extract_contacts: Turn the two network-touching enrichment
                stages off. Exposed because a re-run over a city already enriched pays a
                large latency cost for very little new data, and because an operator on a
                metered connection may want the map data alone.

        Raises:
            BadRequestException: the provider cannot service the request (no city, bad
                radius, unavailable source). Raised before anything is collected or written.
        """
        summary = DiscoverySummary(city=city, provider=self.provider.key)

        # --- Stage 1: collect. `search()` validates first, so a bad request raises here
        # rather than after a partial run.
        context = self.provider.search(
            query or DEFAULT_QUERY,
            limit=limit,
            city=city,
            state=state,
            options=options or {},
        )
        records = await self._collect(context)
        summary.found = len(records)
        summary.stages.append(
            StageStats(name="collect", records_in=len(records), records_enriched=len(records))
        )
        if not records:
            logger.info("Discovery for %r collected no records.", city)
            return summary

        # --- Stage 2: website discovery. Best-effort; leads without a discoverable site
        # pass through unchanged.
        if discover_websites:
            records = await self._discover_websites(records, summary)

        # --- Stage 3: contact extraction from those websites. Also best-effort.
        if extract_contacts:
            records = await self._extract_contacts(records, summary)

        # --- Stage 4: normalization. Canonicalises whatever the previous stages produced,
        # so deduplication compares like with like.
        records = self._normalize(records, summary)

        # --- Stage 5: deduplication. Returns a *plan*; nothing is written yet.
        valid_records, invalid = self._partition_valid(records)
        for failure in invalid:
            summary.record_failure(failure.reason, failure.business_name)

        plan = await self.deduplication_service.deduplicate(db, valid_records)
        summary.stages.append(
            StageStats(
                name="deduplicate",
                records_in=len(valid_records),
                records_enriched=len(plan.new_leads) + len(plan.merged_leads),
            )
        )

        # --- Stage 6: persist the plan.
        await self._persist(db, plan, summary)

        # Counted from the rows actually written, so the reported figures describe stored
        # data rather than attempted enrichment. See `EnrichmentStats`.
        summary.compute_enrichment()

        logger.info(
            "Discovery for %r finished: found=%d imported=%d merged=%d duplicates=%d failed=%d",
            city, summary.found, summary.imported, summary.merged,
            summary.duplicates, summary.failed,
        )
        if not summary.reconciles:
            # Every record must reach exactly one terminal state. A mismatch means a record
            # was lost between two stages — a bug in this file, not in a stage — so it is
            # logged loudly rather than left for someone to notice in a dashboard.
            logger.error(
                "Discovery summary does not reconcile for %r: found=%d accounted=%d",
                city, summary.found, summary.accounted_for,
            )
        return summary

    # -----------------------------------------------------------------------------------
    # Stages
    # -----------------------------------------------------------------------------------

    async def _collect(self, context: ProviderContext) -> list[NormalizedLead]:
        """
        Runs the provider and returns its normalized records.

        A source-level fault is allowed to propagate: unlike an enrichment miss, "the source
        could not be reached" means this run has no data at all, and reporting zero found
        would misrepresent that as "this city has no photographers".
        """
        try:
            return list(await self.provider.collect_normalized(context))
        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter fault, reported as a source fault
            logger.exception("Provider '%s' failed during collection.", self.provider.key)
            raise ProviderCollectionError(
                f"Provider '{self.provider.key}' failed: {exc}"
            ) from exc

    async def _discover_websites(
        self, records: Sequence[NormalizedLead], summary: DiscoverySummary
    ) -> list[NormalizedLead]:
        """
        Fills in the website of records that arrived without one.

        The stage never raises by contract, so there is no try/except here — wrapping it
        would only hide a genuine bug in it behind a silent "enrichment skipped".
        """
        before = sum(1 for r in records if not r.website)
        enriched = await self.website_discovery.discover_many(records)
        after = sum(1 for r in enriched if not r.website)
        summary.stages.append(
            StageStats(
                name="website_discovery",
                records_in=len(records),
                records_enriched=max(0, before - after),
            )
        )
        return list(enriched)

    async def _extract_contacts(
        self, records: Sequence[NormalizedLead], summary: DiscoverySummary
    ) -> list[NormalizedLead]:
        """
        Visits each record's website and adds the contact details published on it.

        Counts a record as enriched when it gained a phone, an email or a social handle,
        which is what "extraction worked" means to an operator — a site that was fetched
        successfully but published nothing is not an enrichment.

        Runs through `extract_many_with_outcomes` rather than `extract_many` so the per-lead
        statuses and ownership scores survive into the run summary. Without them an operator
        seeing "0 enriched" cannot tell whether the sites were unreachable, blocked by
        robots.txt, or simply publish no contact details — three problems with three
        different responses.

        The ownership score is **reported, never enforced**: a low-relevance site keeps its
        extracted contacts. Discarding on a heuristic would silently lose real studios whose
        sites happen not to spell their name out in text.
        """
        def contact_count(record: NormalizedLead) -> int:
            return (
                len(record.phone_numbers)
                + len(record.emails)
                + (1 if record.instagram else 0)
                + (1 if record.facebook else 0)
            )

        before = [contact_count(r) for r in records]

        # The outcome-bearing call is preferred, but an injected extractor is only *required*
        # to offer `extract_many` — that is the interface this stage has always depended on,
        # and the collaborator is substitutable. A simpler implementation therefore still
        # works; it just contributes no per-status breakdown.
        detail: dict[str, int] = {}
        with_outcomes = getattr(
            self.contact_extractor, "extract_many_with_outcomes", None
        )
        if callable(with_outcomes):
            outcomes = await with_outcomes(records)
            enriched = [outcome.lead for outcome in outcomes]
            for outcome in outcomes:
                detail[outcome.status] = detail.get(outcome.status, 0) + 1
                if outcome.relevance_status:
                    key = f"relevance_{outcome.relevance_status}"
                    detail[key] = detail.get(key, 0) + 1
        else:
            enriched = list(await self.contact_extractor.extract_many(records))

        gained = sum(
            1 for old, record in zip(before, enriched) if contact_count(record) > old
        )

        summary.stages.append(
            StageStats(
                name="contact_extraction",
                records_in=len(records),
                records_enriched=gained,
                detail=detail,
            )
        )
        return enriched

    def _normalize(
        self, records: Sequence[NormalizedLead], summary: DiscoverySummary
    ) -> list[NormalizedLead]:
        """
        Canonicalises every record's contact fields, then applies the DTO's own cleaning.

        Both passes are deliberate and neither is redundant. `ContactNormalizationService`
        canonicalises *values* — E.164 phones, lowercased emails, bare handles — while
        `NormalizedLead.normalize()` enforces the *record's* shape: column length caps,
        coordinate ranges, ordered de-duplication of the phone list. Deduplication compares
        keys derived from both, so both must have run before stage 5.
        """
        normalized: list[NormalizedLead] = []
        changed = 0
        for record in records:
            cleaned = self.contact_normalizer.normalize_lead(record).normalize()
            if cleaned != record:
                changed += 1
            normalized.append(cleaned)
        summary.stages.append(
            StageStats(
                name="normalization", records_in=len(records), records_enriched=changed
            )
        )
        return normalized

    @staticmethod
    def _partition_valid(
        records: Sequence[NormalizedLead],
    ) -> tuple[list[NormalizedLead], list[DiscoveryFailedRecord]]:
        """
        Splits records into those the CRM can store and structured reasons for those it cannot.

        Validity is `NormalizedLead.is_valid()`'s call, not this service's: a lead needs a
        business name and at least one phone number. Filtering here rather than inside the
        persistence loop keeps the deduplication stage from spending a query on a record
        that could never be written anyway.
        """
        valid: list[NormalizedLead] = []
        invalid: list[DiscoveryFailedRecord] = []
        for index, record in enumerate(records):
            ok, reason = record.is_valid()
            if ok:
                valid.append(record)
            else:
                # Falls back to a positional label so an unnamed record is still
                # identifiable in the results table, which is the common case here: a
                # missing business name is one of the two things that makes a record
                # invalid in the first place.
                invalid.append(
                    DiscoveryFailedRecord(
                        reason=reason,
                        business_name=record.business_name or f"record {index + 1}",
                    )
                )
        return valid, invalid

    # -----------------------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------------------

    async def _persist(
        self, db: AsyncSession, plan: DeduplicationResult, summary: DiscoverySummary
    ) -> None:
        """
        Applies a deduplication plan: inserts the new leads, enriches the mergeable ones,
        counts the rest as duplicates.

        Each record is written in isolation and a failure is contained: the session is
        rolled back so the remaining records still have a usable transaction, and the record
        is counted in `failed` with its reason. One unwritable row must not cost the run.
        """
        summary.duplicates += len(plan.duplicates)

        for new_lead in plan.new_leads:
            try:
                lead = await self._create_lead(db, new_lead.record)
                summary.imported += 1
                summary.created_lead_ids.append(lead.id)
                summary.imported_records.append(
                    DiscoveredLeadRecord.from_lead(lead)
                )
            except Exception as exc:  # noqa: BLE001 - per-record isolation, see docstring
                logger.exception(
                    "Failed to create lead for %r.", new_lead.record.business_name
                )
                await db.rollback()
                summary.record_failure(
                    f"create failed — {exc}", new_lead.record.business_name
                )

        for merged in plan.merged_leads:
            try:
                existing = await self.lead_repository.get_by_id(db, merged.match.lead_id)
                if existing is None:
                    # The matched lead disappeared between planning and writing — deleted by
                    # another operator mid-run. Counted as failed rather than silently
                    # dropped, and not re-created: re-creating it would resurrect a lead
                    # someone deliberately removed.
                    summary.record_failure(
                        f"matched lead {merged.match.lead_id} no longer exists.",
                        merged.record.business_name,
                    )
                    continue
                await self.lead_repository.update(
                    db, db_obj=existing, update_data=merged.changes
                )
                summary.merged += 1
                summary.merged_lead_ids.append(existing.id)
                summary.merged_records.append(
                    DiscoveredLeadRecord.from_lead(
                        existing, enriched_fields=sorted(merged.changes.keys())
                    )
                )
            except Exception as exc:  # noqa: BLE001 - per-record isolation
                logger.exception(
                    "Failed to enrich lead %s.", merged.match.lead_id
                )
                await db.rollback()
                summary.record_failure(
                    f"merge failed — {exc}", merged.record.business_name
                )

    async def _create_lead(self, db: AsyncSession, record: NormalizedLead) -> Lead:
        """
        Writes one normalized record as a new Lead and logs its creation activity.

        Mirrors `LeadImportService._create_lead` field for field, including folding the
        collected extras that have no column — rating, categories, pincode, source URL,
        surplus numbers — into `remarks` rather than dropping them. Kept as its own method
        so the mapping is in one readable place; the shared `ENRICHABLE_FIELDS` merge logic
        it would otherwise duplicate lives in the deduplication service, which is where this
        pipeline gets its `changes` dict from.
        """
        lead = Lead(
            business_name=record.business_name,
            contact_person=record.owner_name,
            phone=record.primary_phone,
            whatsapp=record.secondary_phone,
            email=record.primary_email,
            instagram=record.instagram,
            facebook=record.facebook,
            youtube=record.youtube,
            website=record.website,
            address=record.address,
            city=record.city,
            district=record.district,
            state=record.state,
            country=record.country,
            latitude=record.latitude,
            longitude=record.longitude,
            source=self._resolve_source(record.source or self.provider.lead_source),
            status=LeadStatus.NEW,
            remarks=self._build_remarks(record),
            is_converted=False,
        )
        lead = await self.lead_repository.create(db, lead)
        await self.activity_service.log_created(db, lead)
        return lead

    @staticmethod
    def _resolve_source(value: str | None) -> LeadSource:
        """
        Maps a provider's declared source string onto the `LeadSource` enum, defaulting to
        OTHER. Falling back rather than raising means a new provider can be run through this
        pipeline before anyone decides whether it deserves its own enum member.
        """
        if not value:
            return LeadSource.OTHER
        try:
            return LeadSource(value.strip().upper())
        except ValueError:
            return LeadSource.OTHER

    @staticmethod
    def _build_remarks(record: NormalizedLead) -> str | None:
        """
        Renders the collected fields that have no dedicated Lead column into a short
        remarks block, or None when there is nothing extra to say.
        """
        parts: list[str] = []
        if record.rating is not None:
            rating_text = f"Rating: {record.rating}"
            if record.review_count is not None:
                rating_text += f" ({record.review_count} reviews)"
            parts.append(rating_text)
        elif record.review_count is not None:
            parts.append(f"Reviews: {record.review_count}")
        if record.categories:
            parts.append(f"Categories: {', '.join(record.categories)}")
        if record.pincode:
            parts.append(f"Pincode: {record.pincode}")
        if record.source_url:
            parts.append(f"Source: {record.source_url}")
        if len(record.phone_numbers) > 2:
            parts.append(f"Other numbers: {', '.join(record.phone_numbers[2:])}")
        if len(record.emails) > 1:
            parts.append(f"Other emails: {', '.join(record.emails[1:])}")

        if not parts:
            return None
        return "Discovered via lead discovery pipeline.\n" + "\n".join(parts)

    # -----------------------------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """
        Reports the wired pipeline — which implementation is behind each stage — for a
        health or debug endpoint. Useful precisely because every stage is injectable: this
        is how an operator confirms a run used the real extractor and not a stub.
        """
        return {
            "service": "LeadDiscoveryService",
            "pipeline": [
                "collect", "website_discovery", "contact_extraction",
                "normalization", "deduplication", "persist",
            ],
            "provider": self.provider.key,
            "website_discovery": type(self.website_discovery).__name__,
            "contact_extractor": type(self.contact_extractor).__name__,
            "contact_normalizer": type(self.contact_normalizer).__name__,
            "deduplication_service": type(self.deduplication_service).__name__,
        }


__all__ = [
    "DEFAULT_PROVIDER_KEY",
    "DEFAULT_QUERY",
    "DiscoverySummary",
    "LeadDiscoveryService",
    "StageStats",
]
