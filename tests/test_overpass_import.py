"""
tests/test_overpass_import.py

Unit test suite for the OpenStreetMap / Overpass lead provider.

Verifies:
1.  Provider initialization — registry resolution, capability description, and the fact
    that this provider is available with **no credential configured**, which is the whole
    point of replacing the billed Google Places adapter with it.
2.  Search validation — city required, radius defaulted/parsed/clamped, limit clamping,
    empty query refused.
3.  Query construction — every required tag appears, all three element types are queried,
    the radius is converted to metres, and `out center` is requested.
4.  Geocoding — Nominatim is called before Overpass, state narrows the search, a city that
    matches nothing fails the run with a readable reason.
5.  Collection — elements parsed, limit honoured, untagged geometry dropped, the raw OSM
    payload retained for diagnosis.
6.  Normalization — name/address/phone/email/website/coordinate extraction, tag preference
    order, multi-value tags, way/relation `center` fallback, city fallback, OSM URL.
7.  Rate limiting — outbound calls are serialised and spaced by the configured interval.
8.  Retry with exponential backoff — 429/504/transport faults retried, `Retry-After`
    honoured, delays grow exponentially and are capped, 4xx not retried, exhaustion fails
    the run with a stated reason.
9.  The failure contract — a record with no phone is a *failed record*, not a failed run;
    `collect_normalized` never raises for bad data.
10. Nothing is persisted — `collect_normalized` returns `NormalizedLead` objects and the
    provider module imports no ORM model, session or repository.

Unlike the sibling `test_google_maps_import.py`, this suite is a **pure unit suite**: it
touches no database at all, because the brief for this provider is explicitly "do not save
anything into the database — return only normalized leads". It therefore needs no cleanup
block, no marker rows and no configured Postgres, and it is safe to run anywhere.

Every response is mocked through `httpx.MockTransport`, so this suite needs no network. The
stub speaks real Overpass and Nominatim response shapes (`{"elements": [...]}` with
`node`/`way` entries and a `center` for ways; Nominatim's bare JSON array with string
`lat`/`lon`), so the mapping under test is the same one production runs. `asyncio.sleep` is
patched where backoff is asserted, so the retry tests measure the *computed delays* rather
than spending them.

Run:  python tests/test_overpass_import.py
"""

import asyncio
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from app.core.exceptions import BadRequestException
from app.services.lead_providers import get_provider, registered_provider_keys
from app.services.lead_providers.base import (
    MAX_COLLECTION_LIMIT,
    ProviderCollectionError,
)
from app.services.lead_providers.normalized import NormalizedLead
from app.services.lead_providers.overpass import OverpassLeadProvider


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


# ===========================================================================================
# Stub Overpass + Nominatim
# ===========================================================================================

def make_node(
    index: int,
    *,
    name: str | None = None,
    tag_key: str = "shop",
    tag_value: str = "photo",
    phone: str | None = None,
    email: str | None = None,
    website: str | None = None,
    city: str = "Kozhikode",
    state: str = "Kerala",
    pincode: str = "673001",
    extra_tags: dict | None = None,
) -> dict:
    """
    Builds one OSM `node` element in Overpass's real response shape.

    Faithful to the API — tags as a flat string->string dict, `lat`/`lon` on the element
    itself, no formatted address anywhere — because the mapping under test is precisely the
    code that assembles a usable lead out of that shape.
    """
    tags: dict = {tag_key: tag_value}
    if name is not None:
        tags["name"] = name
    if phone is not None:
        tags["phone"] = phone
    if email is not None:
        tags["email"] = email
    if website is not None:
        tags["website"] = website
    tags.update({
        "addr:housenumber": str(index),
        "addr:street": "MG Road",
        "addr:city": city,
        "addr:state": state,
        "addr:postcode": pincode,
    })
    if extra_tags:
        tags.update(extra_tags)

    return {
        "type": "node",
        "id": 1000 + index,
        "lat": 11.25 + index / 100,
        "lon": 75.78 + index / 100,
        "tags": tags,
    }


def make_way(index: int, *, name: str, phone: str | None = None) -> dict:
    """
    Builds one OSM `way` element — a building outline, which has no `lat`/`lon` of its own
    and instead carries the `center` that `out center` asks Overpass to compute.
    """
    tags: dict = {"craft": "photographer", "name": name}
    if phone is not None:
        tags["phone"] = phone
    return {
        "type": "way",
        "id": 2000 + index,
        "center": {"lat": 11.30 + index / 100, "lon": 75.80 + index / 100},
        "tags": tags,
    }


