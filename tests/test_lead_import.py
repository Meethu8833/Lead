"""
tests/test_lead_import.py

Integration test suite for the Lead Collection Engine.
Verifies:
1.  Provider interface (ABC contract, registry resolution, unknown-provider refusal,
    planned-provider refusal, search() validation, capability descriptions, and that a
    brand-new provider can be added without touching the service).
2.  Normalization (phone/email/business/instagram/URL key derivation, multi-value
    de-duplication with order preserved, range checks, field cleaning, validity rules).
3.  Duplicate detection (by phone, by whatsapp column, by email, by business name + city,
    rule precedence, within-batch dedup, and non-matching records staying separate).
4.  Enrichment on match (empty fields filled, populated fields never overwritten,
    nothing-new counted as duplicate rather than update).
5.  CSV import (alias header mapping, multi-value cells, malformed rows, blank rows,
    headerless/empty file refusal, delimiter sniffing, dedup reuse).
6.  Import statistics (per-job counters reconcile as found = new + updated + duplicate +
    failed; lifetime aggregate).
7.  Job status lifecycle (COMPLETED / PARTIAL / FAILED, timestamps, logs, retry creating a
    linked new job, retry refusal rules).
8.  Isolation: the engine writes only to `leads` and `import_jobs` and leaves an
    unrelated lead untouched.

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block, since the repository layer commits each write
immediately (a session-level rollback would not undo already-committed work). Deleting a
Lead cascades away its activities.

Run:  python tests/test_lead_import.py
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.models.import_job import ImportJob, ImportJobStatus, RETRYABLE_STATUSES
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_activity import LeadActivity
from app.schemas.import_job import ImportRunRequest
from app.services.lead_import import LeadImportService
from app.services.lead_providers import (
    LeadProvider,
    NormalizedLead,
    PlannedProvider,
    ProviderCollectionError,
    ProviderContext,
    get_provider,
    list_providers,
    register_provider,
    registered_provider_keys,
)
from app.services.lead_providers.base import MAX_COLLECTION_LIMIT
from app.services.lead_providers.csv_provider import CsvLeadProvider, build_column_map
from app.services.lead_providers.mock import MockLeadProvider
from app.services.lead_providers.normalized import (
    normalize_business_key,
    normalize_email,
    normalize_instagram,
    normalize_phone,
    normalize_url,
)


# A marker embedded in every business name this suite creates, so cleanup and assertions
# can find exactly this run's rows and nothing else.
MARKER = f"ZZTEST{uuid.uuid4().hex[:8].upper()}"


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


def unique_phone(suffix: int) -> str:
    """
    Builds a distinct 10-digit mobile per test record. Derived from the run marker so two
    concurrent runs of this suite cannot collide on the `leads.phone` unique constraint.
    """
    base = int(MARKER[6:8], 16) * 1000 + suffix
    return f"9{base:09d}"


# ===========================================================================================
# Test doubles
# ===========================================================================================

class StaticTestProvider(LeadProvider):
    """
    A provider whose records are handed to it at construction.

    This is the workhorse double for the dedup/enrichment tests: it lets a test state
    exactly what a source returned, without a fixture generator in the way. It is
    deliberately NOT registered, proving `LeadImportService` accepts any object satisfying
    the interface.
    """

    key = "static_test"
    display_name = "Static Test Provider"
    lead_source = "OTHER"
    requires_query = False

    def __init__(self, records: list[dict] | None = None) -> None:
        self._records = records or []

    async def collect(self, context: ProviderContext):
        return self._records[: context.limit]

    def normalize(self, raw: dict) -> NormalizedLead:
        return NormalizedLead(
            business_name=raw.get("business_name"),
            owner_name=raw.get("owner_name"),
            phone_numbers=list(raw.get("phone_numbers") or []),
            emails=list(raw.get("emails") or []),
            website=raw.get("website"),
            instagram=raw.get("instagram"),
            facebook=raw.get("facebook"),
            address=raw.get("address"),
            city=raw.get("city"),
            district=raw.get("district"),
            state=raw.get("state"),
            country=raw.get("country"),
            pincode=raw.get("pincode"),
            latitude=raw.get("latitude"),
            longitude=raw.get("longitude"),
            rating=raw.get("rating"),
            review_count=raw.get("review_count"),
            source=raw.get("source") or self.lead_source,
            source_url=raw.get("source_url"),
            categories=list(raw.get("categories") or []),
            raw=raw,
        ).normalize()


class ExplodingProvider(LeadProvider):
    """A provider whose source is unreachable, for the run-level failure path."""

    key = "exploding_test"
    display_name = "Exploding Test Provider"
    requires_query = False

    async def collect(self, context: ProviderContext):
        raise ProviderCollectionError("Source unreachable (simulated).")

    def normalize(self, raw: dict) -> NormalizedLead:
        return NormalizedLead().normalize()


class BadNormalizeProvider(LeadProvider):
    """
    A provider that violates the contract by raising from `normalize()`, to prove
    `collect_normalized` contains it rather than letting one row abort the run.
    """

    key = "bad_normalize_test"
    display_name = "Bad Normalize Test Provider"
    requires_query = False

    async def collect(self, context: ProviderContext):
        return [{"ok": True}, {"ok": False}]

    def normalize(self, raw: dict) -> NormalizedLead:
        if not raw["ok"]:
            raise ValueError("deliberate normalize failure")
        return NormalizedLead(
            business_name=f"Good Record {MARKER}",
            phone_numbers=[unique_phone(910)],
            city="Bengaluru",
        ).normalize()


async def test_lead_import_suite() -> None:
    """Runs the full Lead Collection Engine integration suite."""
    created_lead_ids: list[uuid.UUID] = []
    created_job_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        service = LeadImportService()

        try:
            print(f"\n=== LEAD COLLECTION ENGINE INTEGRATION TESTS (marker {MARKER}) ===")

            # ===============================================================================
            print("\n--- 1. PROVIDER INTERFACE ---")
            # ===============================================================================

            # 1.1 Every shipped provider satisfies the interface.
            keys = registered_provider_keys()
            for expected in (
                "mock", "csv", "google_maps", "overpass", "justdial", "facebook",
                "instagram", "indiamart", "wedding_directory",
            ):
                check(expected in keys, f"Provider '{expected}' is not registered.")
            print(f"All 9 providers are registered: {', '.join(keys)}")

            for key in keys:
                provider = get_provider(key)
                check(isinstance(provider, LeadProvider), f"'{key}' is not a LeadProvider.")
                check(callable(provider.search), f"'{key}' has no search().")
                check(callable(provider.collect), f"'{key}' has no collect().")
                check(callable(provider.normalize), f"'{key}' has no normalize().")
            print("Every registered provider implements search() / collect() / normalize().")

            # 1.2 The ABC cannot be instantiated directly.
            try:
                LeadProvider()  # type: ignore[abstract]
                raise AssertionError("Abstract LeadProvider should not be instantiable.")
            except TypeError:
                print("Abstract LeadProvider correctly refuses direct instantiation.")

            # 1.3 Unknown provider is refused (not silently defaulted).
            try:
                get_provider("no_such_provider")
                raise AssertionError("Unknown provider should raise.")
            except BadRequestException as e:
                check("Unknown lead provider" in str(e.detail), f"Wrong message: {e.detail}")
                print("Unknown provider key is refused rather than silently defaulted.")

            # 1.4 Planned-but-unimplemented providers refuse to run, with a clear reason.
            #     `google_maps` and `instagram` are deliberately absent from this list: they
            #     now have real implementations (see tests/test_google_maps_import.py and
            #     tests/test_instagram_import.py). That each could be moved off this list by
            #     adding one module and deleting one class — with no change to
            #     LeadImportService, the endpoints, the schemas or the database — is the
            #     extensibility property asserted in 1.7.
            for planned_key in ("justdial", "facebook", "indiamart", "wedding_directory"):
                provider = get_provider(planned_key)
                check(isinstance(provider, PlannedProvider), f"'{planned_key}' should be planned.")
                check(provider.is_available is False, f"'{planned_key}' should be unavailable.")
                try:
                    provider.search("wedding photographers")
                    raise AssertionError(f"'{planned_key}' should refuse to run.")
                except BadRequestException as e:
                    check("not yet implemented" in str(e.detail), f"Wrong message: {e.detail}")
            print("All 4 remaining planned providers are declared, discoverable, and refuse "
                  "to run.")

            # 1.4b Google Maps and Instagram are implemented, not planned.
            google = get_provider("google_maps")
            check(not isinstance(google, PlannedProvider),
                  "google_maps must no longer be a PlannedProvider.")
            instagram = get_provider("instagram")
            check(not isinstance(instagram, PlannedProvider),
                  "instagram must no longer be a PlannedProvider.")
            print("google_maps is a real implemented provider (covered by "
                  "tests/test_google_maps_import.py).")
            print("instagram is a real implemented provider (covered by "
                  "tests/test_instagram_import.py).")

            # 1.5 search() validation.
            mock = get_provider("mock")
            try:
                mock.search("")
                raise AssertionError("A query-driven provider should require a query.")
            except BadRequestException:
                print("Query-driven provider requires a non-empty query.")

            csv_provider = get_provider("csv")
            try:
                csv_provider.search(None)
                raise AssertionError("The CSV provider should require a file.")
            except BadRequestException:
                print("File-driven provider requires an uploaded file.")

            ctx = mock.search("photographers", limit=99999)
            check(ctx.limit == MAX_COLLECTION_LIMIT,
                  f"limit should clamp to {MAX_COLLECTION_LIMIT}, got {ctx.limit}")
            print(f"An oversized limit clamps to MAX_COLLECTION_LIMIT ({MAX_COLLECTION_LIMIT}).")

            try:
                mock.search("photographers", limit=0)
                raise AssertionError("limit=0 should be refused.")
            except BadRequestException:
                print("A limit below 1 is refused.")

            # 1.6 describe() powers the provider-listing endpoint.
            described = list_providers()
            check(len(described) == len(keys), "describe() count mismatch.")
            check(all({"key", "display_name", "is_available"} <= set(d) for d in described),
                  "describe() is missing required fields.")
            print("Provider capability descriptions are complete.")

            # 1.7 A NEW provider can be added without touching the service — the core
            #     extensibility requirement.
            @register_provider
            class AdHocProvider(LeadProvider):
                key = "adhoc_test"
                display_name = "Ad-hoc Test Provider"
                lead_source = "OTHER"
                requires_query = False

                async def collect(self, context):
                    return [{"n": f"Adhoc Studio {MARKER}"}]

                def normalize(self, raw):
                    return NormalizedLead(
                        business_name=raw["n"],
                        phone_numbers=[unique_phone(900)],
                        city="Kochi",
                    ).normalize()

            check("adhoc_test" in registered_provider_keys(), "Ad-hoc provider not registered.")
            adhoc_job = await service.run_import(db, provider_key="adhoc_test")
            created_job_ids.append(adhoc_job.id)
            check(adhoc_job.new_leads == 1,
                  f"Ad-hoc provider should create 1 lead, got {adhoc_job.new_leads}")
            adhoc_lead = (await db.execute(
                select(Lead).where(Lead.business_name == f"Adhoc Studio {MARKER}")
            )).scalars().first()
            check(adhoc_lead is not None, "Ad-hoc provider's lead was not created.")
            created_lead_ids.append(adhoc_lead.id)
            print("A brand-new provider registered and ran with ZERO changes to "
                  "LeadImportService — extensibility requirement satisfied.")

            # ===============================================================================
            print("\n--- 2. NORMALIZATION ---")
            # ===============================================================================

            # 2.1 Phone key derivation handles every format seen in the wild.
            for raw_phone, expected in [
                ("9876543210", "9876543210"),
                ("+91 98765 43210", "9876543210"),
                ("098765-43210", "9876543210"),
                ("(+91) 98765 43210", "9876543210"),
                ("919876543210", "9876543210"),
                ("123", None),          # too few digits
                ("", None),
                (None, None),
            ]:
                got = normalize_phone(raw_phone)
                check(got == expected, f"normalize_phone({raw_phone!r}) = {got!r}, want {expected!r}")
            print("Phone normalization collapses all 5 common Indian formats onto one key.")

            # 2.2 Email + business key.
            check(normalize_email("  Studio@Example.COM ") == "studio@example.com",
                  "Email normalization failed.")
            check(normalize_email("not-an-email") is None, "Malformed email should yield no key.")
            check(
                normalize_business_key("Sunrise Photography.", "Bengaluru")
                == normalize_business_key("SUNRISE  photography", " bengaluru "),
                "Business key should ignore case, punctuation and spacing.",
            )
            check(normalize_business_key("Sunrise", None) is None,
                  "A business key without a city must not be produced.")
            print("Email and business-name+city keys normalize as specified.")

            # 2.3 Instagram and URL handling.
            check(normalize_instagram("https://www.instagram.com/studio_x/") == "studio_x",
                  "Instagram URL should reduce to a handle.")
            check(normalize_instagram("@studio_x") == "studio_x", "@-prefix should be stripped.")
            check(normalize_instagram("not a handle!") is None, "Illegal handle should be dropped.")
            check(normalize_url("studio.example.com") == "https://studio.example.com",
                  "A bare host should gain a scheme.")
            check(normalize_url("https://studio.example.com") == "https://studio.example.com",
                  "An absolute URL should be preserved.")
            print("Instagram handles and URLs are normalized to CRM-acceptable values.")

            # 2.4 A full record normalizes, de-duplicating multi-values while keeping order.
            messy = NormalizedLead(
                business_name="  Messy   Studio  ",
                phone_numbers=["+91 98765 43210", "098765-43210", "080 2345 6789", "junk"],
                emails=["A@B.com", "a@b.com", "bad", "second@b.com"],
                website="studio.example.com",
                instagram="@messy_studio",
                latitude="12.97",
                longitude=999,           # out of range -> dropped
                rating="4.5",
                review_count="1,234 reviews",
                categories=["Wedding", "wedding", "Portrait"],
                pincode="PIN: 560 001",
            ).normalize()

            check(messy.business_name == "Messy Studio", f"Got {messy.business_name!r}")
            check(len(messy.phone_numbers) == 2,
                  f"Duplicate/invalid phones should collapse to 2, got {messy.phone_numbers}")
            check(messy.phone_numbers[0] == "+91 98765 43210",
                  "Provider ordering must be preserved (first number stays primary).")
            check(messy.emails == ["a@b.com", "second@b.com"], f"Got {messy.emails}")
            check(messy.website == "https://studio.example.com", f"Got {messy.website}")
            check(messy.latitude == 12.97, f"Got {messy.latitude}")
            check(messy.longitude is None, "An out-of-range longitude should be dropped.")
            check(messy.rating == 4.5 and messy.review_count == 1234,
                  f"Got rating={messy.rating}, reviews={messy.review_count}")
            check(messy.categories == ["Wedding", "Portrait"], f"Got {messy.categories}")
            check(messy.pincode == "560001", f"Got {messy.pincode}")
            print("A messy record normalizes correctly: values de-duplicated, order preserved, "
                  "out-of-range values dropped.")

            # 2.5 Validity rules.
            ok, reason = messy.is_valid()
            check(ok, f"A complete record should be valid, got {reason}")
            ok, reason = NormalizedLead(business_name="No Phone Studio").normalize().is_valid()
            check(not ok and "phone" in reason.lower(), f"Expected a phone reason, got {reason}")
            ok, reason = NormalizedLead(phone_numbers=["9876543210"]).normalize().is_valid()
            check(not ok and "business_name" in reason, f"Expected a name reason, got {reason}")
            print("Validity rules require both a business name and at least one phone number.")

            # 2.6 Every provider returns the SAME normalized shape.
            mock_ctx = mock.search(f"photographers {MARKER}", limit=3)
            mock_records = await mock.collect_normalized(mock_ctx)
            check(all(isinstance(r, NormalizedLead) for r in mock_records),
                  "MockProvider must return NormalizedLead instances.")
            csv_bytes = f"Business Name,Phone,City\nShape Check {MARKER},{unique_phone(1)},Kochi\n".encode()
            csv_ctx = csv_provider.search(None, file_content=csv_bytes, filename="s.csv")
            csv_records = await csv_provider.collect_normalized(csv_ctx)
            check(all(isinstance(r, NormalizedLead) for r in csv_records),
                  "CsvProvider must return NormalizedLead instances.")
            check(
                {f.name for f in mock_records[0].__dataclass_fields__.values()}
                == {f.name for f in csv_records[0].__dataclass_fields__.values()},
                "Providers must return an identical normalized shape.",
            )
            print("Mock and CSV providers return an identical NormalizedLead shape.")

            # 2.7 A provider that violates the no-raise contract is contained.
            bad_job = await service.run_import(db, provider_key="x", provider=BadNormalizeProvider())
            created_job_ids.append(bad_job.id)
            check(bad_job.total_found == 2, f"Expected 2 records, got {bad_job.total_found}")
            check(bad_job.new_leads == 1, f"The good record should import, got {bad_job.new_leads}")
            check(bad_job.failed_records == 1, f"The raising record should fail, got {bad_job.failed_records}")
            check(bad_job.status == ImportJobStatus.PARTIAL, f"Got {bad_job.status}")
            bad_lead = (await db.execute(
                select(Lead).where(Lead.business_name == f"Good Record {MARKER}")
            )).scalars().first()
            if bad_lead:
                created_lead_ids.append(bad_lead.id)
            print("A provider raising from normalize() costs one record, not the whole run.")

            # ===============================================================================
            print("\n--- 3. DUPLICATE DETECTION ---")
            # ===============================================================================

            # 3.1 Seed a baseline lead.
            base_phone = unique_phone(10)
            seed_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": f"Dedup Base Studio {MARKER}",
                    "owner_name": "Original Owner",
                    "phone_numbers": [base_phone],
                    "emails": ["base@dedup.example.com"],
                    "city": "Bengaluru",
                    "district": "Bengaluru Urban",
                }]),
            )
            created_job_ids.append(seed_job.id)
            check(seed_job.new_leads == 1, f"Seed should create 1 lead, got {seed_job.new_leads}")
            base_lead = (await db.execute(
                select(Lead).where(Lead.business_name == f"Dedup Base Studio {MARKER}")
            )).scalars().first()
            check(base_lead is not None, "Seed lead was not created.")
            created_lead_ids.append(base_lead.id)
            print(f"Baseline lead created (phone {base_phone}).")

            # 3.2 Duplicate by phone, in a DIFFERENT format.
            phone_dupe_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": "A Completely Different Name",
                    "phone_numbers": [f"+91 {base_phone[:5]} {base_phone[5:]}"],
                    "city": "Mysuru",
                }]),
            )
            created_job_ids.append(phone_dupe_job.id)
            check(phone_dupe_job.new_leads == 0,
                  f"A phone duplicate must not create a lead, got {phone_dupe_job.new_leads}")
            check(phone_dupe_job.updated_leads + phone_dupe_job.duplicate_leads == 1,
                  "The record should have matched the existing lead.")
            phone_rule = [l for l in phone_dupe_job.logs if l.get("match_rule")]
            check(phone_rule and phone_rule[0]["match_rule"] == "phone",
                  f"Expected a phone match, got {phone_rule}")
            print("Duplicate detected by PHONE across differing formats (+91/spaces).")

            # 3.3 Duplicate by email.
            email_dupe_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": "Another Unrelated Name",
                    "phone_numbers": [unique_phone(11)],
                    "emails": ["BASE@Dedup.Example.COM"],
                    "city": "Chennai",
                }]),
            )
            created_job_ids.append(email_dupe_job.id)
            check(email_dupe_job.new_leads == 0,
                  f"An email duplicate must not create a lead, got {email_dupe_job.new_leads}")
            email_rule = [l for l in email_dupe_job.logs if l.get("match_rule")]
            check(email_rule and email_rule[0]["match_rule"] == "email",
                  f"Expected an email match, got {email_rule}")
            print("Duplicate detected by EMAIL, case-insensitively.")

            # 3.4 Duplicate by business name + city.
            name_dupe_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": f"DEDUP BASE STUDIO {MARKER}.",   # punctuation + case differ
                    "phone_numbers": [unique_phone(12)],
                    "city": " bengaluru ",
                }]),
            )
            created_job_ids.append(name_dupe_job.id)
            check(name_dupe_job.new_leads == 0,
                  f"A name+city duplicate must not create a lead, got {name_dupe_job.new_leads}")
            name_rule = [l for l in name_dupe_job.logs if l.get("match_rule")]
            check(name_rule and name_rule[0]["match_rule"] == "business_name_city",
                  f"Expected a business_name_city match, got {name_rule}")
            print("Duplicate detected by BUSINESS NAME + CITY, ignoring case and punctuation.")

            # 3.5 Same name in a DIFFERENT city is a different business.
            other_city_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": f"Dedup Base Studio {MARKER}",
                    "phone_numbers": [unique_phone(13)],
                    "city": "Chennai",
                }]),
            )
            created_job_ids.append(other_city_job.id)
            check(other_city_job.new_leads == 1,
                  f"Same name in another city is a new lead, got {other_city_job.new_leads}")
            other_city_lead = (await db.execute(
                select(Lead).where(
                    Lead.business_name == f"Dedup Base Studio {MARKER}",
                    Lead.city == "Chennai",
                )
            )).scalars().first()
            created_lead_ids.append(other_city_lead.id)
            print("The same business name in a different city correctly stays a separate lead.")

            # 3.6 Rule precedence: phone beats name+city when they point at different leads.
            precedence_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    # Name+city matches the Chennai lead; phone matches the Bengaluru lead.
                    "business_name": f"Dedup Base Studio {MARKER}",
                    "city": "Chennai",
                    "phone_numbers": [base_phone],
                }]),
            )
            created_job_ids.append(precedence_job.id)
            precedence_rule = [l for l in precedence_job.logs if l.get("match_rule")]
            check(precedence_rule and precedence_rule[0]["match_rule"] == "phone",
                  f"Phone must outrank name+city, got {precedence_rule}")
            check(precedence_rule[0]["lead_id"] == str(base_lead.id),
                  "The phone match should win and point at the Bengaluru lead.")
            print("Rule precedence holds: PHONE outranks BUSINESS NAME + CITY.")

            # 3.7 Dedup also matches against the `whatsapp` column.
            wa_phone = unique_phone(14)
            wa_seed = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": f"WhatsApp Column Studio {MARKER}",
                    "phone_numbers": [unique_phone(15), wa_phone],
                    "city": "Kochi",
                }]),
            )
            created_job_ids.append(wa_seed.id)
            wa_lead = (await db.execute(
                select(Lead).where(Lead.business_name == f"WhatsApp Column Studio {MARKER}")
            )).scalars().first()
            created_lead_ids.append(wa_lead.id)
            check(wa_lead.whatsapp is not None, "The second number should land in `whatsapp`.")
            wa_dupe = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": "Reached By Its Second Number",
                    "phone_numbers": [wa_phone],
                    "city": "Mysuru",
                }]),
            )
            created_job_ids.append(wa_dupe.id)
            check(wa_dupe.new_leads == 0,
                  "A number stored in the whatsapp column must still be matched.")
            print("Duplicate detection matches the `whatsapp` column, not just `phone`.")

            # 3.8 Within-batch dedup: one run, same business twice under two formats.
            batch_phone = unique_phone(20)
            batch_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([
                    {
                        "business_name": f"Batch Dupe Studio {MARKER}",
                        "phone_numbers": [batch_phone],
                        "city": "Mysuru",
                    },
                    {
                        "business_name": f"Batch Dupe Studio {MARKER}",
                        "phone_numbers": [f"+91-{batch_phone}"],
                        "city": "Mysuru",
                        "website": "batchdupe.example.com",
                    },
                ]),
            )
            created_job_ids.append(batch_job.id)
            check(batch_job.total_found == 2, f"Expected 2 records, got {batch_job.total_found}")
            check(batch_job.new_leads == 1,
                  f"Within-batch duplicates must create ONE lead, got {batch_job.new_leads}")
            batch_leads = (await db.execute(
                select(Lead).where(Lead.business_name == f"Batch Dupe Studio {MARKER}")
            )).scalars().all()
            check(len(batch_leads) == 1, f"Expected 1 row, found {len(batch_leads)}")
            created_lead_ids.append(batch_leads[0].id)
            check(batch_leads[0].website == "https://batchdupe.example.com",
                  "The second occurrence should have enriched the first.")
            print("Within-batch duplicates collapse to ONE lead, and the later record enriches it.")

            # ===============================================================================
            print("\n--- 4. ENRICHMENT ON MATCH ---")
            # ===============================================================================

            # 4.1 Empty fields are filled; populated fields are never overwritten.
            check(base_lead.website is None, "Precondition: the base lead has no website.")
            enrich_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": "Enricher",
                    "phone_numbers": [base_phone],
                    "owner_name": "SHOULD NOT OVERWRITE",     # base already has an owner
                    "website": "enriched.example.com",         # base has none -> fill
                    "instagram": "@enriched_handle",           # base has none -> fill
                    "state": "Karnataka",                      # base has none -> fill
                    "city": "SHOULD NOT OVERWRITE",            # base already has a city
                }]),
            )
            created_job_ids.append(enrich_job.id)
            check(enrich_job.updated_leads == 1,
                  f"Expected 1 enriched lead, got {enrich_job.updated_leads}")

            await db.refresh(base_lead)
            check(base_lead.website == "https://enriched.example.com",
                  f"Empty website should be filled, got {base_lead.website}")
            check(base_lead.instagram == "enriched_handle",
                  f"Empty instagram should be filled, got {base_lead.instagram}")
            check(base_lead.state == "Karnataka", f"Empty state should be filled, got {base_lead.state}")
            check(base_lead.contact_person == "Original Owner",
                  f"Populated owner must NOT be overwritten, got {base_lead.contact_person}")
            check(base_lead.city == "Bengaluru",
                  f"Populated city must NOT be overwritten, got {base_lead.city}")
            print("Enrichment fills empty fields and never overwrites populated ones.")

            # 4.2 A match carrying nothing new is a duplicate, not an update.
            noop_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": "Nothing New",
                    "phone_numbers": [base_phone],
                }]),
            )
            created_job_ids.append(noop_job.id)
            check(noop_job.updated_leads == 0,
                  f"Nothing new should not count as an update, got {noop_job.updated_leads}")
            check(noop_job.duplicate_leads == 1,
                  f"Nothing new should count as a duplicate, got {noop_job.duplicate_leads}")
            print("A match carrying nothing new is counted as a duplicate and writes nothing.")

            # 4.3 Re-running the same import is a true no-op — the headline guarantee.
            version_before = base_lead.version
            rerun_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([{
                    "business_name": f"Dedup Base Studio {MARKER}",
                    "owner_name": "Original Owner",
                    "phone_numbers": [base_phone],
                    "emails": ["base@dedup.example.com"],
                    "city": "Bengaluru",
                    "district": "Bengaluru Urban",
                }]),
            )
            created_job_ids.append(rerun_job.id)
            await db.refresh(base_lead)
            check(rerun_job.new_leads == 0, "Re-running must create no leads.")
            check(rerun_job.duplicate_leads == 1, "Re-running should report a pure duplicate.")
            check(base_lead.version == version_before,
                  f"A no-op re-run must not bump the version ({version_before} -> {base_lead.version}).")
            print("Re-running an identical import is a true no-op: no new rows, no version churn.")

            # 4.4 The MockProvider is deterministic, so a second run dedups entirely.
            mock_run_1 = await service.run_import(
                db, provider_key="mock", query=f"wedding photographers {MARKER}", limit=6
            )
            created_job_ids.append(mock_run_1.id)
            mock_lead_rows = (await db.execute(
                select(Lead).where(Lead.source == LeadSource.OTHER,
                                   Lead.created_at >= mock_run_1.started_at)
            )).scalars().all()
            for row in mock_lead_rows:
                if row.id not in created_lead_ids:
                    created_lead_ids.append(row.id)

            mock_run_2 = await service.run_import(
                db, provider_key="mock", query=f"wedding photographers {MARKER}", limit=6
            )
            created_job_ids.append(mock_run_2.id)
            check(mock_run_2.new_leads == 0,
                  f"A repeat mock run must create 0 leads, got {mock_run_2.new_leads}")
            check(mock_run_1.total_found == mock_run_2.total_found,
                  "The mock provider must be deterministic across runs.")
            print(f"Repeat MockProvider run over the same query created 0 new leads "
                  f"({mock_run_2.duplicate_leads + mock_run_2.updated_leads} matched).")

            # ===============================================================================
            print("\n--- 5. CSV IMPORT ---")
            # ===============================================================================

            # 5.1 Header alias mapping.
            column_map = build_column_map(
                ["Business Name", "Contact Person", "Phone", "Alternate Phone",
                 "Email ID", "Website", "City", "Unknown Column"]
            )
            check(column_map["business_name"] == ["Business Name"], f"Got {column_map}")
            check(column_map["phone_numbers"] == ["Phone", "Alternate Phone"],
                  f"Both phone columns should feed phone_numbers, got {column_map}")
            check("Unknown Column" not in str(column_map), "Unknown headers should not be mapped.")
            print("CSV headers map through aliases; multiple phone columns feed one field.")

            # 5.2 A realistic CSV with awkward rows.
            csv_text = (
                "Business Name,Contact Person,Phone,Email,City,District,Categories,Website\n"
                f"CSV Studio One {MARKER},Ravi Kumar,{unique_phone(30)},one@csv.example.com,Kochi,Ernakulam,\"Wedding, Portrait\",csvone.example.com\n"
                f"CSV Studio Two {MARKER},Priya S,\"{unique_phone(31)}; {unique_phone(32)}\",two@csv.example.com,Mysuru,Mysuru,Event,\n"
                "\n"                                                       # blank row -> skipped
                f"CSV No Phone {MARKER},Nobody,,nophone@csv.example.com,Kochi,Ernakulam,,\n"   # -> failed
                f",Missing Name,{unique_phone(33)},,Kochi,,,\n"            # no name -> failed
                f"CSV Studio One {MARKER},Ravi Kumar,{unique_phone(30)},one@csv.example.com,Kochi,,,\n"  # in-file dupe
            )
            csv_job = await service.run_import(
                db,
                provider_key="csv",
                file_content=csv_text.encode("utf-8"),
                filename="leads.csv",
            )
            created_job_ids.append(csv_job.id)

            check(csv_job.total_found == 5,
                  f"5 data rows expected (blank skipped), got {csv_job.total_found}")
            check(csv_job.new_leads == 2, f"Expected 2 new leads, got {csv_job.new_leads}")
            check(csv_job.failed_records == 2, f"Expected 2 failed rows, got {csv_job.failed_records}")
            check(csv_job.status == ImportJobStatus.PARTIAL,
                  f"A mixed run should be PARTIAL, got {csv_job.status}")

            for name in (f"CSV Studio One {MARKER}", f"CSV Studio Two {MARKER}"):
                row = (await db.execute(select(Lead).where(Lead.business_name == name))).scalars().first()
                check(row is not None, f"'{name}' was not imported.")
                created_lead_ids.append(row.id)
                check(row.source == LeadSource.CSV_IMPORT,
                      f"CSV leads must be tagged CSV_IMPORT, got {row.source}")

            two = (await db.execute(
                select(Lead).where(Lead.business_name == f"CSV Studio Two {MARKER}")
            )).scalars().first()
            check(two.whatsapp is not None,
                  "A multi-value phone cell should populate both phone and whatsapp.")
            one = (await db.execute(
                select(Lead).where(Lead.business_name == f"CSV Studio One {MARKER}")
            )).scalars().first()
            check(one.website == "https://csvone.example.com", f"Got {one.website}")
            check(one.remarks and "Wedding" in one.remarks,
                  "Categories should be retained in remarks.")
            print("CSV import: 5 rows -> 2 new, 2 failed (no phone / no name), 1 in-file duplicate. "
                  "Blank rows skipped; multi-value cells split.")

            # 5.3 Failed rows are reported with their row number.
            failures = [l for l in csv_job.logs if l.get("level") == "error"]
            check(len(failures) == 2, f"Expected 2 error entries, got {len(failures)}")
            check(all("row" in f["message"] for f in failures),
                  f"Failures must name the row: {failures}")
            print(f"Failed rows are reported by row number: "
                  f"{[f['message'].split(':')[0] for f in failures]}")

            # 5.4 Semicolon-delimited files work (delimiter sniffing).
            semi_csv = (
                "Studio;Mobile;Town\n"
                f"Semicolon Studio {MARKER};{unique_phone(40)};Chennai\n"
            )
            semi_job = await service.run_import(
                db, provider_key="csv", file_content=semi_csv.encode(), filename="semi.csv"
            )
            created_job_ids.append(semi_job.id)
            check(semi_job.new_leads == 1,
                  f"A semicolon-delimited file should import, got {semi_job.new_leads}")
            semi_lead = (await db.execute(
                select(Lead).where(Lead.business_name == f"Semicolon Studio {MARKER}")
            )).scalars().first()
            created_lead_ids.append(semi_lead.id)
            print("Semicolon-delimited CSV with alias headers (Studio/Mobile/Town) imported.")

            # 5.5 CSV dedup reuses the same rules as any other provider.
            dupe_csv = (
                "Business Name,Phone,City\n"
                f"Totally New Name,+91 {unique_phone(30)},Kochi\n"
            )
            csv_dupe_job = await service.run_import(
                db, provider_key="csv", file_content=dupe_csv.encode(), filename="dupe.csv"
            )
            created_job_ids.append(csv_dupe_job.id)
            check(csv_dupe_job.new_leads == 0,
                  "A CSV row duplicating an existing phone must not create a lead.")
            print("CSV import reuses the shared duplicate detection.")

            # 5.6 File-level failures.
            for bad_content, description in [
                (b"", "an empty file"),
                (b"col_a,col_b\n1,2\n", "a file with no recognisable columns"),
                ("Business Name,Phone\n".encode(), "a header with no data rows"),
            ]:
                bad_csv_job = await service.run_import(
                    db, provider_key="csv", file_content=bad_content or b" ", filename="bad.csv"
                )
                created_job_ids.append(bad_csv_job.id)
                check(bad_csv_job.status == ImportJobStatus.FAILED,
                      f"{description} should FAIL the run, got {bad_csv_job.status}")
                check(bad_csv_job.error_message, f"{description} should record a reason.")
            print("Empty, unmappable and data-less CSV files fail the run with a stated reason.")

            # ===============================================================================
            print("\n--- 6. IMPORT STATISTICS ---")
            # ===============================================================================

            # 6.1 Per-job counters reconcile.
            for job in (csv_job, batch_job, mock_run_1, seed_job):
                total = (job.new_leads + job.updated_leads
                         + job.duplicate_leads + job.failed_records)
                check(total == job.total_found,
                      f"Job {job.id}: {total} != total_found {job.total_found}")
            print("Per-job counters reconcile: found = new + updated + duplicates + failed.")

            # 6.2 Lifetime aggregate.
            stats = await service.get_statistics(db)
            for key_name in ("total_jobs", "total_found", "new_leads", "updated_leads",
                             "duplicate_leads", "failed_records", "jobs_by_status"):
                check(key_name in stats, f"Statistics missing '{key_name}'.")
            check(stats["total_jobs"] >= len(created_job_ids),
                  f"Expected >= {len(created_job_ids)} jobs, got {stats['total_jobs']}")
            check(stats["new_leads"] >= 1, "Lifetime new_leads should be positive.")
            check(sum(stats["jobs_by_status"].values()) == stats["total_jobs"],
                  "Per-status counts must sum to total_jobs.")
            print(f"Lifetime statistics: {stats['total_jobs']} jobs, {stats['total_found']} found, "
                  f"{stats['new_leads']} new, {stats['updated_leads']} updated, "
                  f"{stats['duplicate_leads']} duplicates, {stats['failed_records']} failed.")

            # ===============================================================================
            print("\n--- 7. JOB STATUS LIFECYCLE ---")
            # ===============================================================================

            # 7.1 A fully-successful run is COMPLETED with both timestamps set.
            check(seed_job.status == ImportJobStatus.COMPLETED, f"Got {seed_job.status}")
            check(seed_job.started_at is not None and seed_job.completed_at is not None,
                  "A finished job must carry both timestamps.")
            check(seed_job.completed_at >= seed_job.started_at,
                  "completed_at must not precede started_at.")
            check(seed_job.logs and len(seed_job.logs) >= 2,
                  "A job must log at least a start and a summary entry.")
            print("A clean run is COMPLETED, timestamped, and logged.")

            # 7.2 A run where everything failed is FAILED.
            all_fail_job = await service.run_import(
                db,
                provider_key="static_test",
                provider=StaticTestProvider([
                    {"business_name": "No Phone A"},
                    {"business_name": "No Phone B"},
                ]),
            )
            created_job_ids.append(all_fail_job.id)
            check(all_fail_job.status == ImportJobStatus.FAILED, f"Got {all_fail_job.status}")
            check(all_fail_job.failed_records == 2, f"Got {all_fail_job.failed_records}")
            check(all_fail_job.new_leads == 0, "A failed run must create nothing.")
            print("A run where every record failed is FAILED.")

            # 7.3 A source-level fault fails the run without inventing counters.
            explode_job = await service.run_import(
                db, provider_key="x", provider=ExplodingProvider()
            )
            created_job_ids.append(explode_job.id)
            check(explode_job.status == ImportJobStatus.FAILED, f"Got {explode_job.status}")
            check("unreachable" in (explode_job.error_message or "").lower(),
                  f"Got {explode_job.error_message}")
            check(explode_job.total_found == 0, "A source fault collects nothing.")
            print("An unreachable source fails the run and records the reason.")

            # 7.4 An empty result set is COMPLETED, not FAILED.
            empty_job = await service.run_import(
                db, provider_key="static_test", provider=StaticTestProvider([])
            )
            created_job_ids.append(empty_job.id)
            check(empty_job.status == ImportJobStatus.COMPLETED,
                  f"'No results' is a successful answer, got {empty_job.status}")
            print("A run that matched nothing is COMPLETED, not FAILED.")

            # 7.5 Read paths.
            fetched = await service.get_job_by_id(db, seed_job.id)
            check(fetched.id == seed_job.id, "get_job_by_id returned the wrong job.")
            try:
                await service.get_job_by_id(db, uuid.uuid4())
                raise AssertionError("An unknown job id should raise NotFound.")
            except NotFoundException:
                pass
            jobs, total = await service.get_all_jobs(db, limit=5)
            check(len(jobs) <= 5 and total >= len(created_job_ids), "Job listing/paging is wrong.")
            check(all(jobs[i].created_at >= jobs[i + 1].created_at for i in range(len(jobs) - 1)),
                  "Jobs must be listed newest-first.")
            _, csv_total = await service.get_all_jobs(db, provider="csv")
            check(csv_total >= 4, f"Provider filter returned {csv_total}.")
            _, failed_total = await service.get_all_jobs(db, status=ImportJobStatus.FAILED)
            check(failed_total >= 2, f"Status filter returned {failed_total}.")
            print("Job read paths work: fetch, 404, pagination, newest-first, provider/status filters.")

            # 7.6 Retry creates a NEW job linked to the original.
            check(all_fail_job.status in RETRYABLE_STATUSES, "Precondition: the job is retryable.")
            retry_job = await service.retry_job(
                db, all_fail_job.id, provider=StaticTestProvider([{
                    "business_name": f"Retry Fixed Studio {MARKER}",
                    "phone_numbers": [unique_phone(50)],
                    "city": "Kochi",
                }]),
            )
            created_job_ids.append(retry_job.id)
            check(retry_job.id != all_fail_job.id, "Retry must create a NEW job row.")
            check(retry_job.retry_of_job_id == all_fail_job.id,
                  "The retry must link back to the original.")
            check(retry_job.status == ImportJobStatus.COMPLETED, f"Got {retry_job.status}")
            check(retry_job.new_leads == 1, f"Got {retry_job.new_leads}")
            retry_lead = (await db.execute(
                select(Lead).where(Lead.business_name == f"Retry Fixed Studio {MARKER}")
            )).scalars().first()
            created_lead_ids.append(retry_lead.id)

            await db.refresh(all_fail_job)
            check(all_fail_job.status == ImportJobStatus.FAILED,
                  "The original job's record of failure must survive the retry.")
            print("Retry creates a NEW linked job and preserves the original's failure record.")

            # 7.7 Retrying is safe: the leads the first run imported are not re-created.
            safe_retry = await service.retry_job(
                db, all_fail_job.id, provider=StaticTestProvider([{
                    "business_name": f"Retry Fixed Studio {MARKER}",
                    "phone_numbers": [unique_phone(50)],
                    "city": "Kochi",
                }]),
            )
            created_job_ids.append(safe_retry.id)
            check(safe_retry.new_leads == 0,
                  f"A second retry must not duplicate leads, got {safe_retry.new_leads}")
            print("Retrying an already-partly-imported run creates no duplicates.")

            # 7.8 A COMPLETED job cannot be retried.
            try:
                await service.retry_job(db, seed_job.id)
                raise AssertionError("A COMPLETED job should not be retryable.")
            except ConflictException as e:
                check("cannot be retried" in str(e.detail), f"Got {e.detail}")
            print("A COMPLETED job is refused for retry.")

            # 7.9 A file-upload job cannot be retried (the bytes are not retained).
            try:
                await service.retry_job(db, csv_job.id)
                raise AssertionError("A CSV job should not be retryable.")
            except BadRequestException as e:
                check("re-upload" in str(e.detail).lower(), f"Got {e.detail}")
            print("A CSV upload job is refused for retry, directing the operator to re-upload.")

            # ===============================================================================
            print("\n--- 8. REQUEST SCHEMA & MODULE ISOLATION ---")
            # ===============================================================================

            # 8.1 The request schema normalizes and validates.
            parsed = ImportRunRequest(provider="  Google_Maps  ", query=" studios ", limit=50)
            check(parsed.provider == "google_maps", f"Got {parsed.provider}")
            check(parsed.query == "studios", f"Got {parsed.query}")
            blank = ImportRunRequest(provider="mock", query="   ")
            check(blank.query is None, "A whitespace-only query should become None.")
            print("The import request schema trims and lowercases input as expected.")

            # 8.2 The engine wrote only to `leads` and `import_jobs`.
            unrelated = Lead(
                business_name=f"Untouched Control Lead {MARKER}",
                phone=unique_phone(99),
                city="Bengaluru",
                source=LeadSource.MANUAL,
                status=LeadStatus.CONTACTED,
                contact_person="Do Not Touch",
            )
            db.add(unrelated)
            await db.commit()
            await db.refresh(unrelated)
            created_lead_ids.append(unrelated.id)
            control_version = unrelated.version

            isolation_job = await service.run_import(
                db, provider_key="mock", query=f"isolation probe {MARKER}", limit=3
            )
            created_job_ids.append(isolation_job.id)
            for row in (await db.execute(
                select(Lead).where(Lead.created_at >= isolation_job.started_at)
            )).scalars().all():
                if row.id not in created_lead_ids:
                    created_lead_ids.append(row.id)

            await db.refresh(unrelated)
            check(unrelated.version == control_version,
                  "An unrelated lead must be untouched by an import run.")
            check(unrelated.status == LeadStatus.CONTACTED,
                  "An unrelated lead's CRM status must be untouched.")
            check(unrelated.contact_person == "Do Not Touch", "An unrelated lead must not be edited.")
            print("An unrelated lead is untouched: no version bump, no status change.")

            # 8.3 Imported leads enter the pipeline correctly and get a timeline entry.
            check(retry_lead.status == LeadStatus.NEW, "Imported leads must start at NEW.")
            check(retry_lead.is_converted is False, "Imported leads must not be pre-converted.")
            activity_count = (await db.execute(
                select(LeadActivity).where(LeadActivity.lead_id == retry_lead.id)
            )).scalars().all()
            check(len(activity_count) >= 1, "An imported lead should get a CREATED timeline entry.")
            print("Imported leads start at status NEW and receive a timeline activity.")

            print(f"\n=== ALL LEAD COLLECTION ENGINE TESTS COMPLETED SUCCESSFULLY ===")
            print(f"Created {len(created_lead_ids)} leads and {len(created_job_ids)} import jobs.")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so we explicitly hard-delete everything
            # this suite created. Jobs go first (a retry job references another job), then
            # leads (which cascade away their activities).
            print("\nCleaning up test data...")
            await db.rollback()

            # Clear the self-referential retry links before deleting, so ordering within the
            # job set cannot trip the FK.
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

            # Sweep any lead this run created that was not individually tracked (the mock
            # provider's generated businesses), matched by the run marker and by the jobs'
            # window, then delete the tracked ones.
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
    asyncio.run(test_lead_import_suite())
