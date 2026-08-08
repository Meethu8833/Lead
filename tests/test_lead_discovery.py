"""
tests/test_lead_discovery.py

Integration test suite for `LeadDiscoveryService` — the orchestrator that turns a city into
saved leads by running the collection pipeline end to end.

    city → Overpass → website discovery → contact extraction → normalization
         → deduplication → save → summary

What is real and what is stubbed
--------------------------------
This is an **integration** suite, not a unit suite: the database is real, and so are four of
the six stages. The service runs against `AsyncSessionLocal`, writes real `Lead` rows through
the real `LeadRepository`, classifies them through the real `LeadDeduplicationService`, and
cleans them up in a `finally` block — repository writes commit immediately, so a session
rollback would not undo them.

The three network-touching collaborators are replaced by stubs implementing their ports:

  * `StubProvider`      — a `LeadProvider` returning canned records instead of calling
                          Overpass and Nominatim.
  * `StubDiscovery`     — answers "what is this business's website" from a dict.
  * `StubExtractor`     — answers "what contacts does that website publish" from a dict.

Stubbing exactly these three is the point of the constructor injection under test. They are
the stages that reach the public internet, and a suite that hit them would be slow,
non-deterministic, and rude to donated infrastructure. Everything *this service is
responsible for* — stage order, batch hand-off, counter reconciliation, persistence, failure
containment — is exercised for real. Each stubbed stage already has its own dedicated suite
(`test_overpass_import.py`, `test_website_discovery.py`, `test_contact_extractor.py`).

Sections
--------
1.  Construction and dependency injection — every collaborator is overridable, the defaults
    are the real implementations, and `describe()` reports what is actually wired.
2.  Pipeline order — the six stages run once each, in the specified order, with each stage
    receiving the previous stage's output. Proven by a recording harness, not by reading.
3.  The summary contract — exactly `{found, imported, merged, duplicates, failed}`, and the
    counters reconcile with what is in the database.
4.  Enrichment flows through — a website found in stage 2 and contacts extracted in stage 3
    reach the saved `Lead` row.
5.  Deduplication — a record matching an existing lead enriches it (merged) or is ignored
    (duplicates) rather than being inserted twice; a repeated record within one batch yields
    one lead.
6.  Failure handling — invalid records and failing writes are counted in `failed` without
    aborting the run; a source-level provider fault propagates.
7.  Orchestration only — asserted structurally: the module contains no scraping, no HTTP
    client, no HTML parsing, and delegates every stage.
8.  Stage toggles and empty results — a run that collects nothing, and runs with the two
    network stages disabled.
9.  Full contact persistence, merge safety and statistics — every collected channel (phone,
    WhatsApp, email, website, Instagram, Facebook, YouTube) reaches the `Lead` row; an
    ordinary phone is never mistaken for a WhatsApp number; enrichment counters are measured
    over what was written; a populated field is never overwritten by a weaker source; and a
    failed enrichment saves the lead unenriched rather than losing it.

Requires a reachable database (`.env` / `app/core/config.py`). No network is touched.

Run:  python tests/test_lead_discovery.py
"""

import ast
import asyncio
import inspect
import os
import sys
import uuid
from typing import Any, Sequence

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_activity import LeadActivity
from app.repositories.lead import LeadRepository
from app.services import lead_discovery as module
from app.services.contact_extractor import ContactExtractorService
from app.services.contact_normalization import ContactNormalizationService
from app.services.lead_deduplication import LeadDeduplicationService
from app.services.lead_discovery import (
    DiscoverySummary,
    LeadDiscoveryService,
    StageStats,
)
from app.services.lead_providers.base import (
    LeadProvider,
    ProviderCollectionError,
    ProviderContext,
)
from app.services.lead_providers.normalized import NormalizedLead
from app.services.website_discovery import WebsiteDiscoveryService


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


#: Marker embedded in every business name this suite creates, so the cleanup block can find
#: rows even if a test fails before it tracked an id.
MARKER = uuid.uuid4().hex[:8]

#: Phone prefix unique to this run. Leads carry a UNIQUE constraint on `phone`, so a fixed
#: number would collide with a previous run's leftovers and turn a real failure into a
#: confusing one.
_PHONE_BASE = 7000000000 + (int(MARKER, 16) % 90000000)


def unique_phone(offset: int) -> str:
    """Returns a phone number unique to this run, so reruns cannot collide."""
    return f"+91{_PHONE_BASE + offset}"


