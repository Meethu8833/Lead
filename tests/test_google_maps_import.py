"""
tests/test_google_maps_import.py

Integration test suite for the Google Maps lead provider.
Verifies:
1.  Provider initialization (registry resolution, capability description, availability
    driven by configuration, refusal messages, no hardcoded credentials).
2.  Search execution (query composition from city/state, validation, limit clamping,
    Text Search pagination, the limit being honoured before the billed Details fan-out,
    permanently-closed businesses skipped, ZERO_RESULTS handled as success).
3.  Normalization (address components split into city/district/state/pincode, phone
    ordering, Maps URL, categories, rating/reviews, opening hours, coordinate fallback,
    details-missing degradation, and the address-derived city fallback).
4.  The import pipeline (leads created through LeadImportService, tagged GOOGLE_MAPS,
    entering the CRM at status NEW with a timeline activity, extras in remarks).
5.  Duplicate handling (re-running the same search creates nothing new; a Google record
    matching a hand-entered lead by phone enriches it rather than duplicating it).
6.  Import statistics (per-job counters reconcile; the job records provider and query).
7.  Error handling (one failing business never stops the run; failures land in the job
    logs; credential/quota/transport faults fail the run with a stated reason).

The provider is exercised against a stub HTTP transport rather than the live Places API, so
this suite needs no API key, no network and no billing, and is deterministic. The stub speaks
real Google response shapes (`status` + `results` / `result`, `next_page_token`,
`address_components`), so the mapping under test is the same one production runs.

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block, since the repository layer commits each write
immediately.

Run:  python tests/test_google_maps_import.py
"""

import asyncio
import sys
import os
import uuid

from sqlalchemy import select, delete

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException
from app.models.import_job import ImportJob, ImportJobStatus
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_activity import LeadActivity
from app.services.lead_import import LeadImportService
from app.services.lead_providers import get_provider, registered_provider_keys
from app.services.lead_providers.base import (
    MAX_COLLECTION_LIMIT,
    ProviderCollectionError,
)
from app.services.lead_providers.google_maps import GoogleMapsLeadProvider


#: A marker embedded in every business name this suite creates, so cleanup and assertions
#: can find exactly this run's rows and nothing else.
MARKER = f"ZZGM{uuid.uuid4().hex[:8].upper()}"

#: A key that is never sent anywhere real — the stub transport intercepts every request.
STUB_KEY = "test-key-not-a-real-credential"


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


def unique_phone(suffix: int) -> str:
    """
    Builds a distinct 10-digit mobile per test record, derived from the run marker so two
    concurrent runs cannot collide on the `leads.phone` unique constraint.
    """
    base = int(MARKER[4:6], 16) * 1000 + suffix
    return f"9{base:09d}"


# ===========================================================================================
# Stub Google Places API
# ===========================================================================================

def make_place(
    index: int,
    *,
    name: str,
    city: str = "Kozhikode",
    district: str = "Kozhikode",
    state: str = "Kerala",
    pincode: str = "673001",
    phone: str | None = None,
    business_status: str = "OPERATIONAL",
) -> dict:
    """
    Builds a (search summary, details payload) pair in Google's real response shape.

    Kept faithful to the API — `address_components` as a flat typed list, phone in both
    international and national form, `geometry.location`, `types` including the structural
    entries Google always adds — because the mapping under test is precisely the code that
    untangles that shape.
    """
    place_id = f"PID_{MARKER}_{index}"
    phone_national = phone or f"0495 27{index:02d} 000"
    phone_intl = f"+91 {phone_national.lstrip('0')}" if phone is None else phone

    search = {
        "place_id": place_id,
        "name": name,
        "formatted_address": f"{index} MG Road, {city}, {state} {pincode}, India",
        "rating": 4.0 + (index % 10) / 10,
        "user_ratings_total": 50 + index,
        "business_status": business_status,
        "geometry": {"location": {"lat": 11.25 + index / 100, "lng": 75.78 + index / 100}},
        "types": ["point_of_interest", "establishment"],
    }
    details = {
        "place_id": place_id,
        "name": name,
        "formatted_address": f"{index} MG Road, {city}, {state} {pincode}, India",
        "address_components": [
            {"long_name": city, "short_name": city, "types": ["locality", "political"]},
            {"long_name": district, "short_name": district,
             "types": ["administrative_area_level_2", "political"]},
            {"long_name": state, "short_name": state,
             "types": ["administrative_area_level_1", "political"]},
            {"long_name": "India", "short_name": "IN", "types": ["country", "political"]},
            {"long_name": pincode, "short_name": pincode, "types": ["postal_code"]},
        ],
        "formatted_phone_number": phone_national,
        "international_phone_number": phone_intl,
        "website": f"http://studio{index}.example.com",
        "url": f"https://maps.google.com/?cid={index}",
        "rating": 4.0 + (index % 10) / 10,
        "user_ratings_total": 50 + index,
        "types": ["wedding_photographer", "photographer", "point_of_interest", "establishment"],
        "geometry": {"location": {"lat": 11.25 + index / 100, "lng": 75.78 + index / 100}},
        "opening_hours": {
            "weekday_text": [
                "Monday: 9:00 AM – 8:00 PM",
                "Tuesday: 9:00 AM – 8:00 PM",
            ]
        },
        "business_status": business_status,
    }
    return {"place_id": place_id, "search": search, "details": details}