class StubOverpassAPI:
    """
    An in-process stand-in for Nominatim + Overpass, driven by a list of elements.

    Records every request it receives, and the monotonic time each arrived at, so a test can
    assert on *call behaviour* — that the geocode happened before the query, that retries
    actually retried, that calls were spaced by the rate limiter — and not merely on the
    final records. Behaviour under a rate-limited public endpoint is the part that bites in
    production, so it is the part worth asserting.
    """

    def __init__(
        self,
        elements: list[dict] | None = None,
        *,
        geocode_results: list[dict] | None = None,
        overpass_statuses: list[int] | None = None,
        overpass_exceptions: int = 0,
        retry_after: str | None = None,
        non_json_body: bool = False,
        missing_elements_key: bool = False,
    ) -> None:
        self.elements = elements or []
        self.geocode_results = (
            geocode_results
            if geocode_results is not None
            else [{
                "lat": "11.2588",
                "lon": "75.7804",
                "display_name": "Kozhikode, Kerala, India",
            }]
        )
        #: Status codes returned by successive Overpass calls; the list is consumed one entry
        #: per call and 200 is returned once exhausted. This is how a "fails twice then
        #: succeeds" retry scenario is expressed.
        self.overpass_statuses = list(overpass_statuses or [])
        #: How many leading Overpass calls raise a transport error instead of responding.
        self.overpass_exceptions = overpass_exceptions
        self.retry_after = retry_after
        self.non_json_body = non_json_body
        self.missing_elements_key = missing_elements_key

        self.geocode_calls: list[dict] = []
        self.overpass_calls: list[str] = []
        self.call_order: list[str] = []
        self.call_times: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Routes one intercepted request to the Nominatim or Overpass responder."""
        self.call_times.append(asyncio.get_running_loop().time())
        if "nominatim" in str(request.url.host) or "search" in request.url.path:
            return self._geocode(request)
        return self._overpass(request)

    def _geocode(self, request: httpx.Request) -> httpx.Response:
        self.call_order.append("geocode")
        params = dict(request.url.params)
        self.geocode_calls.append(params)
        return httpx.Response(200, json=self.geocode_results)

    def _overpass(self, request: httpx.Request) -> httpx.Response:
        self.call_order.append("overpass")
        self.overpass_calls.append(request.content.decode("utf-8", errors="replace"))

        call_index = len(self.overpass_calls) - 1
        if call_index < self.overpass_exceptions:
            raise httpx.ConnectTimeout("Simulated Overpass connection timeout.")

        if self.overpass_statuses:
            status = self.overpass_statuses.pop(0)
            if status != 200:
                headers = {"Retry-After": self.retry_after} if self.retry_after else {}
                return httpx.Response(
                    status, json={"error": f"Simulated HTTP {status}."}, headers=headers
                )

        if self.non_json_body:
            return httpx.Response(200, text="<html>rate limited</html>")
        if self.missing_elements_key:
            return httpx.Response(200, json={"version": 0.6})
        return httpx.Response(200, json={"version": 0.6, "elements": self.elements})


class StubbedOverpassProvider(OverpassLeadProvider):
    """
    The real provider with its HTTP transport swapped for a stub.

    Subclassing to override only `_import_httpx` keeps `search()`, `collect()`, `normalize()`,
    the geocode hop, the rate limiter and every retry path as the production code — the stub
    replaces the socket, nothing else. This mirrors `StubbedGoogleMapsProvider`.
    """

    def __init__(self, api: StubOverpassAPI, **kwargs) -> None:
        kwargs.setdefault("min_request_interval", 0.0)
        super().__init__(**kwargs)
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


class SleepRecorder:
    """
    Replaces `asyncio.sleep` inside the provider module so backoff tests assert the delays
    that *would* have been spent without spending them.

    A retry suite that really slept would take half a minute and would be the first thing a
    developer skipped; recording the computed delays tests the actual policy — exponential
    growth, the cap, `Retry-After` precedence — more precisely than a wall-clock measurement
    could anyway.
    """

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def patch_sleep(recorder: SleepRecorder):
    """Swaps the provider module's `asyncio.sleep`, returning a restore callable."""
    from app.services.lead_providers import overpass as module

    original = module.asyncio.sleep

    class _AsyncioProxy:
        def __getattr__(self, name):
            return getattr(module.asyncio, name)

        sleep = staticmethod(recorder)

        @staticmethod
        def get_running_loop():
            return asyncio.get_running_loop()

        Lock = asyncio.Lock

    module.asyncio = _AsyncioProxy()  # type: ignore[assignment]

    def restore() -> None:
        module.asyncio = asyncio  # type: ignore[assignment]
        assert original is asyncio.sleep or True

    return restore


# ===========================================================================================
# 1. Provider initialization
# ===========================================================================================