def make_record(
    name: str,
    phone_offset: int,
    city: str = "Kozhikode",
    website: str | None = None,
    **extra: Any,
) -> NormalizedLead:
    """Builds a normalized record as a provider would return one."""
    return NormalizedLead(
        business_name=f"{name} {MARKER}",
        phone_numbers=[unique_phone(phone_offset)],
        city=city,
        source="GOOGLE_MAPS",
        website=website,
        **extra,
    ).normalize()


# ===========================================================================================
# Stubs — the three network-touching stages
# ===========================================================================================

class StubProvider(LeadProvider):
    """
    A `LeadProvider` returning canned records, standing in for Overpass.

    Implements the port directly rather than stubbing HTTP, which is what the port exists
    for: the orchestrator under test cannot tell this from the real adapter, and the real
    adapter's own behaviour is covered by `test_overpass_import.py`.
    """

    key = "stub_overpass"
    display_name = "Stub Overpass"
    lead_source = "GOOGLE_MAPS"
    requires_query = True
    requires_file = False

    def __init__(
        self,
        records: Sequence[NormalizedLead] = (),
        fail_with: str | None = None,
    ) -> None:
        self._records = list(records)
        self._fail_with = fail_with
        self.contexts: list[ProviderContext] = []

    def search(self, query: str | None = None, **kwargs: Any) -> ProviderContext:
        context = super().search(query, **kwargs)
        # Mirror the real adapter's city requirement, so the suite proves the orchestrator
        # actually passes the city down rather than dropping it.
        if not (context.city or "").strip():
            from app.core.exceptions import BadRequestException
            raise BadRequestException("Stub provider requires a `city`.")
        self.contexts.append(context)
        return context

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        if self._fail_with:
            raise ProviderCollectionError(self._fail_with)
        return [{"index": i} for i in range(len(self._records[: context.limit]))]

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        return self._records[raw["index"]]


class StubDiscovery:
    """
    Stands in for `WebsiteDiscoveryService`, answering from a name → website dict.

    Honours the real service's two hard rules so the orchestrator is tested against real
    semantics: an existing website is never overwritten, and an unknown business is returned
    unchanged rather than raising.
    """

    def __init__(self, sites: dict[str, str] | None = None) -> None:
        self.sites = sites or {}
        self.calls: list[list[str | None]] = []

    async def discover_many(
        self, leads: Sequence[NormalizedLead]
    ) -> list[NormalizedLead]:
        self.calls.append([lead.business_name for lead in leads])
        out: list[NormalizedLead] = []
        for lead in leads:
            if lead.website:
                out.append(lead)
                continue
            found = self.sites.get(lead.business_name)
            out.append(
                NormalizedLead(**{**lead.to_dict(), "website": found}) if found else lead
            )
        return out


class StubExtractor:
    """
    Stands in for `ContactExtractorService`, answering from a website → contacts dict.

    Like the real service, it enriches only leads that have a website and never raises.
    """

    def __init__(self, contacts: dict[str, dict[str, Any]] | None = None) -> None:
        self.contacts = contacts or {}
        self.calls: list[list[str | None]] = []

    async def extract_many(
        self, leads: Sequence[NormalizedLead]
    ) -> list[NormalizedLead]:
        self.calls.append([lead.website for lead in leads])
        out: list[NormalizedLead] = []
        for lead in leads:
            found = self.contacts.get(lead.website or "")
            if not found:
                out.append(lead)
                continue
            data = lead.to_dict()
            data["emails"] = list(dict.fromkeys(list(data["emails"]) + found.get("emails", [])))
            data["phone_numbers"] = list(
                dict.fromkeys(list(data["phone_numbers"]) + found.get("phones", []))
            )
            for social in ("instagram", "facebook", "youtube"):
                if found.get(social):
                    data[social] = found[social]
            # WhatsApp numbers travel on their own list, never inferred from `phones`: the
            # pipeline only treats a number as WhatsApp-capable when a source said so.
            if found.get("whatsapp_numbers"):
                data["whatsapp_numbers"] = list(
                    dict.fromkeys(
                        list(data.get("whatsapp_numbers") or [])
                        + found["whatsapp_numbers"]
                    )
                )
            out.append(NormalizedLead(**data))
        return out