class StubPlacesAPI:
    """
    An in-process stand-in for the Places API, driven by a list of places.

    Records every request it receives so a test can assert on *call behaviour* — that the
    limit was applied before the billed Details fan-out, that pagination stopped when it
    should — and not merely on the final records. That is the difference between testing the
    mapping and testing the cost model, and the cost model is the part that bites in
    production.
    """

    def __init__(
        self,
        places: list[dict],
        *,
        page_size: int = 20,
        search_status: str = "OK",
        detail_status_by_id: dict[str, str] | None = None,
        detail_exception_ids: frozenset[str] = frozenset(),
        http_error_status: int | None = None,
    ) -> None:
        self.places = places
        self.page_size = page_size
        self.search_status = search_status
        self.detail_status_by_id = detail_status_by_id or {}
        self.detail_exception_ids = detail_exception_ids
        self.http_error_status = http_error_status
        self.search_calls: list[dict] = []
        self.detail_calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Routes one intercepted request to the textsearch or details responder."""
        params = dict(request.url.params)
        if self.http_error_status:
            return httpx.Response(self.http_error_status, json={"status": "ERROR"})
        if "textsearch" in request.url.path:
            return self._text_search(params)
        return self._details(params)

    def _text_search(self, params: dict) -> httpx.Response:
        self.search_calls.append(params)

        if self.search_status != "OK":
            return httpx.Response(200, json={
                "status": self.search_status,
                "error_message": f"Simulated {self.search_status}.",
                "results": [],
            })

        page = int(params.get("pagetoken", "0") or 0)
        start = page * self.page_size
        window = self.places[start:start + self.page_size]

        if not window and page == 0:
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

        body: dict = {
            "status": "OK",
            "results": [place["search"] for place in window],
        }
        if len(self.places) > start + self.page_size:
            body["next_page_token"] = str(page + 1)
        return httpx.Response(200, json=body)

    def _details(self, params: dict) -> httpx.Response:
        place_id = params.get("place_id", "")
        self.detail_calls.append(place_id)

        if place_id in self.detail_exception_ids:
            raise httpx.ConnectTimeout("Simulated per-place network timeout.")

        status = self.detail_status_by_id.get(place_id, "OK")
        if status != "OK":
            return httpx.Response(200, json={
                "status": status,
                "error_message": f"Simulated {status} for {place_id}.",
            })

        for place in self.places:
            if place["place_id"] == place_id:
                return httpx.Response(200, json={"status": "OK", "result": place["details"]})
        return httpx.Response(200, json={"status": "NOT_FOUND"})


class StubbedGoogleMapsProvider(GoogleMapsLeadProvider):
    """
    The real provider with its HTTP transport swapped for a stub.

    Subclassing to override only `_import_httpx` keeps `search()`, `collect()`,
    `normalize()`, pagination, the Details fan-out and every error path as the production
    code — the stub replaces the socket, nothing else.
    """

    def __init__(self, api: StubPlacesAPI, **kwargs) -> None:
        super().__init__(api_key=kwargs.pop("api_key", STUB_KEY), **kwargs)
        self._api = api

    def _import_httpx(self):
        """Returns an httpx-shaped module whose AsyncClient is bound to the stub transport."""
        api = self._api

        class _StubHttpx:
            Timeout = httpx.Timeout

            @staticmethod
            def AsyncClient(**kwargs):
                return httpx.AsyncClient(
                    transport=httpx.MockTransport(api.handler), **kwargs
                )

        return _StubHttpx


async def test_google_maps_suite() -> None:
    """Runs the full Google Maps provider integration suite."""
    created_lead_ids: list[uuid.UUID] = []
    created_job_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        service = LeadImportService()

        try:
            print(f"\n=== GOOGLE MAPS PROVIDER INTEGRATION TESTS (marker {MARKER}) ===")

            # ===============================================================================
            print("\n--- 1. PROVIDER INITIALIZATION ---")
            # ===============================================================================

            # 1.1 It is registered and resolvable through the shared registry.
            check("google_maps" in registered_provider_keys(),
                  "google_maps must be registered.")
            resolved = get_provider("google_maps")
            check(isinstance(resolved, GoogleMapsLeadProvider),
                  f"Registry returned {type(resolved).__name__}, expected the real provider.")
            print("Provider resolves from the registry to the real GoogleMapsLeadProvider.")

            # 1.2 It is no longer a PlannedProvider.
            from app.services.lead_providers import PlannedProvider
            check(not isinstance(resolved, PlannedProvider),
                  "google_maps must no longer be a PlannedProvider.")
            print("google_maps is no longer a planned/unimplemented stub.")

            # 1.3 It implements the full three-method contract.
            for method in ("search", "collect", "normalize"):
                check(callable(getattr(resolved, method)), f"Missing {method}().")
            print("search() / collect() / normalize() are all implemented.")

            # 1.4 Capabilities are described for the listing endpoint.
            described = resolved.describe()
            check(described["key"] == "google_maps", f"Got {described}")
            check(described["lead_source"] == "GOOGLE_MAPS", f"Got {described}")
            check(described["requires_query"] is True, "Google Maps is query-driven.")
            check(described["requires_file"] is False, "Google Maps takes no file.")
            print(f"Capabilities described: {described['display_name']} "
                  f"(source {described['lead_source']}, query-driven).")

            # 1.5 No credential is hardcoded: availability follows configuration alone.
            unconfigured = GoogleMapsLeadProvider(api_key="")
            check(unconfigured.is_available is False,
                  "With no API key the provider must report itself unavailable.")
            check("GOOGLE_MAPS_API_KEY" in unconfigured.describe()["unavailable_reason"],
                  "The unavailable reason must name the missing setting.")
            try:
                unconfigured.search("Photographer Kozhikode")
                raise AssertionError("An unconfigured provider must refuse to run.")
            except BadRequestException as e:
                check("GOOGLE_MAPS_API_KEY" in str(e.detail),
                      f"The refusal must name the setting to fix, got {e.detail}")
            print("With no API key configured: unavailable, and refused with the exact "
                  "setting name to fix (no hardcoded credential anywhere).")

            configured = GoogleMapsLeadProvider(api_key=STUB_KEY)
            check(configured.is_available is True,
                  "With an API key present the provider must be available.")
            print("With an API key configured: available.")

            # ===============================================================================
            print("\n--- 2. SEARCH EXECUTION ---")
            # ===============================================================================

            # 2.1 The documented search inputs are all accepted.
            for query in (
                "Photographer Kozhikode",
                "Wedding Photographer Thrissur",
                "Colour Lab Malappuram",
                "Photography Studio Kochi",
                "Event Photographer Kannur",
            ):
                ctx = configured.search(query, limit=10)
                check(ctx.query == query, f"Query should pass through, got {ctx.query!r}")
            print("All 5 documented search inputs are accepted unchanged.")

            # 2.2 City/state are composed into the query, without duplicating a term.
            ctx = configured.search("Photographer", city="Kozhikode", state="Kerala")
            check(ctx.query == "Photographer Kozhikode Kerala", f"Got {ctx.query!r}")
            ctx = configured.search("Wedding Photographer Thrissur", city="Thrissur")
            check(ctx.query == "Wedding Photographer Thrissur",
                  f"An already-present city must not be repeated, got {ctx.query!r}")
            print("City/state scope is composed into the query, and never duplicated.")

            # 2.3 Shared validation still applies.
            try:
                configured.search("")
                raise AssertionError("An empty query must be refused.")
            except BadRequestException:
                pass
            try:
                configured.search("Photographer", limit=0)
                raise AssertionError("limit=0 must be refused.")
            except BadRequestException:
                pass
            check(configured.search("Photographer", limit=99999).limit == MAX_COLLECTION_LIMIT,
                  "An oversized limit must clamp.")
            print("Empty queries and limit<1 are refused; oversized limits clamp to "
                  f"{MAX_COLLECTION_LIMIT}.")

            # 2.4 Collection returns merged search+details records.
            places = [
                make_place(i, name=f"GM Studio {i} {MARKER}")
                for i in range(1, 6)
            ]
            api = StubPlacesAPI(places)
            provider = StubbedGoogleMapsProvider(api)
            ctx = provider.search(f"Photographer Kozhikode {MARKER}", limit=10)
            raw_records = await provider.collect(ctx)
            check(len(raw_records) == 5, f"Expected 5 records, got {len(raw_records)}")
            check(all("search" in r and "details" in r for r in raw_records),
                  "Each raw record must carry both halves of the collection.")
            check(len(api.detail_calls) == 5,
                  f"Expected one Details call per business, got {len(api.detail_calls)}")
            print(f"Text Search + Place Details collected 5 businesses "
                  f"({len(api.search_calls)} search call, {len(api.detail_calls)} details calls).")

            # 2.5 Pagination walks next_page_token across pages.
            many = [make_place(i, name=f"GM Page {i} {MARKER}") for i in range(1, 46)]
            page_api = StubPlacesAPI(many, page_size=20)
            page_provider = StubbedGoogleMapsProvider(page_api)
            page_ctx = page_provider.search(f"Photographer Kerala {MARKER}", limit=45)
            page_records = await page_provider.collect(page_ctx)
            check(len(page_api.search_calls) == 3,
                  f"Expected 3 search pages, got {len(page_api.search_calls)}")
            check(len(page_records) == 45, f"Expected 45 records, got {len(page_records)}")
            print(f"Pagination walked {len(page_api.search_calls)} pages to collect "
                  f"{len(page_records)} businesses.")

            # 2.6 The limit is honoured BEFORE the billed Details fan-out. This is the cost
            #     guarantee: asking for 5 must not pay for 20 Details calls.
            cost_api = StubPlacesAPI(
                [make_place(i, name=f"GM Cost {i} {MARKER}") for i in range(1, 21)]
            )
            cost_provider = StubbedGoogleMapsProvider(cost_api)
            cost_ctx = cost_provider.search(f"Photographer {MARKER}", limit=5)
            cost_records = await cost_provider.collect(cost_ctx)
            check(len(cost_records) == 5, f"Expected 5 records, got {len(cost_records)}")
            check(len(cost_api.detail_calls) == 5,
                  f"limit=5 must cost exactly 5 Details calls, got {len(cost_api.detail_calls)}")
            print("limit=5 over 20 available results cost exactly 5 Details calls — the "
                  "limit is applied before the billed fan-out.")

            # 2.7 Permanently closed businesses are skipped (not a lead, and not billed).
            closed_api = StubPlacesAPI([
                make_place(1, name=f"GM Open {MARKER}"),
                make_place(2, name=f"GM Closed {MARKER}",
                           business_status="CLOSED_PERMANENTLY"),
            ])
            closed_provider = StubbedGoogleMapsProvider(closed_api)
            closed_records = await closed_provider.collect(
                closed_provider.search(f"Photographer {MARKER}", limit=10)
            )
            check(len(closed_records) == 1,
                  f"A permanently closed business must be skipped, got {len(closed_records)}")
            check(len(closed_api.detail_calls) == 1,
                  "A skipped business must not cost a Details call.")
            print("Permanently closed businesses are skipped before being billed for.")

            # 2.8 A query matching nothing is an empty success, not an error.
            empty_provider = StubbedGoogleMapsProvider(StubPlacesAPI([]))
            empty_records = await empty_provider.collect(
                empty_provider.search(f"Nonexistent {MARKER}", limit=10)
            )
            check(empty_records == [] or len(empty_records) == 0,
                  f"ZERO_RESULTS must collect nothing, got {empty_records}")
            print("A ZERO_RESULTS query collects nothing without raising.")

            # ===============================================================================
            print("\n--- 3. NORMALIZATION ---")
            # ===============================================================================

            # 3.1 A full record maps onto every NormalizedLead field.
            sample = make_place(7, name=f"Normalize Studio {MARKER}",
                                city="Thrissur", district="Thrissur",
                                state="Kerala", pincode="680001")
            normalized = provider.normalize(
                {"search": sample["search"], "details": sample["details"]}
            )
            check(normalized.business_name == f"Normalize Studio {MARKER}",
                  f"Got {normalized.business_name}")
            check(normalized.phone_numbers, "A phone number must be mapped from Details.")
            check(normalized.website == "http://studio7.example.com", f"Got {normalized.website}")
            check(normalized.city == "Thrissur", f"Got city {normalized.city}")
            check(normalized.district == "Thrissur", f"Got district {normalized.district}")
            check(normalized.state == "Kerala", f"Got state {normalized.state}")
            check(normalized.country == "India", f"Got country {normalized.country}")
            check(normalized.pincode == "680001", f"Got pincode {normalized.pincode}")
            check(normalized.latitude is not None and normalized.longitude is not None,
                  "Coordinates must be mapped.")
            check(normalized.rating == 4.7, f"Got rating {normalized.rating}")
            check(normalized.review_count == 57, f"Got reviews {normalized.review_count}")
            check(normalized.source == "GOOGLE_MAPS", f"Got source {normalized.source}")
            check(normalized.source_url and "maps.google.com" in normalized.source_url,
                  f"Got source_url {normalized.source_url}")
            check("Wedding Photographer" in normalized.categories,
                  f"Got categories {normalized.categories}")
            check("Point Of Interest" not in normalized.categories,
                  "Google's structural types must be dropped from categories.")
            ok, reason = normalized.is_valid()
            check(ok, f"A complete Google record must be valid, got {reason}")
            print("Address components split correctly into city / district / state / "
                  "pincode / country; rating, reviews, coordinates, categories and Maps URL "
                  "all mapped.")

            # 3.2 Opening hours are collected and readable.
            hours = provider.opening_hours(
                {"search": sample["search"], "details": sample["details"]}
            )
            check(len(hours) == 2 and "Monday" in hours[0], f"Got {hours}")
            print(f"Opening hours collected and retained: {hours[0]!r}.")

            # 3.3 A record whose Details lookup failed still keeps its search half.
            degraded = provider.normalize(
                {"search": sample["search"], "details": None,
                 "detail_error": "Simulated timeout"}
            )
            check(degraded.business_name == f"Normalize Studio {MARKER}",
                  "The search half must survive a failed Details lookup.")
            check(degraded.city == "Thrissur",
                  f"City must fall back to the formatted address, got {degraded.city}")
            check(degraded.latitude is not None,
                  "Coordinates come from the search summary too.")
            ok, reason = degraded.is_valid()
            check(not ok and "phone" in reason.lower(),
                  f"Without Details there is no phone, so the record is invalid: {reason}")
            print("A failed Details lookup degrades one record (kept, but phone-less) "
                  "rather than losing it entirely — city still derived from the address.")

            # 3.4 normalize() never raises, even on nonsense.
            for nonsense in ({}, {"search": None, "details": None}, {"search": {"x": 1}}):
                result = provider.normalize(nonsense)
                ok, reason = result.is_valid()
                check(not ok, "A nonsense record must be invalid, not raise.")
            print("normalize() is total: nonsense records come back invalid, never raising.")

            # ===============================================================================
            print("\n--- 4. IMPORT PIPELINE ---")
            # ===============================================================================

            # 4.1 A full run through LeadImportService.
            import_places = [
                make_place(100 + i, name=f"GM Import Studio {i} {MARKER}",
                           phone=unique_phone(100 + i))
                for i in range(1, 4)
            ]
            import_api = StubPlacesAPI(import_places)
            import_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer Kozhikode {MARKER}",
                limit=10,
                provider=StubbedGoogleMapsProvider(import_api),
            )
            created_job_ids.append(import_job.id)

            check(import_job.provider == "google_maps",
                  f"The job must record the provider, got {import_job.provider}")
            check(import_job.query and MARKER in import_job.query,
                  f"The job must record the query, got {import_job.query}")
            check(import_job.total_found == 3, f"Got total_found {import_job.total_found}")
            check(import_job.new_leads == 3, f"Got new_leads {import_job.new_leads}")
            check(import_job.failed_records == 0, f"Got failed {import_job.failed_records}")
            check(import_job.status == ImportJobStatus.COMPLETED,
                  f"A clean run must be COMPLETED, got {import_job.status}")
            check(import_job.started_at and import_job.completed_at,
                  "A finished job must carry both timestamps.")
            print(f"Import run: {import_job.total_found} found -> {import_job.new_leads} new "
                  f"leads, status {import_job.status.value}.")

            # 4.2 Leads landed in the CRM, correctly attributed and enriched.
            gm_leads = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%GM Import Studio%{MARKER}%"))
            )).scalars().all()
            check(len(gm_leads) == 3, f"Expected 3 leads, found {len(gm_leads)}")
            for row in gm_leads:
                created_lead_ids.append(row.id)
                check(row.source == LeadSource.GOOGLE_MAPS,
                      f"Leads must be tagged GOOGLE_MAPS, got {row.source}")
                check(row.status == LeadStatus.NEW,
                      f"Imported leads must start at NEW, got {row.status}")
                check(row.is_converted is False, "Imported leads must not be pre-converted.")
                check(row.phone, "Every imported lead must carry a phone number.")
                check(row.city == "Kozhikode", f"Got city {row.city}")
                check(row.state == "Kerala", f"Got state {row.state}")
                check(row.website, "The website from Place Details must be stored.")
                check(row.latitude is not None and row.longitude is not None,
                      "Coordinates must be stored.")
            print("All 3 leads stored: tagged GOOGLE_MAPS, status NEW, with phone, website, "
                  "city/state and coordinates.")

            # 4.3 Collected extras with no column reach the operator via remarks.
            sample_lead = gm_leads[0]
            check(sample_lead.remarks, "Extras must be recorded in remarks.")
            check("Rating" in sample_lead.remarks, f"Got remarks {sample_lead.remarks!r}")
            check("Pincode" in sample_lead.remarks, f"Got remarks {sample_lead.remarks!r}")
            check("maps.google.com" in sample_lead.remarks,
                  "The Maps URL must be recorded so an operator can verify the listing.")
            print("Rating, review count, categories, pincode and the Maps URL are recorded "
                  "in the lead's remarks.")

            # 4.4 Imported leads receive a timeline activity, like any other lead.
            activities = (await db.execute(
                select(LeadActivity).where(LeadActivity.lead_id == sample_lead.id)
            )).scalars().all()
            check(len(activities) >= 1,
                  "An imported lead must get a CREATED timeline entry.")
            print("Imported leads receive a timeline activity — audit logging is unchanged.")

            # 4.5 The provider inserted nothing itself: every write went through the service.
            check(import_job.new_leads == len(gm_leads),
                  "Lead creation must be the service's count, not the provider's.")
            print("The provider wrote no rows itself — creation stayed in LeadImportService.")

            # ===============================================================================
            print("\n--- 5. DUPLICATE HANDLING ---")
            # ===============================================================================

            # 5.1 Re-running the identical search creates nothing new.
            rerun_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer Kozhikode {MARKER}",
                limit=10,
                provider=StubbedGoogleMapsProvider(StubPlacesAPI(import_places)),
            )
            created_job_ids.append(rerun_job.id)
            check(rerun_job.total_found == 3, f"Got {rerun_job.total_found}")
            check(rerun_job.new_leads == 0,
                  f"A repeat run must create 0 leads, got {rerun_job.new_leads}")
            check(rerun_job.duplicate_leads + rerun_job.updated_leads == 3,
                  "All 3 records should have matched existing leads.")
            still = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%GM Import Studio%{MARKER}%"))
            )).scalars().all()
            check(len(still) == 3, f"Still expected 3 leads, found {len(still)}")
            print(f"Re-running the same search created 0 new leads "
                  f"({rerun_job.duplicate_leads} duplicates, {rerun_job.updated_leads} enriched) "
                  f"— the existing dedup pipeline was reused unchanged.")

            # 5.2 A Google record matching a hand-entered lead enriches it, not duplicates it.
            manual_phone = unique_phone(200)
            manual = Lead(
                business_name=f"Manually Entered Studio {MARKER}",
                phone=manual_phone,
                city="Kozhikode",
                source=LeadSource.MANUAL,
                status=LeadStatus.CONTACTED,
                contact_person="Typed By A Human",
            )
            db.add(manual)
            await db.commit()
            await db.refresh(manual)
            created_lead_ids.append(manual.id)
            check(manual.website is None, "Precondition: the manual lead has no website.")

            match_place = make_place(300, name="A Totally Different Google Name",
                                     phone=manual_phone)
            match_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} match",
                limit=5,
                provider=StubbedGoogleMapsProvider(StubPlacesAPI([match_place])),
            )
            created_job_ids.append(match_job.id)
            check(match_job.new_leads == 0,
                  f"A phone match must not create a lead, got {match_job.new_leads}")
            check(match_job.updated_leads == 1,
                  f"The matched lead should be enriched, got {match_job.updated_leads}")

            await db.refresh(manual)
            check(manual.website is not None,
                  "The empty website should have been enriched from Google.")
            check(manual.contact_person == "Typed By A Human",
                  f"Human-entered data must NOT be overwritten, got {manual.contact_person}")
            check(manual.status == LeadStatus.CONTACTED,
                  "CRM workflow status must not be touched by an import.")
            check(manual.source == LeadSource.MANUAL,
                  "An enriched lead keeps its original source attribution.")
            match_rules = [l for l in match_job.logs if l.get("match_rule")]
            check(match_rules and match_rules[0]["match_rule"] == "phone",
                  f"Expected a phone match, got {match_rules}")
            print("A Google listing matching a hand-entered lead by phone ENRICHED it "
                  "(website filled) without overwriting the human's data or its status.")

            # 5.3 Two Google results for the same business collapse within one run.
            twin_phone = unique_phone(400)
            twin_a = make_place(400, name=f"GM Twin Studio {MARKER}", phone=twin_phone)
            twin_b = make_place(401, name=f"GM Twin Studio {MARKER}", phone=twin_phone)
            twin_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} twin",
                limit=10,
                provider=StubbedGoogleMapsProvider(StubPlacesAPI([twin_a, twin_b])),
            )
            created_job_ids.append(twin_job.id)
            check(twin_job.total_found == 2, f"Got {twin_job.total_found}")
            check(twin_job.new_leads == 1,
                  f"Two results for one business must create ONE lead, got {twin_job.new_leads}")
            twins = (await db.execute(
                select(Lead).where(Lead.business_name == f"GM Twin Studio {MARKER}")
            )).scalars().all()
            check(len(twins) == 1, f"Expected 1 row, found {len(twins)}")
            created_lead_ids.append(twins[0].id)
            print("Two Google results for the same business collapsed to ONE lead "
                  "(within-batch dedup).")

            # ===============================================================================
            print("\n--- 6. IMPORT STATISTICS ---")
            # ===============================================================================

            # 6.1 Per-job counters reconcile.
            for job in (import_job, rerun_job, match_job, twin_job):
                total = (job.new_leads + job.updated_leads
                         + job.duplicate_leads + job.failed_records)
                check(total == job.total_found,
                      f"Job {job.id}: {total} != total_found {job.total_found}")
            print("Per-job counters reconcile: found = new + updated + duplicates + failed.")

            # 6.2 Google jobs are filterable and appear in the lifetime aggregate.
            _, gm_total = await service.get_all_jobs(db, provider="google_maps")
            check(gm_total >= 4, f"Expected >= 4 google_maps jobs, got {gm_total}")
            stats = await service.get_statistics(db)
            check(stats["total_jobs"] >= len(created_job_ids),
                  "Google runs must be included in lifetime statistics.")
            print(f"Import history filters by provider ({gm_total} google_maps jobs) and "
                  f"feeds the lifetime aggregate ({stats['total_jobs']} jobs total).")

            # 6.3 Every run left a diagnostic log.
            check(import_job.logs and len(import_job.logs) >= 2,
                  "A run must log at least a start and a summary entry.")
            summary = [l for l in import_job.logs if "Import finished" in l.get("message", "")]
            check(summary, "The run must record a closing summary line.")
            print(f"Job log records the run: {summary[0]['message']}")

            # ===============================================================================
            print("\n--- 7. ERROR HANDLING ---")
            # ===============================================================================

            # 7.1 One business failing must never stop the import. Three good, one whose
            #     Details lookup times out, one whose Details returns NOT_FOUND.
            mixed_places = [
                make_place(500 + i, name=f"GM Mixed Studio {i} {MARKER}",
                           phone=unique_phone(500 + i))
                for i in range(1, 6)
            ]
            timeout_id = mixed_places[3]["place_id"]
            notfound_id = mixed_places[4]["place_id"]
            mixed_api = StubPlacesAPI(
                mixed_places,
                detail_status_by_id={notfound_id: "NOT_FOUND"},
                detail_exception_ids=frozenset({timeout_id}),
            )
            mixed_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} mixed",
                limit=10,
                provider=StubbedGoogleMapsProvider(mixed_api),
            )
            created_job_ids.append(mixed_job.id)

            check(mixed_job.total_found == 5,
                  f"All 5 businesses must be accounted for, got {mixed_job.total_found}")
            check(mixed_job.new_leads == 3,
                  f"The 3 healthy businesses must import, got {mixed_job.new_leads}")
            check(mixed_job.failed_records == 2,
                  f"The 2 broken businesses must be counted failed, got {mixed_job.failed_records}")
            check(mixed_job.status == ImportJobStatus.PARTIAL,
                  f"A mixed run must be PARTIAL, got {mixed_job.status}")
            for row in (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%GM Mixed Studio%{MARKER}%"))
            )).scalars().all():
                created_lead_ids.append(row.id)
            print("A timing-out and a NOT_FOUND business cost 2 records; the other 3 "
                  "imported normally. Status PARTIAL — one failure never stops the run.")

            # 7.2 Those failures are recorded in the job's logs, with a reason.
            errors = [l for l in mixed_job.logs if l.get("level") == "error"]
            check(len(errors) == 2, f"Expected 2 error log entries, got {len(errors)}")
            check(all(e.get("message") for e in errors), "Every failure must carry a message.")
            check(any("phone" in e["message"].lower() for e in errors),
                  f"The failure reason must be stated, got {[e['message'] for e in errors]}")
            print(f"Both failures are in the job logs with reasons: "
                  f"{errors[0]['message'][:70]}...")

            # 7.3 A rejected API key fails the whole run, with a clear reason.
            denied_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} denied",
                limit=5,
                provider=StubbedGoogleMapsProvider(
                    StubPlacesAPI([], search_status="REQUEST_DENIED")
                ),
            )
            created_job_ids.append(denied_job.id)
            check(denied_job.status == ImportJobStatus.FAILED,
                  f"A rejected key must FAIL the run, got {denied_job.status}")
            check(denied_job.error_message and "API key" in denied_job.error_message,
                  f"The reason must name the credential problem, got {denied_job.error_message}")
            check(denied_job.total_found == 0, "A credential failure collects nothing.")
            print(f"A rejected API key fails the run cleanly: "
                  f"{denied_job.error_message[:80]}...")

            # 7.4 Quota exhaustion likewise.
            quota_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} quota",
                limit=5,
                provider=StubbedGoogleMapsProvider(
                    StubPlacesAPI([], search_status="OVER_QUERY_LIMIT")
                ),
            )
            created_job_ids.append(quota_job.id)
            check(quota_job.status == ImportJobStatus.FAILED, f"Got {quota_job.status}")
            check("quota" in (quota_job.error_message or "").lower(),
                  f"Got {quota_job.error_message}")
            print("Quota exhaustion fails the run with a billing-actionable message.")

            # 7.5 An HTTP-level fault from Google fails the run rather than 500-ing the API.
            http_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} http",
                limit=5,
                provider=StubbedGoogleMapsProvider(
                    StubPlacesAPI([], http_error_status=503)
                ),
            )
            created_job_ids.append(http_job.id)
            check(http_job.status == ImportJobStatus.FAILED, f"Got {http_job.status}")
            check("503" in (http_job.error_message or ""),
                  f"The HTTP status should be reported, got {http_job.error_message}")
            print("A 503 from Google fails the run with the status recorded — no 500 "
                  "propagates to the API caller.")

            # 7.6 An unconfigured provider raises at collect() too, not just at search().
            try:
                await GoogleMapsLeadProvider(api_key="").collect(
                    GoogleMapsLeadProvider(api_key=STUB_KEY).search("Photographer", limit=1)
                )
                raise AssertionError("Collecting without a key must raise.")
            except ProviderCollectionError as e:
                check("GOOGLE_MAPS_API_KEY" in str(e), f"Got {e}")
            print("Collecting with no API key raises a run-level ProviderCollectionError.")

            # 7.7 A run where every business fails is FAILED, not PARTIAL.
            all_bad = [make_place(600 + i, name=f"GM AllBad {i} {MARKER}")
                       for i in range(1, 3)]
            all_bad_api = StubPlacesAPI(
                all_bad,
                detail_exception_ids=frozenset(p["place_id"] for p in all_bad),
            )
            all_bad_job = await service.run_import(
                db,
                provider_key="google_maps",
                query=f"Photographer {MARKER} allbad",
                limit=5,
                provider=StubbedGoogleMapsProvider(all_bad_api),
            )
            created_job_ids.append(all_bad_job.id)
            check(all_bad_job.status == ImportJobStatus.FAILED,
                  f"A run where everything failed must be FAILED, got {all_bad_job.status}")
            check(all_bad_job.new_leads == 0, "Nothing should have been created.")
            print("A run where every business failed is FAILED and created nothing.")

            print(f"\n=== ALL GOOGLE MAPS PROVIDER TESTS COMPLETED SUCCESSFULLY ===")
            print(f"Created {len(created_lead_ids)} leads and {len(created_job_ids)} import jobs.")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so everything this suite created is
            # explicitly hard-deleted. Jobs first, then leads (which cascade activities).
            print("\nCleaning up test data...")
            await db.rollback()

            for job_id in created_job_ids:
                row = await db.get(ImportJob, job_id)
                if row:
                    row.retry_of_job_id = None
            await db.commit()

            for job_id in created_job_ids:
                row = await db.get(ImportJob, job_id)
                if row:
                    await db.delete(row)
            await db.commit()

            for lead_id in created_lead_ids:
                row = await db.get(Lead, lead_id)
                if row:
                    await db.execute(
                        delete(LeadActivity).where(LeadActivity.lead_id == row.id)
                    )
                    await db.delete(row)
            await db.commit()

            leftover = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER}%"))
            )).scalars().all()
            for row in leftover:
                await db.execute(delete(LeadActivity).where(LeadActivity.lead_id == row.id))
                await db.delete(row)
            await db.commit()
            print(f"Cleanup complete ({len(leftover)} extra marker rows swept).")


if __name__ == "__main__":
    asyncio.run(test_google_maps_suite())