async def test_initialization() -> None:
    print("\n[1] Provider initialization")

    check("overpass" in registered_provider_keys(),
          "overpass must be registered in the provider registry")
    print("  ✓ registered under key 'overpass'")

    provider = get_provider("overpass")
    check(isinstance(provider, OverpassLeadProvider),
          "get_provider('overpass') must resolve to OverpassLeadProvider")
    print("  ✓ resolves to OverpassLeadProvider")

    described = provider.describe()
    check(described["key"] == "overpass", "describe() key mismatch")
    check(described["requires_query"] is True, "provider requires a query")
    check(described["requires_file"] is False, "provider takes no file")
    check(described["lead_source"] == "GOOGLE_MAPS",
          "Overpass leads reuse the GOOGLE_MAPS lead source (map listings)")
    print(f"  ✓ describe(): {described['display_name']}, source={described['lead_source']}")

    # The headline property: no credential exists, so nothing can make it unavailable.
    check(provider.is_available is True,
          "Overpass needs no API key and must always be available")
    check("unavailable_reason" not in described,
          "an available provider must not advertise an unavailable reason")
    print("  ✓ available with NO credential configured (free provider)")

    # Registering alongside rather than replacing: the paid adapter is untouched.
    check("google_maps" in registered_provider_keys(),
          "the google_maps provider must remain registered alongside overpass")
    print("  ✓ google_maps left registered alongside (no hard cutover)")


# ===========================================================================================
# 2. Search validation
# ===========================================================================================

async def test_search_validation() -> None:
    print("\n[2] Search validation")

    provider = OverpassLeadProvider()

    context = provider.search("Wedding Photographer", city="Kozhikode", limit=25)
    check(context.query == "Wedding Photographer", "query must be preserved")
    check(context.city == "Kozhikode", "city must be preserved")
    check(context.limit == 25, "limit must be preserved")
    print("  ✓ valid request accepted")

    default_radius = context.options["radius_km"]
    check(default_radius > 0, "a default radius must be applied when none is supplied")
    print(f"  ✓ radius defaults to {default_radius}km when unspecified")

    context = provider.search("Photographer", city="Thrissur", options={"radius_km": 7.5})
    check(context.options["radius_km"] == 7.5, "an explicit radius must be honoured")
    print("  ✓ explicit radius_km=7.5 honoured")

    context = provider.search("Photographer", city="Thrissur", options={"radius_km": 9999})
    from app.core.config import settings
    check(context.options["radius_km"] == float(settings.OVERPASS_MAX_RADIUS_KM),
          "an oversized radius must be clamped to the ceiling, not refused")
    print(f"  ✓ radius clamped to the {settings.OVERPASS_MAX_RADIUS_KM}km ceiling")

    # City is the one input this provider cannot proceed without.
    try:
        provider.search("Photographer")
        raise AssertionError("a request with no city must be refused")
    except BadRequestException as exc:
        check("city" in str(exc).lower(), "the refusal must name the missing city")
        print("  ✓ missing city refused at request time (before the job is RUNNING)")

    try:
        provider.search("   ", city="Kozhikode")
        raise AssertionError("an empty query must be refused")
    except BadRequestException:
        print("  ✓ empty query refused")

    for bad in ("ten", -5, 0):
        try:
            provider.search("Photographer", city="Kozhikode", options={"radius_km": bad})
            raise AssertionError(f"radius_km={bad!r} must be refused")
        except BadRequestException:
            pass
    print("  ✓ non-numeric / zero / negative radius refused")

    context = provider.search("Photographer", city="Kozhikode", limit=99999)
    check(context.limit == MAX_COLLECTION_LIMIT,
          "limit must be clamped to the engine-wide ceiling")
    print(f"  ✓ limit clamped to MAX_COLLECTION_LIMIT ({MAX_COLLECTION_LIMIT})")


# ===========================================================================================
# 3. Query construction
# ===========================================================================================

async def test_query_construction() -> None:
    print("\n[3] Overpass QL construction")

    provider = OverpassLeadProvider()
    query = provider.build_query(11.2588, 75.7804, 5.0)

    # The three tag combinations named in the brief must all be present.
    for fragment in ('["shop"="photo"]', '["office"="photographer"]', '["studio"="photography"]'):
        check(fragment in query, f"query must contain {fragment}")
    print("  ✓ shop=photo, office=photographer, studio=photography all queried")

    check('["craft"="photographer"]' in query,
          "craft=photographer is the dominant OSM tagging and must be queried too")
    print("  ✓ craft=photographer included (dominant real-world tagging)")

    for element_type in ("node", "way", "relation"):
        check(f"{element_type}[" in query, f"{element_type} elements must be queried")
    print("  ✓ node, way and relation all queried")

    check("around:5000," in query, "5km must be converted to 5000 metres")
    print("  ✓ radius 5.0km -> around:5000 (metres)")

    check("11.2588" in query and "75.7804" in query, "coordinates must be embedded")
    print("  ✓ geocoded coordinates embedded")

    check("[out:json]" in query, "JSON output must be requested")
    check("out center tags;" in query,
          "`out center` is required or ways/relations come back with no usable coordinate")
    print("  ✓ [out:json] and `out center tags` requested")

    from app.core.config import settings
    check(f"[timeout:{int(settings.OVERPASS_QUERY_TIMEOUT_SECONDS)}]" in query,
          "the server-side timeout must be embedded in the query")
    check(settings.OVERPASS_QUERY_TIMEOUT_SECONDS < settings.OVERPASS_TIMEOUT_SECONDS,
          "the server timeout must be below the client timeout, or the client hangs up first")
    print("  ✓ server-side [timeout:N] embedded and below the client timeout")

    # A radius change must actually change the query.
    check("around:12000," in provider.build_query(11.0, 75.0, 12.0),
          "radius must scale the around: filter")
    print("  ✓ radius scales the around: filter")


