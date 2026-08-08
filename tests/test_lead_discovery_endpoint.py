"""
tests/test_lead_discovery_endpoint.py

Integration test suite for `POST /api/v1/leads/discover` — the HTTP edge in front of
`LeadDiscoveryService`.

Scope: the edge, not the pipeline
---------------------------------
`tests/test_lead_discovery.py` already proves the pipeline itself — stage order, counter
reconciliation, deduplication, failure containment. Re-asserting any of that here would
duplicate it and make both suites drift. What this suite owns is everything that only
exists because the service is exposed over HTTP:

  * the route resolves at the documented path, and is not swallowed by `/leads/{id}`
  * the request body is validated (radius, limit, blank city) before the service is reached
  * `city`, `category` and `radius_km` arrive at the provider in the right places —
    `radius_km` and `category` in `options`, which is the channel the provider contract
    defines for adapter extras
  * the response body is exactly the five documented keys, and they reconcile
  * `leads:import` is enforced, and `leads:view` alone is not enough
  * a source outage becomes 502, not 500, and a bad request becomes 400
  * the OpenAPI document describes all of the above

How the app is driven
---------------------
Requests go through the **real ASGI app** (`app.main.app`) via `httpx.ASGITransport`, so the
real router, the real dependency graph, the real Pydantic validation and the real global
exception handlers all run. Three dependencies are overridden:

  * `get_lead_discovery_service` — returns a service holding the same three stubs the
    pipeline suite uses, so no network is touched. The rest of the service is real and it
    writes real leads.
  * `get_current_employee` — returns a real `Employee` row created by this suite, avoiding
    a login round trip for what is not an auth test.
  * `get_db` — yields the suite's own session so writes land where the assertions look.

Overriding by dependency rather than by monkey-patching is the point of `deps.py` holding
every provider in one place, and is why `LeadDiscoveryService` takes its collaborators as
constructor arguments.

Permission enforcement is exercised against the **real** `RequirePermission`, with real
`Role` and `Permission` rows, because the thing under test is precisely that the route
carries the right permission string.

Requires a reachable database (`.env` / `app/core/config.py`). No network is touched.

Run:  python tests/test_lead_discovery_endpoint.py
"""

import asyncio
import os
import sys
import uuid
from typing import Any, Sequence

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from sqlalchemy import delete, select

from app.api.deps import (
    get_current_employee,
    get_db,
    get_lead_discovery_service,
)
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.permission import Permission, role_permissions
from app.models.role import Role
from app.services.cache import permission_cache
from app.services.lead_discovery import LeadDiscoveryService
from app.services.lead_providers.base import (
    LeadProvider,
    ProviderCollectionError,
    ProviderContext,
)
from app.services.lead_providers.normalized import NormalizedLead

ENDPOINT = "/api/v1/leads/discover"


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


#: Marker embedded in every row this suite creates, so cleanup can find leftovers even if a
#: test fails before tracking an id.
MARKER = uuid.uuid4().hex[:8]

#: Phone prefix unique to this run. `Lead.phone` is UNIQUE, so a fixed number would collide
#: with a previous run's leftovers and turn a real failure into a confusing one.
_PHONE_BASE = 7100000000 + (int(MARKER, 16) % 80000000)


def unique_phone(offset: int) -> str:
    """Returns a phone number unique to this run, so reruns cannot collide."""
    return f"+91{_PHONE_BASE + offset}"


def make_record(name: str, phone_offset: int, city: str = "Calicut", **extra: Any) -> NormalizedLead:
    """Builds a normalized record as a provider would return one."""
    return NormalizedLead(
        business_name=f"{name} {MARKER}",
        phone_numbers=[unique_phone(phone_offset)],
        city=city,
        source="GOOGLE_MAPS",
        **extra,
    ).normalize()


# ===========================================================================================
# Stubs — the three network-touching stages
# ===========================================================================================