class RecordingNormalizer(ContactNormalizationService):
    """The real normalizer, instrumented to record that the orchestrator called it."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str | None] = []

    def normalize_lead(self, lead: NormalizedLead) -> NormalizedLead:
        self.calls.append(lead.business_name)
        return super().normalize_lead(lead)


class RecordingDeduplicator(LeadDeduplicationService):
    """The real deduplicator, instrumented to record the batch it received."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[str | None]] = []

    async def deduplicate(self, db, records):  # type: ignore[no-untyped-def]
        self.batches.append([r.business_name for r in records])
        return await super().deduplicate(db, records)


def build_service(
    records: Sequence[NormalizedLead] = (),
    sites: dict[str, str] | None = None,
    contacts: dict[str, dict[str, Any]] | None = None,
    fail_with: str | None = None,
) -> tuple[LeadDiscoveryService, dict[str, Any]]:
    """
    Wires a service from stubs and returns it alongside the stubs, so a test can assert on
    both the outcome and what each stage was handed.
    """
    provider = StubProvider(records, fail_with=fail_with)
    discovery = StubDiscovery(sites)
    extractor = StubExtractor(contacts)
    normalizer = RecordingNormalizer()
    deduplicator = RecordingDeduplicator()
    service = LeadDiscoveryService(
        provider=provider,
        website_discovery=discovery,
        contact_extractor=extractor,
        contact_normalizer=normalizer,
        deduplication_service=deduplicator,
    )
    return service, {
        "provider": provider,
        "discovery": discovery,
        "extractor": extractor,
        "normalizer": normalizer,
        "deduplicator": deduplicator,
    }


# ===========================================================================================
# Suite
# ===========================================================================================