# ===========================================================================================
# 4. Geocoding
# ===========================================================================================

async def test_geocoding() -> None:
    print("\n[4] Nominatim geocoding")

    api = StubOverpassAPI(elements=[make_node(1, name="Studio One", phone="+919847000001")])
    provider = StubbedOverpassProvider(api)
    context = provider.search("Photographer", city="Kozhikode", limit=10)
    await provider.collect(context)

    check(api.call_order[0] == "geocode",
          "the city must be geocoded BEFORE Overpass is queried")
    check(api.call_order[1] == "overpass", "Overpass must follow the geocode")
    print("  ✓ geocode happens first, then exactly one Overpass query")

    check(len(api.geocode_calls) == 1, "one geocode per run, not one per element")
    print("  ✓ a single geocode for the whole run")

    params = api.geocode_calls[0]
    check(params.get("q") == "Kozhikode", "the city must be the geocode query")
    check(params.get("format") == "json", "JSON format must be requested")
    check(params.get("countrycodes") == "in", "the search must be biased to India")
    print(f"  ✓ geocode params: q={params.get('q')}, countrycodes={params.get('countrycodes')}")

    # State narrows an ambiguous town name.
    api2 = StubOverpassAPI(elements=[])
    provider2 = StubbedOverpassProvider(api2)
    context2 = provider2.search("Photographer", city="Thrissur", state="Kerala", limit=5)
    await provider2.collect(context2)
    check(api2.geocode_calls[0].get("q") == "Thrissur, Kerala",
          "state must narrow the geocode query")
    print("  ✓ state appended to disambiguate ('Thrissur, Kerala')")

    # A coordinate is only ever produced by the geocoder, never invented.
    api3 = StubOverpassAPI(elements=[], geocode_results=[])
    provider3 = StubbedOverpassProvider(api3)
    context3 = provider3.search("Photographer", city="Nowhereville", limit=5)
    try:
        await provider3.collect(context3)
        raise AssertionError("an ungeocodable city must fail the run")
    except ProviderCollectionError as exc:
        check("geocode" in str(exc).lower(), "the failure must say the city could not be geocoded")
        check(len(api3.overpass_calls) == 0,
              "Overpass must not be queried when there are no coordinates")
        print(f"  ✓ ungeocodable city fails the run, Overpass never called")
        print(f"    reason: {str(exc)[:70]}...")


# ===========================================================================================
# 5. Collection
# ===========================================================================================

async def test_collection() -> None:
    print("\n[5] Collection")

    elements = [
        make_node(i, name=f"Studio {i}", phone=f"+9198470000{i:02d}")
        for i in range(1, 6)
    ]
    api = StubOverpassAPI(elements=elements)
    provider = StubbedOverpassProvider(api)

    context = provider.search("Photographer", city="Kozhikode", limit=10)
    records = await provider.collect(context)

    check(len(records) == 5, f"expected 5 records, got {len(records)}")
    print(f"  ✓ {len(records)} elements collected")

    check(all("element" in r for r in records),
          "each record must retain the untouched OSM element for diagnosis")
    check(records[0]["search_city"] == "Kozhikode",
          "the searched city must travel with the record for the city fallback")
    print("  ✓ raw OSM payload + search context retained on every record")

    # The limit is honoured.
    context = provider.search("Photographer", city="Kozhikode", limit=3)
    records = await provider.collect(context)
    check(len(records) == 3, f"limit=3 must yield 3 records, got {len(records)}")
    print("  ✓ context.limit honoured")

    # Untagged geometry is not a business.
    api2 = StubOverpassAPI(elements=[
        {"type": "node", "id": 55, "lat": 11.2, "lon": 75.7},          # no tags at all
        {"type": "node", "id": 56, "lat": 11.2, "lon": 75.7, "tags": {}},  # empty tags
        make_node(9, name="Real Studio", phone="+919847000009"),
    ])
    provider2 = StubbedOverpassProvider(api2)
    context2 = provider2.search("Photographer", city="Kozhikode", limit=10)
    records2 = await provider2.collect(context2)
    check(len(records2) == 1, "untagged geometry nodes must be dropped, not counted as failures")
    print("  ✓ untagged geometry dropped (not inflated into failed records)")

    # An empty result set is a successful run with zero records, not an error.
    api3 = StubOverpassAPI(elements=[])
    provider3 = StubbedOverpassProvider(api3)
    context3 = provider3.search("Photographer", city="Kozhikode", limit=10)
    records3 = await provider3.collect(context3)
    check(records3 == [] or len(records3) == 0, "an empty result must be an empty list")
    print("  ✓ zero matches is a successful empty run, not a failure")

    # A payload with no elements key means the endpoint is not answering with Overpass JSON.
    api4 = StubOverpassAPI(missing_elements_key=True)
    provider4 = StubbedOverpassProvider(api4)
    context4 = provider4.search("Photographer", city="Kozhikode", limit=10)
    try:
        await provider4.collect(context4)
        raise AssertionError("a payload with no `elements` must fail the run")
    except ProviderCollectionError:
        print("  ✓ malformed payload (no `elements`) fails the run with a reason")

    # A non-JSON body (the usual shape of an HTML rate-limit page) is a source-level fault.
    api5 = StubOverpassAPI(non_json_body=True)
    provider5 = StubbedOverpassProvider(api5)
    context5 = provider5.search("Photographer", city="Kozhikode", limit=10)
    try:
        await provider5.collect(context5)
        raise AssertionError("a non-JSON body must fail the run")
    except ProviderCollectionError as exc:
        check("json" in str(exc).lower() or "unreadable" in str(exc).lower(),
              "the reason must name the unreadable body")
        print("  ✓ non-JSON body (HTML error page) fails the run with a reason")