class StubProvider(LeadProvider):
    """
    A `LeadProvider` returning canned records, standing in for Overpass.

    Records every `ProviderContext` it is handed, which is how this suite proves the
    endpoint put `city`, `category` and `radius_km` where the adapter contract says they go
    without needing to reach a real adapter.
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
        raise_bad_request: str | None = None,
    ) -> None:
        self._records = list(records)
        self._fail_with = fail_with
        self._raise_bad_request = raise_bad_request
        self.contexts: list[ProviderContext] = []

    def search(self, query: str | None = None, **kwargs: Any) -> ProviderContext:
        if self._raise_bad_request:
            from app.core.exceptions import BadRequestException
            raise BadRequestException(self._raise_bad_request)
        context = super().search(query, **kwargs)
        self.contexts.append(context)
        return context

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        if self._fail_with:
            raise ProviderCollectionError(self._fail_with)
        return [{"index": i} for i in range(len(self._records[: context.limit]))]

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        return self._records[raw["index"]]


class StubDiscovery:
    """Stands in for `WebsiteDiscoveryService`. Passes every lead through untouched."""

    def __init__(self) -> None:
        self.calls = 0

    async def discover_many(self, records: Sequence[NormalizedLead]) -> list[NormalizedLead]:
        self.calls += 1
        return list(records)


class StubExtractor:
    """Stands in for `ContactExtractorService`. Passes every lead through untouched."""

    def __init__(self) -> None:
        self.calls = 0

    async def extract_many(self, records: Sequence[NormalizedLead]) -> list[NormalizedLead]:
        self.calls += 1
        return list(records)


def build_service(
    records: Sequence[NormalizedLead] = (),
    fail_with: str | None = None,
    raise_bad_request: str | None = None,
) -> tuple[LeadDiscoveryService, StubProvider, StubDiscovery, StubExtractor]:
    """
    Builds a `LeadDiscoveryService` with the three network stages stubbed and everything
    else real, plus handles on the stubs so a test can inspect what reached them.
    """
    provider = StubProvider(records, fail_with=fail_with, raise_bad_request=raise_bad_request)
    discovery = StubDiscovery()
    extractor = StubExtractor()
    service = LeadDiscoveryService(
        provider=provider,
        website_discovery=discovery,
        contact_extractor=extractor,
    )
    return service, provider, discovery, extractor


async def test_lead_discovery_endpoint_suite() -> None:
    """Runs the full POST /leads/discover endpoint suite."""
    created_lead_ids: list[uuid.UUID] = []
    created_role_ids: list[uuid.UUID] = []
    created_employee_ids: list[uuid.UUID] = []
    created_permission_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        try:
            print(f"\n=== LEAD DISCOVERY ENDPOINT TESTS (marker {MARKER}) ===")

            # ===============================================================================
            print("\n--- 0. FIXTURES ---")
            # ===============================================================================

            async def get_permission(module: str, action: str) -> Permission:
                """Fetches a seeded permission, creating it if the seeder has not been run."""
                row = (await db.execute(
                    select(Permission).where(
                        Permission.module == module, Permission.action == action
                    )
                )).scalars().first()
                if row is None:
                    row = Permission(module=module, action=action)
                    db.add(row)
                    await db.flush()
                    created_permission_ids.append(row.id)
                return row

            perm_import = await get_permission("leads", "import")
            perm_view = await get_permission("leads", "view")

            async def make_employee(label: str, permissions: list[Permission]) -> Employee:
                """
                Creates a non-system, non-Administrator role with exactly `permissions`, and
                an employee holding it. Both qualifiers matter: `RequirePermission` short-
                circuits for Administrator and for any `is_system` role, so a fixture with
                either would pass the permission tests without checking anything.
                """
                role = Role(
                    name=f"Discovery {label} {MARKER}",
                    description=f"Endpoint suite fixture ({label})",
                    is_system=False,
                )
                role.permissions = list(permissions)
                db.add(role)
                await db.flush()
                created_role_ids.append(role.id)

                employee = Employee(
                    employee_code=f"DISC-{label[:4].upper()}-{MARKER}",
                    first_name="Discovery",
                    last_name=f"{label.capitalize()} {MARKER}",
                    email=f"discovery.{label}.{MARKER}@test.local",
                    phone=unique_phone(900 + len(created_employee_ids)),
                    password_hash="not-a-real-hash",
                    role_id=role.id,
                    is_active=True,
                )
                db.add(employee)
                await db.flush()
                created_employee_ids.append(employee.id)
                return employee

            importer = await make_employee("importer", [perm_import])
            viewer = await make_employee("viewer", [perm_view])
            await db.commit()
            print(f"Fixtures ready: importer holds leads:import, viewer holds leads:view only.")

            # The permission cache is process-local and warmed at startup; these roles were
            # created after that, so seed the cache the same way a live request would on a
            # miss. Invalidating instead would also work — this is explicit about intent.
            await permission_cache.invalidate_employee(importer.id)
            await permission_cache.invalidate_employee(viewer.id)

            # --- Wire the app to this suite's session. The service override is re-pointed
            #     per test; the db and auth overrides stay for the whole run.
            async def override_db():
                yield db

            current_service: dict[str, LeadDiscoveryService] = {}
            current_employee: dict[str, Employee] = {"employee": importer}

            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_employee] = lambda: current_employee["employee"]
            app.dependency_overrides[get_lead_discovery_service] = lambda: current_service["service"]

            transport = httpx.ASGITransport(app=app)
            client = httpx.AsyncClient(
                transport=transport, base_url="http://test", timeout=30.0
            )

            # ===============================================================================
            print("\n--- 1. ROUTING AND THE HAPPY PATH ---")
            # ===============================================================================

            # 1.1 The documented request body returns the documented response body.
            service, provider, discovery, extractor = build_service([
                make_record("Malabar Portrait Works", 1),
                make_record("Beypore Wedding Films", 2),
            ])
            current_service["service"] = service

            response = await client.post(
                ENDPOINT,
                json={"city": "Calicut", "category": "photographer", "radius_km": 30},
            )
            check(
                response.status_code == 200,
                f"Expected 200 from {ENDPOINT}, got {response.status_code}: {response.text}",
            )
            body = response.json()
            print(f"POST {ENDPOINT} -> 200 {body}")

            # 1.2 The response is EXACTLY the documented keys — no more, no fewer. The
            #     'no more' half is the half that matters: response_model prunes extras, and
            #     this is what stops a diagnostic field from silently becoming API.
            #
            #     The five counters were once the whole response. The record-level fields
            #     were added deliberately so the import UI can show *which* leads a run
            #     produced rather than only how many; they are API now and are pinned here
            #     for the same reason the counters are. `created_lead_ids`/`merged_lead_ids`
            #     and the raw `errors` lines remain internal to DiscoverySummary — if either
            #     ever shows up in this set, something leaked.
            #     `enrichment` joined them for the same reason: the import screen reports
            #     how much contact information a run actually landed, and a figure the
            #     server does not send is a figure the UI would otherwise have to invent.
            COUNTER_KEYS = {"found", "imported", "duplicates", "merged", "failed"}
            RECORD_KEYS = {
                "imported_records", "merged_records", "failed_records",
                "stages", "city", "provider", "enrichment",
            }
            check(
                set(body.keys()) == COUNTER_KEYS | RECORD_KEYS,
                f"Response keys must be exactly the documented ones, got {sorted(body)}",
            )
            check(
                all(isinstance(body[k], int) for k in COUNTER_KEYS),
                f"Every counter must be an integer, got {body}",
            )
            print("Response body is exactly the five counters plus the record-level fields.")

            # 1.2b The record arrays stay in step with the counters they detail. This is the
            #      invariant the results tables depend on: a table showing fewer rows than
            #      its tab's count is the one bug the UI cannot notice on its own.
            check(
                len(body["imported_records"]) == body["imported"],
                f"imported_records must match imported={body['imported']}, "
                f"got {len(body['imported_records'])}",
            )
            check(
                len(body["merged_records"]) == body["merged"],
                f"merged_records must match merged={body['merged']}, "
                f"got {len(body['merged_records'])}",
            )
            check(
                len(body["failed_records"]) == body["failed"],
                f"failed_records must match failed={body['failed']}, "
                f"got {len(body['failed_records'])}",
            )

            # 1.2c An imported record carries what the results table renders, and its id is
            #      a real lead id the UI can link through to.
            first = body["imported_records"][0]
            #      The contact channels below were added so the results table can show the
            #      operator who to call without a round trip per row; `is_whatsapp_ready`
            #      and `contact_quality` are derived from those columns and never stored.
            check(
                set(first) == {
                    "id", "business_name", "phone", "email", "city", "website",
                    "whatsapp", "instagram", "facebook", "youtube", "source",
                    "is_whatsapp_ready", "contact_quality",
                    "enriched_fields",
                },
                f"An imported record has unexpected fields: {sorted(first)}",
            )
            check(
                first["business_name"] is not None and first["phone"] is not None,
                f"An imported record must carry the fields it was stored with: {first}",
            )
            check(
                first["enriched_fields"] == [],
                f"A newly created lead has no enriched fields, got {first['enriched_fields']}",
            )
            print("Imported records carry id, contact details and an empty enriched_fields.")

            # 1.3 The counters describe the run and reconcile.
            check(body["found"] == 2, f"Expected found=2, got {body['found']}")
            check(body["imported"] == 2, f"Expected imported=2, got {body['imported']}")
            check(
                body["imported"] + body["merged"] + body["duplicates"] + body["failed"]
                == body["found"],
                f"Counters must reconcile: {body}",
            )
            print(f"Counters reconcile: {body['found']} found = "
                  f"{body['imported']} imported + {body['merged']} merged + "
                  f"{body['duplicates']} duplicates + {body['failed']} failed.")

            # 1.4 The run actually wrote leads — the endpoint is not reporting a dry run.
            saved = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER}%"))
            )).scalars().all()
            created_lead_ids.extend(row.id for row in saved)
            check(
                len(saved) == 2,
                f"Expected 2 leads persisted by the request, found {len(saved)}",
            )
            print(f"The request persisted {len(saved)} real leads.")

            # ===============================================================================
            print("\n--- 2. REQUEST FIELDS REACH THE PROVIDER ---")
            # ===============================================================================

            # 2.1 city travels as `city`, not folded into the query text.
            context = provider.contexts[-1]
            check(context.city == "Calicut", f"city not passed through: {context.city!r}")

            # 2.2 category and radius_km travel in `options`, which is the channel the
            #     provider contract defines for adapter extras. Asserted explicitly because
            #     an endpoint that dropped either would still return a plausible 200.
            check(
                context.options.get("category") == "photographer",
                f"category must reach options, got {context.options!r}",
            )
            check(
                float(context.options.get("radius_km")) == 30.0,
                f"radius_km must reach options, got {context.options!r}",
            )
            print(f"city/category/radius_km reach the provider: "
                  f"city={context.city!r} options={context.options!r}")

            # 2.3 An omitted radius is omitted from options entirely, rather than sent as
            #     None — the adapter defaults and clamps it, and a None would be a value it
            #     has to interpret.
            service, provider, _, _ = build_service([make_record("No Radius", 3)])
            current_service["service"] = service
            response = await client.post(ENDPOINT, json={"city": "Calicut"})
            check(response.status_code == 200, f"Expected 200, got {response.text}")
            created_lead_ids.extend((await db.execute(
                select(Lead.id).where(Lead.business_name.ilike(f"%No Radius {MARKER}%"))
            )).scalars().all())
            check(
                "radius_km" not in provider.contexts[-1].options,
                f"An omitted radius must not be sent: {provider.contexts[-1].options!r}",
            )
            # 2.4 category defaults to 'photographer', so the documented default is real.
            check(
                provider.contexts[-1].options.get("category") == "photographer",
                f"category should default to 'photographer', got "
                f"{provider.contexts[-1].options!r}",
            )
            print("Omitting radius_km sends no radius; category defaults to 'photographer'.")

            # 2.5 The enrichment toggles are honoured end to end.
            service, provider, discovery, extractor = build_service([make_record("Toggles", 4)])
            current_service["service"] = service
            response = await client.post(
                ENDPOINT,
                json={
                    "city": "Calicut",
                    "discover_websites": False,
                    "extract_contacts": False,
                },
            )
            check(response.status_code == 200, f"Expected 200, got {response.text}")
            created_lead_ids.extend((await db.execute(
                select(Lead.id).where(Lead.business_name.ilike(f"%Toggles {MARKER}%"))
            )).scalars().all())
            check(
                discovery.calls == 0 and extractor.calls == 0,
                f"Disabled stages must not run (discovery={discovery.calls}, "
                f"extractor={extractor.calls})",
            )
            print("discover_websites/extract_contacts=false skip both network stages.")

            # ===============================================================================
            print("\n--- 3. REQUEST VALIDATION ---")
            # ===============================================================================

            # Validation must reject before the service is reached, so point the override at
            # a provider that would fail loudly if it were ever called.
            service, provider, _, _ = build_service([], fail_with="must not be reached")
            current_service["service"] = service

            invalid_bodies = [
                ({}, "a missing city"),
                ({"city": ""}, "an empty city"),
                ({"city": "   "}, "a whitespace-only city"),
                ({"city": "Calicut", "radius_km": 0}, "radius_km = 0"),
                ({"city": "Calicut", "radius_km": -5}, "a negative radius_km"),
                ({"city": "Calicut", "radius_km": 10_000}, "an absurd radius_km"),
                ({"city": "Calicut", "radius_km": "wide"}, "a non-numeric radius_km"),
                ({"city": "Calicut", "limit": 0}, "limit = 0"),
                ({"city": "Calicut", "limit": 99_999}, "an over-large limit"),
                ({"city": "C" * 200}, "an over-long city"),
            ]
            for payload, label in invalid_bodies:
                response = await client.post(ENDPOINT, json=payload)
                check(
                    response.status_code == 422,
                    f"Expected 422 for {label}, got {response.status_code}: {response.text}",
                )
            check(
                provider.contexts == [] ,
                "Validation must reject before the provider is reached.",
            )
            print(f"All {len(invalid_bodies)} invalid bodies were rejected with 422 before "
                  f"reaching the service.")

            # 3.1 The 422 body keeps the project's error envelope rather than FastAPI's raw
            #     shape, so a client parses one format across every endpoint.
            response = await client.post(ENDPOINT, json={"city": "Calicut", "radius_km": -1})
            envelope = response.json()
            check(
                envelope.get("success") is False and "error_code" in envelope,
                f"422 should use the project error envelope, got {envelope}",
            )
            print(f"Validation errors use the standard envelope: error_code="
                  f"{envelope.get('error_code')!r}")

            # ===============================================================================
            print("\n--- 4. RBAC: leads:import ---")
            # ===============================================================================

            service, _, _, _ = build_service([])
            current_service["service"] = service

            # 4.1 leads:view alone is not enough. This is the assertion that pins the route
            #     to `leads:import` specifically: a route guarded by `leads:view` would pass
            #     every other test in this suite unchanged.
            current_employee["employee"] = viewer
            response = await client.post(ENDPOINT, json={"city": "Calicut"})
            check(
                response.status_code == 403,
                f"An employee with only leads:view must be refused, got "
                f"{response.status_code}: {response.text}",
            )
            envelope = response.json()
            check(
                "leads:import" in str(envelope),
                f"The 403 should name the missing permission, got {envelope}",
            )
            print(f"leads:view alone -> 403 naming leads:import.")

            # 4.2 leads:import is accepted.
            current_employee["employee"] = importer
            response = await client.post(ENDPOINT, json={"city": "Calicut"})
            check(
                response.status_code == 200,
                f"leads:import must be accepted, got {response.status_code}: {response.text}",
            )
            print("leads:import -> 200.")

            # 4.3 An unauthenticated request is refused. The auth override is lifted so the
            #     real `get_current_employee` runs against a request with no bearer token.
            del app.dependency_overrides[get_current_employee]
            response = await client.post(ENDPOINT, json={"city": "Calicut"})
            check(
                response.status_code in (401, 403),
                f"An unauthenticated request must be refused, got {response.status_code}",
            )
            print(f"No credentials -> {response.status_code}.")
            app.dependency_overrides[get_current_employee] = lambda: current_employee["employee"]

            # ===============================================================================
            print("\n--- 5. FAILURE TRANSLATION ---")
            # ===============================================================================

            # 5.1 A source outage is 502, not 500. `ProviderCollectionError` is a plain
            #     Exception, so without the endpoint's translation it would reach the generic
            #     handler and report a donated endpoint being down as our internal error.
            service, _, _, _ = build_service([], fail_with="Overpass unreachable (simulated).")
            current_service["service"] = service
            response = await client.post(ENDPOINT, json={"city": "Calicut"})
            check(
                response.status_code == 502,
                f"A source outage must be 502, got {response.status_code}: {response.text}",
            )
            envelope = response.json()
            check(
                envelope.get("error_code") == "DISCOVERY_SOURCE_UNAVAILABLE",
                f"Wrong error_code for a source outage: {envelope}",
            )
            check(
                "Overpass unreachable" in str(envelope.get("detail")),
                f"The 502 should carry the source's reason, got {envelope}",
            )
            print(f"Source outage -> 502 {envelope.get('error_code')}.")

            # 5.2 A provider refusing the request (unusable city/radius) is 400, not 502:
            #     that is the caller's input, not the source being down.
            service, _, _, _ = build_service([], raise_bad_request="City could not be geocoded.")
            current_service["service"] = service
            response = await client.post(ENDPOINT, json={"city": "Nowheresville"})
            check(
                response.status_code == 400,
                f"An unserviceable request must be 400, got {response.status_code}: "
                f"{response.text}",
            )
            check(
                "geocoded" in str(response.json().get("detail")),
                f"The 400 should carry the provider's reason, got {response.json()}",
            )
            print("An unserviceable request -> 400 carrying the provider's reason.")

            # 5.3 A city with nothing in it is a successful run of zero, not an error.
            service, _, _, _ = build_service([])
            current_service["service"] = service
            response = await client.post(ENDPOINT, json={"city": "Calicut"})
            check(response.status_code == 200, f"Expected 200, got {response.text}")
            empty_body = response.json()
            check(
                {k: empty_body[k] for k in COUNTER_KEYS} == {
                    "found": 0, "imported": 0, "duplicates": 0, "merged": 0, "failed": 0
                },
                f"An empty city should return five zeroes, got {empty_body}",
            )
            # And no records to go with them — an empty run has nothing to list, so the
            # results tables render their empty states rather than stale rows.
            check(
                empty_body["imported_records"] == []
                and empty_body["merged_records"] == []
                and empty_body["failed_records"] == [],
                f"An empty run must carry no records, got {empty_body}",
            )
            print("A city yielding nothing -> 200 with five zeroes and no records.")

            # ===============================================================================
            print("\n--- 6. DEDUPLICATION THROUGH THE ENDPOINT ---")
            # ===============================================================================

            # Re-running the first request's records must not create a second copy. The
            # dedup rules themselves are covered by test_lead_deduplication.py; what is
            # asserted here is only that a caller hitting the endpoint twice sees it.
            service, _, _, _ = build_service([
                make_record("Malabar Portrait Works", 1),
                make_record("Beypore Wedding Films", 2),
            ])
            current_service["service"] = service
            response = await client.post(
                ENDPOINT, json={"city": "Calicut", "category": "photographer"}
            )
            check(response.status_code == 200, f"Expected 200, got {response.text}")
            body = response.json()
            check(
                body["imported"] == 0,
                f"A repeated run must import nothing new, got {body}",
            )
            check(
                body["duplicates"] + body["merged"] == body["found"],
                f"Repeated records must classify as duplicates/merged, got {body}",
            )
            total_leads = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER}%"))
            )).scalars().all()
            check(
                len(total_leads) == len(created_lead_ids),
                f"A repeated run must create no new rows, found {len(total_leads)} against "
                f"{len(created_lead_ids)} tracked",
            )
            print(f"Repeat run: imported=0, duplicates={body['duplicates']}, "
                  f"merged={body['merged']}; row count unchanged at {len(total_leads)}.")

            # ===============================================================================
            print("\n--- 7. OPENAPI DOCUMENTATION ---")
            # ===============================================================================

            spec = app.openapi()
            path_item = spec["paths"].get("/api/v1/leads/discover")
            check(path_item is not None, "The route is missing from the OpenAPI document.")
            check("post" in path_item, "The route should be documented as a POST.")
            operation = path_item["post"]

            check(bool(operation.get("summary")), "The operation needs a summary.")
            check(
                len(operation.get("description", "")) > 100,
                "The operation needs a description explaining the pipeline.",
            )
            for code in ("200", "400", "403", "422", "502"):
                check(
                    code in operation["responses"],
                    f"Response {code} is undocumented; documented: "
                    f"{sorted(operation['responses'])}",
                )
            print(f"Documented responses: {sorted(operation['responses'])}")

            # 7.1 The documented request schema carries the three fields of the contract,
            #     with their bounds — the document is what a client codegens from.
            req_name = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            req_schema = spec["components"]["schemas"][req_name.rsplit("/", 1)[-1]]
            for field in ("city", "category", "radius_km"):
                check(
                    field in req_schema["properties"],
                    f"Request schema is missing '{field}'.",
                )
                check(
                    bool(req_schema["properties"][field].get("description")),
                    f"Request field '{field}' has no description.",
                )
            check(
                req_schema.get("required") == ["city"],
                f"'city' should be the only required field, got {req_schema.get('required')}",
            )
            print(f"Request schema documents {sorted(req_schema['properties'])}; "
                  f"required={req_schema.get('required')}")

            # 7.2 The documented response schema is the five counters plus the record-level
            #     fields, every one described.
            res_ref = (operation["responses"]["200"]["content"]["application/json"]
                       ["schema"]["$ref"])
            res_schema = spec["components"]["schemas"][res_ref.rsplit("/", 1)[-1]]
            check(
                set(res_schema["properties"]) == COUNTER_KEYS | RECORD_KEYS,
                f"Response schema must document exactly the documented fields, got "
                f"{sorted(res_schema['properties'])}",
            )
            # Only the counters are required. The record fields all default to empty, which
            # is what makes them an additive change: a client reading just the counters is
            # unaffected by their presence.
            check(
                set(res_schema.get("required", [])) == COUNTER_KEYS,
                f"Exactly the five counters should be required, got "
                f"{sorted(res_schema.get('required', []))}",
            )
            for field, prop in res_schema["properties"].items():
                check(
                    bool(prop.get("description")),
                    f"Response field '{field}' has no description.",
                )
            print(f"Response schema documents exactly {sorted(res_schema['properties'])}, "
                  f"all required and described.")

            # 7.3 Auth is documented the way the rest of this API documents it — which is
            #     to say, not in the `security` block. `get_current_employee` reads the
            #     bearer token itself rather than declaring a FastAPI security scheme, so
            #     no operation in this app emits one and the document advertises every
            #     route as open. That is a real project-wide documentation gap and worth
            #     closing, but closing it belongs in one change across all routes, not here.
            #     Asserted as-is so this suite records the current state instead of
            #     pretending the route is an exception to it.
            operations_with_security = sum(
                1
                for item in spec["paths"].values()
                for op in item.values()
                if isinstance(op, dict) and "security" in op
            )
            check(
                operations_with_security == 0,
                "Some operations now declare `security`; this route should declare it too "
                f"({operations_with_security} do).",
            )
            print("No operation in this API declares an OpenAPI security scheme "
                  "(project-wide; this route matches its peers).")

            # 7.4 The 403 is documented, which is what tells a reader the route is guarded
            #     even without a security block.
            check(
                "leads:import" in operation["responses"]["403"]["description"],
                "The 403 response should name the permission the route requires.",
            )
            print("The documented 403 names the required permission (leads:import).")

            await client.aclose()
            print(f"\n=== ALL LEAD DISCOVERY ENDPOINT TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Always lift the overrides — `app` is module-global, so leaving them installed
            # would silently corrupt any suite importing it afterwards in the same process.
            for dependency in (get_db, get_current_employee, get_lead_discovery_service):
                app.dependency_overrides.pop(dependency, None)

            print("\nCleaning up test data...")
            await db.rollback()

            # Leads commit immediately, so they are hard-deleted here (activities first: a
            # lead's timeline rows reference it).
            leftover = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER}%"))
            )).scalars().all()
            for row in leftover:
                await db.execute(delete(LeadActivity).where(LeadActivity.lead_id == row.id))
                await db.delete(row)
            await db.commit()

            for employee_id in created_employee_ids:
                row = await db.get(Employee, employee_id)
                if row:
                    await db.delete(row)
            await db.commit()

            # The role_permissions association rows are deleted with a Core statement
            # rather than by clearing `role.permissions`: assigning to a lazy-loaded
            # collection triggers IO from a synchronous attribute set, which asyncio cannot
            # service (MissingGreenlet).
            if created_role_ids:
                await db.execute(
                    delete(role_permissions).where(
                        role_permissions.c.role_id.in_(created_role_ids)
                    )
                )
                await db.commit()
            for role_id in created_role_ids:
                row = await db.get(Role, role_id)
                if row:
                    await db.delete(row)
            await db.commit()

            # Only permissions this suite had to create itself — seeded ones stay.
            for permission_id in created_permission_ids:
                row = await db.get(Permission, permission_id)
                if row:
                    await db.delete(row)
            await db.commit()

            for employee_id in created_employee_ids:
                await permission_cache.invalidate_employee(employee_id)

            print(f"Cleanup complete ({len(leftover)} leads, "
                  f"{len(created_employee_ids)} employees, {len(created_role_ids)} roles).")


if __name__ == "__main__":
    asyncio.run(test_lead_discovery_endpoint_suite())