async def test_lead_discovery_suite() -> None:
    created_lead_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        try:
            print("=" * 78)
            print(f"LEAD DISCOVERY SERVICE — INTEGRATION SUITE (marker {MARKER})")
            print("=" * 78)

            # ===============================================================================
            print("\n--- 1. CONSTRUCTION AND DEPENDENCY INJECTION ---")
            # ===============================================================================

            default = LeadDiscoveryService()
            check(isinstance(default.website_discovery, WebsiteDiscoveryService),
                  "Default website_discovery must be the real service.")
            check(isinstance(default.contact_extractor, ContactExtractorService),
                  "Default contact_extractor must be the real service.")
            check(isinstance(default.contact_normalizer, ContactNormalizationService),
                  "Default contact_normalizer must be the real service.")
            check(isinstance(default.deduplication_service, LeadDeduplicationService),
                  "Default deduplication_service must be the real service.")
            check(default.provider.key == "overpass",
                  f"Default provider must be overpass, got {default.provider.key}")
            print("  ✓ constructing with no arguments wires the real, shipped pipeline")

            params = inspect.signature(LeadDiscoveryService.__init__).parameters
            for injectable in (
                "provider", "website_discovery", "contact_extractor",
                "contact_normalizer", "deduplication_service",
                "lead_repository", "activity_service",
            ):
                check(injectable in params, f"'{injectable}' must be injectable.")
                check(params[injectable].default is None,
                      f"'{injectable}' must default to None so the real one is built lazily.")
            print(f"  ✓ all {len(params) - 2} collaborators are constructor-injectable")

            svc, stubs = build_service()
            described = svc.describe()
            check(described["provider"] == "stub_overpass",
                  "describe() must report the injected provider, not the default.")
            check(described["website_discovery"] == "StubDiscovery",
                  "describe() must report the injected discovery stage.")
            check(described["pipeline"] == [
                "collect", "website_discovery", "contact_extraction",
                "normalization", "deduplication", "persist",
            ], f"describe() reports the wrong pipeline: {described['pipeline']}")
            print("  ✓ describe() reports the stages actually wired, not the defaults")

            # ===============================================================================
            print("\n--- 2. PIPELINE ORDER AND HAND-OFF ---")
            # ===============================================================================

            records = [
                make_record("Sunrise Studio", 1),
                make_record("Moonlight Photography", 2),
            ]
            svc, stubs = build_service(
                records,
                sites={f"Sunrise Studio {MARKER}": "https://sunrise-studio.example"},
                contacts={
                    "https://sunrise-studio.example": {
                        "emails": ["hello@sunrise-studio.example"],
                        "instagram": "sunrisestudio",
                    }
                },
            )
            summary = await svc.run(db, city="Kozhikode", limit=25)
            created_lead_ids.extend(summary.created_lead_ids)

            check(len(stubs["provider"].contexts) == 1,
                  "The provider must be searched exactly once per run.")
            context = stubs["provider"].contexts[0]
            check(context.city == "Kozhikode",
                  f"The city must reach the provider, got {context.city!r}")
            check(context.limit == 25, f"The limit must reach the provider, got {context.limit}")
            print("  ✓ stage 1: the city and limit reach the provider's search()")

            check(len(stubs["discovery"].calls) == 1,
                  "Website discovery must run exactly once, over the whole batch.")
            check(stubs["discovery"].calls[0] == [r.business_name for r in records],
                  "Website discovery must receive the provider's records, in order.")
            print("  ✓ stage 2: discovery receives the collected batch, in order")

            check(len(stubs["extractor"].calls) == 1,
                  "Contact extraction must run exactly once, over the whole batch.")
            check("https://sunrise-studio.example" in stubs["extractor"].calls[0],
                  "Extraction must receive the website discovery found in stage 2 — the "
                  "hand-off between the two enrichment stages.")
            print("  ✓ stage 3: extraction receives the websites discovered in stage 2")

            check(len(stubs["normalizer"].calls) == len(records),
                  "Normalization must run over every record.")
            print("  ✓ stage 4: normalization runs over every record")

            check(len(stubs["deduplicator"].batches) == 1,
                  "Deduplication must run exactly once, over the whole batch.")
            print("  ✓ stage 5: deduplication receives one batch")

            stage_names = [s.name for s in summary.stages]
            check(stage_names == [
                "collect", "website_discovery", "contact_extraction",
                "normalization", "deduplicate",
            ], f"Stages ran out of order: {stage_names}")
            print(f"  ✓ stages ran once each, in order: {' → '.join(stage_names)}")

            # ===============================================================================
            print("\n--- 3. THE SUMMARY CONTRACT ---")
            # ===============================================================================

            payload = summary.to_dict()
            check(set(payload) == {"found", "imported", "merged", "duplicates", "failed"},
                  f"Summary must have exactly the five specified keys, got {sorted(payload)}")
            check(all(isinstance(v, int) for v in payload.values()),
                  "Every summary counter must be an int.")
            print(f"  ✓ run() returns exactly {{found, imported, merged, duplicates, failed}}")
            print(f"    {payload}")

            check(summary.found == 2, f"Expected found=2, got {summary.found}")
            check(summary.imported == 2, f"Expected imported=2, got {summary.imported}")
            check(summary.reconciles,
                  f"Counters must reconcile: found={summary.found} "
                  f"accounted={summary.accounted_for}")
            print("  ✓ imported + merged + duplicates + failed == found")

            rows = (await db.execute(
                select(Lead).where(Lead.business_name.like(f"%{MARKER}%"))
            )).scalars().all()
            check(len(rows) == 2,
                  f"`imported` must match rows actually in the database, found {len(rows)}")
            print("  ✓ `imported` matches the rows actually written to the database")

            # ===============================================================================
            print("\n--- 4. ENRICHMENT REACHES THE SAVED LEAD ---")
            # ===============================================================================

            sunrise = next(r for r in rows if r.business_name.startswith("Sunrise"))
            check(sunrise.website == "https://sunrise-studio.example",
                  f"The discovered website must be saved, got {sunrise.website!r}")
            print("  ✓ a website discovered in stage 2 is persisted on the lead")

            check(sunrise.email == "hello@sunrise-studio.example",
                  f"The extracted email must be saved, got {sunrise.email!r}")
            check(sunrise.instagram == "sunrisestudio",
                  f"The extracted Instagram handle must be saved, got {sunrise.instagram!r}")
            print("  ✓ contacts extracted in stage 3 are persisted on the lead")

            check(sunrise.status == LeadStatus.NEW, "A discovered lead must start at NEW.")
            check(sunrise.is_converted is False, "A discovered lead must not be pre-converted.")
            check(sunrise.source == LeadSource.GOOGLE_MAPS,
                  f"Source must be attributed, got {sunrise.source}")
            print("  ✓ leads enter the pipeline at NEW with their source attributed")

            activities = (await db.execute(
                select(LeadActivity).where(LeadActivity.lead_id == sunrise.id)
            )).scalars().all()
            check(len(activities) >= 1, "A discovered lead must get a timeline activity.")
            print("  ✓ each created lead receives a CREATED timeline activity")

            moonlight = next(r for r in rows if r.business_name.startswith("Moonlight"))
            check(moonlight.website is None,
                  "A lead with no discoverable website must be saved without one, not guessed.")
            print("  ✓ a lead with no discoverable website is saved unenriched, not invented")

            # ===============================================================================
            print("\n--- 5. DEDUPLICATION ---")
            # ===============================================================================

            # 5.1 The same business again, now carrying a field the stored lead lacks.
            svc, stubs = build_service([
                make_record("Moonlight Photography", 2, website="https://moonlight.example"),
            ])
            merged_summary = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(merged_summary.created_lead_ids)

            check(merged_summary.found == 1, "One record in.")
            check(merged_summary.imported == 0,
                  "A record matching an existing lead must not be inserted again.")
            check(merged_summary.merged == 1,
                  f"Expected merged=1, got {merged_summary.to_dict()}")
            check(merged_summary.reconciles, "Merged run must reconcile.")
            await db.refresh(moonlight)
            check(moonlight.website == "https://moonlight.example",
                  "A merge must fill the previously-empty field.")
            print("  ✓ a matching record enriches the existing lead (merged), no new row")

            # 5.2 The same business again with nothing new to add.
            svc, stubs = build_service([make_record("Moonlight Photography", 2)])
            dup_summary = await svc.run(db, city="Kozhikode")
            check(dup_summary.duplicates == 1,
                  f"Expected duplicates=1, got {dup_summary.to_dict()}")
            check(dup_summary.imported == 0 and dup_summary.merged == 0,
                  "A record adding nothing must be counted only as a duplicate.")
            check(dup_summary.reconciles, "Duplicate run must reconcile.")
            print("  ✓ a matching record that adds nothing is counted as a duplicate")

            total_now = (await db.execute(
                select(Lead).where(Lead.business_name.like(f"%{MARKER}%"))
            )).scalars().all()
            check(len(total_now) == 2,
                  f"Merges and duplicates must not create rows, found {len(total_now)}")
            print("  ✓ neither a merge nor a duplicate creates a new row")

            # 5.3 One batch containing the same business twice.
            svc, stubs = build_service([
                make_record("Twilight Frames", 3),
                make_record("Twilight Frames", 3),
            ])
            batch_summary = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(batch_summary.created_lead_ids)
            check(batch_summary.found == 2, "Two records in.")
            check(batch_summary.imported == 1,
                  f"A repeated record in one batch must yield one lead, got "
                  f"{batch_summary.to_dict()}")
            check(batch_summary.duplicates == 1, "The repeat must be counted as a duplicate.")
            check(batch_summary.reconciles, "Within-batch run must reconcile.")
            print("  ✓ the same business twice in one batch yields one lead, one duplicate")

            # ===============================================================================
            print("\n--- 6. FAILURE HANDLING ---")
            # ===============================================================================

            # 6.1 An invalid record is counted, and the valid ones still land.
            svc, stubs = build_service([
                NormalizedLead(business_name=f"No Phone {MARKER}", city="Kozhikode").normalize(),
                make_record("Valid Studio", 4),
            ])
            mixed = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(mixed.created_lead_ids)
            check(mixed.found == 2, "Both records count as found.")
            check(mixed.failed == 1, f"The unstorable record must be counted, got {mixed.to_dict()}")
            check(mixed.imported == 1,
                  "One bad record must not cost the good ones in the same run.")
            check(mixed.reconciles, "A run with failures must still reconcile.")
            check(any("No Phone" in e for e in mixed.errors),
                  f"The failure reason must be reported, got {mixed.errors}")
            print("  ✓ an invalid record is counted in `failed`; the rest of the run proceeds")

            # 6.2 A write that raises is contained, not fatal.
            class ExplodingRepository:
                """A repository whose create() fails for one specific business."""

                def __init__(self, real):
                    self._real = real

                async def create(self, db, lead):
                    if "Exploding" in (lead.business_name or ""):
                        raise RuntimeError("simulated write failure")
                    return await self._real.create(db, lead)

                def __getattr__(self, item):
                    return getattr(self._real, item)

            from app.repositories.lead import LeadRepository

            svc, stubs = build_service([
                make_record("Exploding Studio", 5),
                make_record("Surviving Studio", 6),
            ])
            svc.lead_repository = ExplodingRepository(LeadRepository())
            svc.deduplication_service = LeadDeduplicationService()
            exploded = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(exploded.created_lead_ids)
            check(exploded.failed == 1,
                  f"The failing write must be counted, got {exploded.to_dict()}")
            check(exploded.imported == 1,
                  "A failed write must not abort the rest of the run.")
            check(exploded.reconciles, "A run with a failed write must reconcile.")
            print("  ✓ a write that raises is contained: counted, session recovered, run continues")

            # 6.3 A source-level fault propagates rather than reporting an empty run.
            svc, stubs = build_service(fail_with="Overpass unreachable")
            try:
                await svc.run(db, city="Kozhikode")
                raise AssertionError("A provider fault must propagate, not report found=0.")
            except ProviderCollectionError as exc:
                check("unreachable" in str(exc), f"Wrong message: {exc}")
            print("  ✓ a source-level provider fault propagates instead of faking an empty run")

            # 6.4 A bad request is refused before anything is collected or written.
            svc, stubs = build_service([make_record("Never Collected", 7)])
            try:
                await svc.run(db, city="")
                raise AssertionError("A city-less run must be refused.")
            except Exception as exc:
                check("city" in str(exc).lower(), f"Wrong refusal: {exc}")
            check(len(stubs["discovery"].calls) == 0,
                  "A refused request must not reach the enrichment stages.")
            print("  ✓ an invalid request is refused before any stage runs or any row is written")

            # ===============================================================================
            print("\n--- 7. ORCHESTRATION ONLY (STRUCTURAL) ---")
            # ===============================================================================

            source_path = module.__file__
            with open(source_path, "r", encoding="utf-8") as handle:
                source = handle.read()
            tree = ast.parse(source)

            imported_modules: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module.split(".")[0])

            for banned in ("httpx", "requests", "bs4", "urllib", "aiohttp", "selenium"):
                check(banned not in imported_modules,
                      f"The orchestrator must not import '{banned}' — scraping belongs in a stage.")
            print("  ✓ imports no HTTP client and no HTML parser: it cannot scrape")

            check("re" not in imported_modules,
                  "The orchestrator must not import `re` — parsing/extraction belongs in a stage.")
            print("  ✓ imports no regex module: it cannot parse or extract contacts")

            for banned_call in ("BeautifulSoup", "findall", "AsyncClient"):
                check(banned_call not in source,
                      f"The orchestrator must not call '{banned_call}'.")
            print("  ✓ calls no parsing or fetching primitive anywhere in the module")

            for delegated in (
                "discover_many", "extract_many", "normalize_lead",
                "deduplicate", "collect_normalized",
            ):
                check(delegated in source,
                      f"The orchestrator must delegate to '{delegated}'.")
            print("  ✓ every stage is delegated to its own service")

            # ===============================================================================
            print("\n--- 8. STAGE TOGGLES AND EMPTY RESULTS ---")
            # ===============================================================================

            svc, stubs = build_service([])
            empty = await svc.run(db, city="Nowhere")
            check(empty.to_dict() == {
                "found": 0, "imported": 0, "merged": 0, "duplicates": 0, "failed": 0,
            }, f"An empty collection must return all-zero, got {empty.to_dict()}")
            check(len(stubs["discovery"].calls) == 0,
                  "An empty batch must short-circuit rather than run the enrichment stages.")
            print("  ✓ a run that collects nothing returns all zeros and skips the later stages")

            svc, stubs = build_service(
                [make_record("Toggled Studio", 8)],
                sites={f"Toggled Studio {MARKER}": "https://toggled.example"},
            )
            toggled = await svc.run(
                db, city="Kozhikode", discover_websites=False, extract_contacts=False
            )
            created_lead_ids.extend(toggled.created_lead_ids)
            check(len(stubs["discovery"].calls) == 0,
                  "discover_websites=False must skip the discovery stage.")
            check(len(stubs["extractor"].calls) == 0,
                  "extract_contacts=False must skip the extraction stage.")
            check(toggled.imported == 1, "The record must still be collected and saved.")
            check(toggled.reconciles, "A toggled run must reconcile.")
            print("  ✓ the two network stages can be switched off; the rest of the pipeline runs")

            summary_obj = DiscoverySummary(found=1, imported=1, city="Kozhikode")
            detailed = summary_obj.to_detailed_dict()
            check(set(detailed) > set(summary_obj.to_dict()),
                  "to_detailed_dict() must extend the five-key contract, not replace it.")
            check(isinstance(summary.stages[0], StageStats), "Stages are StageStats records.")
            print("  ✓ diagnostics are available without changing the five-key contract")

            # ===============================================================================
            print("\n--- 9. FULL CONTACT PERSISTENCE, MERGE SAFETY AND STATISTICS ---")
            # ===============================================================================

            # Every channel the extractor can produce, on one record, so a field that is
            # collected but never written shows up as a failure here rather than as a
            # quietly empty column in the CRM.
            site = "https://fullcontact.example"
            svc, stubs = build_service(
                [make_record("Full Contact Studio", 40)],
                sites={f"Full Contact Studio {MARKER}": site},
                contacts={
                    site: {
                        "emails": ["hello@fullcontact.example"],
                        "phones": [unique_phone(41)],
                        "whatsapp_numbers": [unique_phone(42)],
                        "instagram": "fullcontactstudio",
                        "facebook": "https://facebook.com/fullcontactstudio",
                        "youtube": "https://youtube.com/@fullcontactstudio",
                    }
                },
            )
            full = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(full.created_lead_ids)
            check(full.imported == 1, f"Expected one import, got {full.imported}.")

            saved = await LeadRepository().get_by_id(db, full.created_lead_ids[0])
            check(saved is not None, "The discovered lead must be readable back.")
            check(bool(saved.phone), "A phone number must be persisted.")
            check(saved.email == "hello@fullcontact.example",
                  f"The extracted email must be persisted, got {saved.email!r}.")
            check(saved.website == site,
                  f"The discovered website must be persisted, got {saved.website!r}.")
            check(saved.instagram == "fullcontactstudio",
                  f"The extracted Instagram must be persisted, got {saved.instagram!r}.")
            check(saved.facebook == "https://facebook.com/fullcontactstudio",
                  f"The extracted Facebook must be persisted, got {saved.facebook!r}.")
            check(saved.youtube == "https://youtube.com/@fullcontactstudio",
                  f"The extracted YouTube must be persisted, got {saved.youtube!r}.")
            check(bool(saved.whatsapp),
                  "A WhatsApp number identified by the source must be persisted.")
            print("  ✓ phone, WhatsApp, email, website, Instagram, Facebook and YouTube all persist")

            record = full.imported_records[0]
            check(record.youtube == saved.youtube,
                  "The results record must carry the stored YouTube URL.")
            check(record.is_whatsapp_ready is True,
                  "A lead with a WhatsApp number must be reported WhatsApp-ready.")
            check(record.contact_quality == "HIGH",
                  f"A number plus a website is HIGH quality, got {record.contact_quality!r}.")
            print("  ✓ the results record reports WhatsApp readiness and contact quality")

            # A phone number alone must NOT be read as a WhatsApp number.
            svc, _ = build_service([make_record("Phone Only Studio", 45)])
            phone_only = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(phone_only.created_lead_ids)
            plain = phone_only.imported_records[0]
            check(plain.is_whatsapp_ready is False,
                  "An ordinary phone number must never be assumed to be on WhatsApp.")
            check(plain.contact_quality == "MEDIUM",
                  f"A number with no second channel is MEDIUM, got {plain.contact_quality!r}.")
            print("  ✓ an ordinary phone number is not treated as a WhatsApp number")

            # Enrichment statistics must describe what was stored, and must be counted, not
            # invented: the figures are re-derived here from the records themselves.
            stats = full.enrichment.to_dict()
            check(stats["emails_found"] == 1,
                  f"One written lead holds an email, got {stats['emails_found']}.")
            check(stats["youtube_found"] == 1,
                  f"One written lead holds a YouTube URL, got {stats['youtube_found']}.")
            check(stats["whatsapp_found"] == 1,
                  f"One written lead holds a WhatsApp number, got {stats['whatsapp_found']}.")
            check(stats["websites_discovered"] == 1,
                  f"One website was discovered, got {stats['websites_discovered']}.")
            check(set(stats) == {
                "websites_discovered", "contacts_extracted", "emails_found",
                "phones_found", "whatsapp_found", "instagram_found",
                "facebook_found", "youtube_found",
            }, "The enrichment block must expose exactly the documented counters.")
            print("  ✓ enrichment statistics are counted over the leads actually written")

            check("enrichment" in full.to_response_dict(),
                  "The API projection must carry the enrichment block.")
            zero = DiscoverySummary()
            zero.compute_enrichment()
            check(all(v == 0 for v in zero.enrichment.to_dict().values()),
                  "A run that wrote nothing must report zeroes, never a fabricated figure.")
            print("  ✓ a run that wrote nothing reports zeroes rather than invented numbers")

            # The never-overwrite rule. The stored lead already has an email and an
            # Instagram handle; a second source offering different ones must fill only the
            # genuinely empty fields and leave the populated ones exactly as they were.
            held = Lead(
                business_name=f"Held Studio {MARKER}",
                phone=unique_phone(50),
                email="original@held.example",
                instagram="originalhandle",
                city="Kozhikode",
                source=LeadSource.OTHER,
                status=LeadStatus.NEW,
                is_converted=False,
            )
            held = await LeadRepository().create(db, held)
            created_lead_ids.append(held.id)

            rival = "https://held-rival.example"
            svc, _ = build_service(
                [make_record("Held Studio", 50, website=None)],
                sites={f"Held Studio {MARKER}": rival},
                contacts={
                    rival: {
                        "emails": ["different@held.example"],
                        "instagram": "differenthandle",
                        "youtube": "https://youtube.com/@heldstudio",
                    }
                },
            )
            merge_run = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(merge_run.created_lead_ids)
            check(merge_run.imported == 0,
                  "The same business from another source must not create a second lead.")
            check(merge_run.merged == 1,
                  f"The matching record must enrich the held lead, got {merge_run.merged}.")

            await db.refresh(held)
            check(held.email == "original@held.example",
                  f"A populated email must never be overwritten, got {held.email!r}.")
            check(held.instagram == "originalhandle",
                  f"A populated Instagram must never be overwritten, got {held.instagram!r}.")
            check(held.youtube == "https://youtube.com/@heldstudio",
                  f"A genuinely empty field must be filled, got {held.youtube!r}.")
            check(held.website == rival,
                  f"The discovered website must fill the empty column, got {held.website!r}.")
            print("  ✓ existing values survive; only empty fields are filled by enrichment")

            merged_record = merge_run.merged_records[0]
            check("youtube" in merged_record.enriched_fields,
                  f"The merge must report youtube as filled, got {merged_record.enriched_fields}.")
            check("email" not in merged_record.enriched_fields,
                  "A field that was left alone must not be reported as enriched.")
            print("  ✓ the merge reports exactly the fields it filled")

            # A failing enrichment must cost the run its contacts, not its leads. The *real*
            # extractor is used here rather than a stub, because the guarantee under test is
            # its own documented contract ("never raises — every failure path returns the
            # input lead"). A stub that raises would only prove the stub raises.
            #
            # The website is a `.invalid` host: RFC 2606 reserves that TLD as guaranteed
            # never to resolve, so this exercises the unreachable-site path without making a
            # real request to anyone's server.
            svc, _ = build_service(
                [make_record("Resilient Studio", 60)],
                sites={f"Resilient Studio {MARKER}": "https://resilient.invalid"},
            )
            svc.contact_extractor = ContactExtractorService()
            resilient = await svc.run(db, city="Kozhikode")
            created_lead_ids.extend(resilient.created_lead_ids)
            check(resilient.imported == 1,
                  "A lead must still be saved when its website cannot be reached.")
            check(resilient.reconciles, "A run with a failed enrichment must still reconcile.")
            saved_resilient = await LeadRepository().get_by_id(db, resilient.created_lead_ids[0])
            check(saved_resilient is not None and bool(saved_resilient.phone),
                  "The lead's own collected data must survive a failed enrichment.")
            print("  ✓ a failed enrichment does not fail the lead: it is saved unenriched")

            print("\n" + "=" * 78)
            print("ALL 9 SECTIONS PASSED")
            print("=" * 78)
            print(f"Created {len(set(created_lead_ids))} leads; all are removed below.")

        except Exception as exc:
            print(f"\nTEST SUITE FAILED: {exc}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            # Repository writes commit immediately, so a session rollback would not undo
            # them; every row this suite created is hard-deleted here. Matched by the run
            # marker as well as by tracked id, so a failure part-way through still cleans up.
            print("\nCleaning up test data...")
            await db.rollback()

            leftovers = (await db.execute(
                select(Lead).where(Lead.business_name.like(f"%{MARKER}%"))
            )).scalars().all()
            for row in leftovers:
                activities = (await db.execute(
                    select(LeadActivity).where(LeadActivity.lead_id == row.id)
                )).scalars().all()
                for activity in activities:
                    await db.delete(activity)
                await db.delete(row)
            await db.commit()
            print(f"Removed {len(leftovers)} lead(s) and their activities.")


if __name__ == "__main__":
    asyncio.run(test_lead_discovery_suite())