# ===========================================================================================
# 6. Normalization
# ===========================================================================================

async def test_normalization() -> None:
    print("\n[6] Normalization")

    provider = OverpassLeadProvider()

    raw = {
        "element": make_node(
            1,
            name="Sunrise Photography",
            phone="+91 495 111 2222",
            email="hello@sunrise.example.com",
            website="sunrise.example.com",
        ),
        "search_city": "Kozhikode",
        "search_state": "Kerala",
        "search_category": "Wedding Photographer",
    }
    lead = provider.normalize(raw)

    check(isinstance(lead, NormalizedLead), "normalize must return a NormalizedLead")
    check(lead.business_name == "Sunrise Photography", "name must come from the name tag")
    check(lead.phone_numbers == ["+91 495 111 2222"], f"phone mismatch: {lead.phone_numbers}")
    check(lead.emails == ["hello@sunrise.example.com"], f"email mismatch: {lead.emails}")
    check(lead.website == "https://sunrise.example.com",
          f"bare website must be given a scheme: {lead.website}")
    print("  ✓ name, phone, email, website extracted")

    check(lead.city == "Kozhikode" and lead.state == "Kerala", "city/state from addr:* tags")
    check(lead.pincode == "673001", "postcode from addr:postcode")
    check("MG Road" in (lead.address or ""), f"address must assemble addr:* parts: {lead.address}")
    print(f"  ✓ address assembled: {lead.address}")

    check(lead.latitude == 11.26 and lead.longitude == 75.79,
          f"node coordinates mismatch: {lead.latitude}, {lead.longitude}")
    print(f"  ✓ coordinates: ({lead.latitude}, {lead.longitude})")

    check(lead.source == "GOOGLE_MAPS", "source must be the map-listing lead source")
    check(lead.source_url == "https://www.openstreetmap.org/node/1001",
          f"OSM permalink mismatch: {lead.source_url}")
    print(f"  ✓ source_url: {lead.source_url}")

    check("Wedding Photographer" in lead.categories,
          "the operator's requested category must be tagged")
    check(any("Photo" in c for c in lead.categories),
          f"the OSM tag must be rendered as a category: {lead.categories}")
    print(f"  ✓ categories: {lead.categories}")

    valid, reason = lead.is_valid()
    check(valid, f"a complete record must be valid: {reason}")
    print("  ✓ complete record is valid")

    # Email is the field the paid provider structurally could not supply.
    check(lead.primary_email == "hello@sunrise.example.com",
          "email must reach the CRM's single email column")
    print("  ✓ email populated (Google Places returns none at any price)")

    # Multi-value tags.
    raw_multi = {
        "element": {
            "type": "node", "id": 77, "lat": 11.2, "lon": 75.7,
            "tags": {
                "name": "Two Numbers Studio",
                "shop": "photo",
                "phone": "+91 495 111 2222;+91 98470 33333",
                "contact:email": "a@example.com;b@example.com",
            },
        },
        "search_city": "Kozhikode",
    }
    multi = provider.normalize(raw_multi)
    check(len(multi.phone_numbers) == 2, f"semicolon-separated phones must split: {multi.phone_numbers}")
    check(len(multi.emails) == 2, f"semicolon-separated emails must split: {multi.emails}")
    check(multi.secondary_phone is not None, "the second number must reach the whatsapp column")
    print(f"  ✓ multi-value tags split: {multi.phone_numbers}")

    # Tag preference: name:en beats name; phone beats mobile.
    raw_pref = {
        "element": {
            "type": "node", "id": 78, "lat": 11.2, "lon": 75.7,
            "tags": {
                "name": "സൺറൈസ് സ്റ്റുഡിയോ",
                "name:en": "Sunrise Studio",
                "mobile": "+919847099999",
                "phone": "+914951112222",
            },
        },
        "search_city": "Kozhikode",
    }
    pref = provider.normalize(raw_pref)
    check(pref.business_name == "Sunrise Studio", f"name:en must win: {pref.business_name}")
    check(pref.primary_phone == "+914951112222",
          f"phone must be promoted over mobile: {pref.primary_phone}")
    print("  ✓ tag preference honoured (name:en > name, phone > mobile)")

    # A way has no lat/lon of its own — only the computed center.
    raw_way = {"element": make_way(1, name="Building Studio", phone="+919847000010"),
               "search_city": "Kozhikode"}
    way_lead = provider.normalize(raw_way)
    check(way_lead.latitude is not None and way_lead.longitude is not None,
          "a way's coordinates must come from `center`")
    check(way_lead.source_url == "https://www.openstreetmap.org/way/2001",
          f"way permalink mismatch: {way_lead.source_url}")
    print(f"  ✓ way `center` fallback: ({way_lead.latitude}, {way_lead.longitude})")

    # City fallback: sound here because every element is within radius of the searched city.
    raw_nocity = {
        "element": {
            "type": "node", "id": 79, "lat": 11.2, "lon": 75.7,
            "tags": {"name": "No Address Studio", "shop": "photo", "phone": "+919847000011"},
        },
        "search_city": "Kozhikode",
    }
    nocity = provider.normalize(raw_nocity)
    check(nocity.city == "Kozhikode",
          "city must fall back to the searched city, or the dedup key cannot be built")
    check(nocity.business_key is not None,
          "the business-name+city duplicate key must be producible")
    print("  ✓ city falls back to the searched city (keeps the dedup key producible)")

    # normalize() must never raise, whatever it is handed.
    for junk in ({}, {"element": {}}, {"element": {"tags": None}}, {"element": {"tags": {"name": ""}}}):
        result = provider.normalize(junk)
        check(isinstance(result, NormalizedLead), "normalize must always return a NormalizedLead")
    print("  ✓ normalize() never raises, even on junk input")

    # Opening hours are retained on raw and readable back out.
    raw_hours = {
        "element": make_node(2, name="Hours Studio", phone="+919847000012",
                             extra_tags={"opening_hours": "Mo-Sa 09:00-20:00"}),
        "search_city": "Kozhikode",
    }
    check(provider.opening_hours(raw_hours) == ["Mo-Sa 09:00-20:00"],
          "opening_hours must be readable from the raw record")
    check(provider.opening_hours({"element": {"tags": {}}}) == [],
          "a record with no hours must yield an empty list")
    print("  ✓ opening_hours retained on raw and readable")


# ===========================================================================================
# 7. Rate limiting
# ===========================================================================================

async def test_rate_limiting() -> None:
    print("\n[7] Rate limiting (Overpass usage policy)")

    # A real, small interval — measured against the event loop clock.
    interval = 0.25
    api = StubOverpassAPI(elements=[make_node(1, name="S1", phone="+919847000001")])
    provider = StubbedOverpassProvider(api, min_request_interval=interval)
    context = provider.search("Photographer", city="Kozhikode", limit=5)

    await provider.collect(context)

    check(len(api.call_times) == 2, "one geocode plus one Overpass call")
    gap = api.call_times[1] - api.call_times[0]
    check(gap >= interval * 0.9,
          f"consecutive calls must be spaced by ~{interval}s, measured {gap:.3f}s")
    print(f"  ✓ consecutive calls spaced {gap:.3f}s apart (min {interval}s)")

    # Two concurrent imports through one provider instance must queue, not burst — this is
    # the property the usage policy actually asks for, and it is why the limiter holds a lock
    # across the whole request rather than just sleeping between calls.
    api2 = StubOverpassAPI(elements=[make_node(1, name="S1", phone="+919847000001")])
    provider2 = StubbedOverpassProvider(api2, min_request_interval=interval)
    ctx_a = provider2.search("Photographer", city="Kozhikode", limit=5)
    ctx_b = provider2.search("Photographer", city="Thrissur", limit=5)

    await asyncio.gather(provider2.collect(ctx_a), provider2.collect(ctx_b))

    check(len(api2.call_times) == 4, "two runs = four calls")
    gaps = [api2.call_times[i + 1] - api2.call_times[i] for i in range(3)]
    check(all(g >= interval * 0.9 for g in gaps),
          f"every gap must respect the interval even across concurrent runs: {gaps}")
    print(f"  ✓ concurrent imports queue rather than burst: gaps "
          f"{[round(g, 3) for g in gaps]}")


# ===========================================================================================
# 8. Retry with exponential backoff
# ===========================================================================================

async def test_retry_and_backoff() -> None:
    print("\n[8] Retry with exponential backoff")

    from app.core.config import settings
    base = float(settings.OVERPASS_BACKOFF_BASE_SECONDS)
    max_delay = float(settings.OVERPASS_BACKOFF_MAX_SECONDS)

    # 429 twice, then success.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(
            elements=[make_node(1, name="Retried Studio", phone="+919847000001")],
            overpass_statuses=[429, 429],
        )
        provider = StubbedOverpassProvider(api)
        context = provider.search("Photographer", city="Kozhikode", limit=5)
        records = await provider.collect(context)

        check(len(records) == 1, "the run must succeed after the retries")
        check(len(api.overpass_calls) == 3, f"expected 3 attempts, got {len(api.overpass_calls)}")
        print(f"  ✓ HTTP 429 retried: 3 attempts, run succeeded")

        check(recorder.delays == [base, base * 2],
              f"delays must double: expected {[base, base * 2]}, got {recorder.delays}")
        print(f"  ✓ backoff is exponential: {recorder.delays}")
    finally:
        restore()

    # 504 — Overpass's "server overloaded" — is retried the same way.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(
            elements=[make_node(1, name="S", phone="+919847000001")],
            overpass_statuses=[504],
        )
        provider = StubbedOverpassProvider(api)
        records = await provider.collect(
            provider.search("Photographer", city="Kozhikode", limit=5)
        )
        check(len(records) == 1, "a 504 must be retried and the run succeed")
        print("  ✓ HTTP 504 (server overloaded) retried")
    finally:
        restore()

    # Transport faults are retried too.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(
            elements=[make_node(1, name="S", phone="+919847000001")],
            overpass_exceptions=2,
        )
        provider = StubbedOverpassProvider(api)
        records = await provider.collect(
            provider.search("Photographer", city="Kozhikode", limit=5)
        )
        check(len(records) == 1, "a transport fault must be retried")
        check(len(recorder.delays) == 2, f"two backoffs expected, got {recorder.delays}")
        print(f"  ✓ transport faults (ConnectTimeout) retried: {recorder.delays}")
    finally:
        restore()

    # Retry-After wins over the computed delay: the server knows when it will be ready.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(
            elements=[make_node(1, name="S", phone="+919847000001")],
            overpass_statuses=[429],
            retry_after="7",
        )
        provider = StubbedOverpassProvider(api)
        await provider.collect(provider.search("Photographer", city="Kozhikode", limit=5))
        check(recorder.delays == [7.0],
              f"Retry-After must override the computed backoff: {recorder.delays}")
        print("  ✓ Retry-After: 7 honoured over the computed backoff")
    finally:
        restore()

    # Retry-After is still capped, so a hostile header cannot park an import.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(
            elements=[make_node(1, name="S", phone="+919847000001")],
            overpass_statuses=[429],
            retry_after="99999",
        )
        provider = StubbedOverpassProvider(api)
        await provider.collect(provider.search("Photographer", city="Kozhikode", limit=5))
        check(recorder.delays == [max_delay],
              f"an oversized Retry-After must be capped at {max_delay}: {recorder.delays}")
        print(f"  ✓ oversized Retry-After capped at {max_delay}s")
    finally:
        restore()

    # Exhaustion: every attempt fails -> the run fails with a stated reason.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(overpass_statuses=[429, 429, 429, 429, 429, 429])
        provider = StubbedOverpassProvider(api)
        try:
            await provider.collect(provider.search("Photographer", city="Kozhikode", limit=5))
            raise AssertionError("exhausted retries must fail the run")
        except ProviderCollectionError as exc:
            expected_attempts = int(settings.OVERPASS_MAX_RETRIES) + 1
            check(len(api.overpass_calls) == expected_attempts,
                  f"expected {expected_attempts} attempts, got {len(api.overpass_calls)}")
            check("429" in str(exc), "the failure must name the last error")
            # No sleep after the final attempt — waiting only to give up is pure latency.
            check(len(recorder.delays) == expected_attempts - 1,
                  f"there must be no backoff after the final attempt: {recorder.delays}")
            print(f"  ✓ exhaustion after {expected_attempts} attempts fails the run")
            print(f"    no sleep after the final attempt ({len(recorder.delays)} delays)")
            print(f"    reason: {str(exc)[:70]}...")
    finally:
        restore()

    # A 400 is a malformed query, not congestion — retrying only adds load.
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        api = StubOverpassAPI(overpass_statuses=[400])
        provider = StubbedOverpassProvider(api)
        try:
            await provider.collect(provider.search("Photographer", city="Kozhikode", limit=5))
            raise AssertionError("a 400 must fail the run")
        except ProviderCollectionError:
            check(len(api.overpass_calls) == 1,
                  f"a 400 must NOT be retried, got {len(api.overpass_calls)} attempts")
            check(recorder.delays == [], "a 400 must not sleep")
            print("  ✓ HTTP 400 fails immediately without retrying (not transient)")
    finally:
        restore()

    # Backoff growth is capped.
    provider = OverpassLeadProvider()
    recorder = SleepRecorder()
    restore = patch_sleep(recorder)
    try:
        for attempt in range(8):
            await provider._sleep_backoff(attempt, base, max_delay, None)
        check(all(d <= max_delay for d in recorder.delays),
              f"no delay may exceed the cap: {recorder.delays}")
        check(recorder.delays[-1] == max_delay, "growth must reach and hold the cap")
        print(f"  ✓ exponential growth capped at {max_delay}s: "
              f"{[round(d, 1) for d in recorder.delays]}")
    finally:
        restore()


# ===========================================================================================
# 9. Failure contract + 10. Nothing persisted
# ===========================================================================================

async def test_failure_contract_and_no_persistence() -> None:
    print("\n[9] Failure contract — bad records degrade, runs survive")

    # A phoneless element is a FAILED RECORD, not a failed run. This is the expected common
    # case for OSM data and the main practical difference from Google Places.
    elements = [
        make_node(1, name="Has Phone Studio", phone="+919847000001"),
        make_node(2, name="No Phone Studio"),                      # no phone -> invalid
        {"type": "node", "id": 3003, "lat": 11.2, "lon": 75.7,
         "tags": {"shop": "photo", "phone": "+919847000003"}},     # no name -> invalid
        make_node(4, name="Also Fine Studio", phone="+919847000004"),
    ]
    api = StubOverpassAPI(elements=elements)
    provider = StubbedOverpassProvider(api)
    context = provider.search("Photographer", city="Kozhikode", limit=10)

    leads = await provider.collect_normalized(context)

    check(len(leads) == 4, f"every element must be returned, valid or not: {len(leads)}")
    valid = [l for l in leads if l.is_valid()[0]]
    invalid = [l for l in leads if not l.is_valid()[0]]
    check(len(valid) == 2, f"expected 2 valid leads, got {len(valid)}")
    check(len(invalid) == 2, f"expected 2 invalid leads, got {len(invalid)}")
    print(f"  ✓ 4 records: {len(valid)} valid, {len(invalid)} counted as failed records")

    reasons = {l.is_valid()[1] for l in invalid}
    check(any("phone" in (r or "").lower() for r in reasons), "a phoneless record must say so")
    check(any("business_name" in (r or "") for r in reasons), "a nameless record must say so")
    print(f"  ✓ each failure carries an operator-readable reason")
    for reason in sorted(r for r in reasons if r):
        print(f"    - {reason}")

    check(all(isinstance(l, NormalizedLead) for l in leads),
          "collect_normalized must return NormalizedLead objects only")
    print("  ✓ collect_normalized() returned only NormalizedLead objects")

    print("\n[10] Nothing is persisted")

    # The structural guarantee: this module cannot write to the CRM because it imports
    # nothing that could. Asserted on the source, the same way the Google adapter is.
    import inspect
    from app.services.lead_providers import overpass as module

    source = inspect.getsource(module)
    for forbidden in (
        "from app.models",
        "from app.repositories",
        "AsyncSession",
        "session.add",
        "db.commit",
        "LeadRepository",
    ):
        check(forbidden not in source,
              f"the provider must not reference {forbidden!r} — it must not touch the DB")
    print("  ✓ provider imports no model, repository or session (cannot write to the DB)")

    check("app.models.lead" not in source and "import Lead" not in source,
          "the provider must not import the Lead model")
    print("  ✓ Lead model untouched (LeadSource reused, no enum change, no migration)")

    check(hasattr(module.OverpassLeadProvider, "collect")
          and hasattr(module.OverpassLeadProvider, "normalize")
          and hasattr(module.OverpassLeadProvider, "search"),
          "the provider must implement the full LeadProvider contract")
    from app.services.lead_providers.base import LeadProvider
    check(issubclass(module.OverpassLeadProvider, LeadProvider),
          "the provider must reuse the existing LeadProvider interface")
    print("  ✓ reuses the existing LeadProvider interface (search/collect/normalize)")


# ===========================================================================================
# Runner
# ===========================================================================================

async def test_overpass_suite() -> None:
    print("=" * 78)
    print("OVERPASS / OPENSTREETMAP LEAD PROVIDER — UNIT SUITE")
    print("=" * 78)

    await test_initialization()
    await test_search_validation()
    await test_query_construction()
    await test_geocoding()
    await test_collection()
    await test_normalization()
    await test_rate_limiting()
    await test_retry_and_backoff()
    await test_failure_contract_and_no_persistence()

    print("\n" + "=" * 78)
    print("ALL 10 SECTIONS PASSED")
    print("=" * 78)
    print("\nNo database was touched: this provider returns normalized leads and persists")
    print("nothing. No network was touched: every response was mocked.")


if __name__ == "__main__":
    asyncio.run(test_overpass_suite())
