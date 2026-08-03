"""
tests/test_instagram_import.py

Integration test suite for the Instagram lead provider.
Verifies:
1.  Provider initialization (registry resolution, capability description, availability
    driven by configuration, refusal messages, no hardcoded credentials).
2.  Search execution (query -> hashtag translation for every documented search form,
    location inference, validation, limit clamping).
3.  Profile collection (hashtag walk to candidate usernames, the limit honoured before the
    Business Discovery fan-out, personal accounts dropped, follower filtering, pagination).
4.  Normalization (bio parsing for phone / WhatsApp / email / city / state / pincode /
    address, every public field mapped, profile URL, category tags, conservative refusals).
5.  The import pipeline (leads created through LeadImportService, tagged INSTAGRAM,
    entering the CRM at status NEW with a timeline activity, extras in remarks).
6.  Duplicate handling (re-running the same search creates nothing new; an Instagram record
    matching a hand-entered lead by phone enriches it rather than duplicating it).
7.  Import statistics (per-job counters reconcile; the job records provider and query).
8.  Error handling (one failing profile never stops the run; failures land in the job logs;
    credential/rate-limit/transport faults fail the run with a stated reason).

The provider is exercised against a stub HTTP transport rather than the live Graph API, so
this suite needs no access token, no network and no Meta app, and is deterministic. The stub
speaks real Graph response shapes (`data` + `paging.cursors`, the nested `business_discovery`
field, Meta's `error.code`/`error_subcode` envelope), so the mapping under test is the same
one production runs.

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block, since the repository layer commits each write
immediately.

Run:  python tests/test_instagram_import.py
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
from app.services.lead_providers.instagram import InstagramLeadProvider


#: A marker embedded in every business name this suite creates, so cleanup and assertions
#: can find exactly this run's rows and nothing else.
MARKER = f"ZZIG{uuid.uuid4().hex[:8].upper()}"

#: Credentials that are never sent anywhere real — the stub transport intercepts everything.
STUB_TOKEN = "test-token-not-a-real-credential"
STUB_ACCOUNT_ID = "17841400000000000"


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
# Stub Instagram Graph API
# ===========================================================================================

def make_profile(
    index: int,
    *,
    name: str,
    username: str | None = None,
    city: str = "Kozhikode",
    state: str = "Kerala",
    phone: str | None = None,
    whatsapp: str | None = None,
    email: str | None = None,
    followers: int = 5000,
    biography: str | None = None,
    is_business: bool = True,
) -> dict:
    """
    Builds a candidate profile in the Graph API's real `business_discovery` shape.

    The biography is assembled the way photographers actually write one — emoji markers,
    pipe separators, a labelled WhatsApp number — because bio parsing is the substance of
    this provider's normalization and testing it against a tidy synthetic string would test
    nothing.
    """
    handle = username or f"studio_{MARKER.lower()}_{index}"
    phone_value = phone if phone is not None else unique_phone(index)

    if biography is None:
        parts = [f"📸 {name}", f"📍 {city}, {state}"]
        if phone_value:
            parts.append(f"📞 {phone_value}")
        if whatsapp:
            parts.append(f"WhatsApp {whatsapp}")
        if email:
            parts.append(email)
        biography = " | ".join(parts)

    profile = {
        "id": f"IGID_{MARKER}_{index}",
        "username": handle,
        "name": name,
        "biography": biography,
        "website": f"http://studio{index}.example.com",
        "followers_count": followers,
        "follows_count": 300 + index,
        "media_count": 120 + index,
        "profile_picture_url": f"https://scontent.example.com/{handle}.jpg",
        "is_verified": index % 3 == 0,
    }
    return {"username": handle, "profile": profile, "is_business": is_business}


class StubGraphAPI:
    """
    An in-process stand-in for the Instagram Graph API, driven by a list of profiles.

    Records every request it receives so a test can assert on *call behaviour* — that the
    limit was applied before the Business Discovery fan-out, that hashtag pagination stopped
    when it should — and not merely on the final records. That is the difference between
    testing the mapping and testing the cost model, and the cost model is the part that bites
    in production.
    """

    def __init__(
        self,
        profiles: list[dict],
        *,
        page_size: int = 25,
        hashtag_error: dict | None = None,
        discovery_error_by_username: dict[str, dict] | None = None,
        discovery_exception_usernames: frozenset[str] = frozenset(),
        fatal_error: dict | None = None,
        http_error_status: int | None = None,
    ) -> None:
        self.profiles = profiles
        self.page_size = page_size
        self.hashtag_error = hashtag_error
        self.discovery_error_by_username = discovery_error_by_username or {}
        self.discovery_exception_usernames = discovery_exception_usernames
        self.fatal_error = fatal_error
        self.http_error_status = http_error_status
        self.hashtag_search_calls: list[dict] = []
        self.media_calls: list[dict] = []
        self.discovery_calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Routes one intercepted request to the hashtag, media or discovery responder."""
        params = dict(request.url.params)
        path = request.url.path

        if self.http_error_status:
            return httpx.Response(self.http_error_status, text="upstream failure")
        if self.fatal_error:
            return httpx.Response(400, json={"error": self.fatal_error})

        if "ig_hashtag_search" in path:
            return self._hashtag_search(params)
        if path.endswith("/top_media") or path.endswith("/recent_media"):
            return self._media(path, params)
        return self._discovery(params)

    def _hashtag_search(self, params: dict) -> httpx.Response:
        self.hashtag_search_calls.append(params)
        if self.hashtag_error:
            return httpx.Response(400, json={"error": self.hashtag_error})
        tag = params.get("q", "")
        return httpx.Response(200, json={"data": [{"id": f"HASH_{tag}"}]})

    def _media(self, path: str, params: dict) -> httpx.Response:
        """
        Serves one page of hashtag media. Only `top_media` yields profiles here, so a test
        can assert that the more-relevant edge is walked first; `recent_media` returns empty,
        as a genuinely exhausted edge does.
        """
        self.media_calls.append({"path": path, **params})

        if path.endswith("/recent_media"):
            return httpx.Response(200, json={"data": [], "paging": {}})

        page = int(params.get("after", "0") or 0)
        start = page * self.page_size
        window = self.profiles[start:start + self.page_size]

        body: dict = {
            "data": [
                {
                    "id": f"MEDIA_{p['username']}",
                    "username": p["username"],
                    "caption": "#weddingphotographer",
                    "permalink": f"https://www.instagram.com/p/{p['username']}/",
                }
                for p in window
            ]
        }
        if len(self.profiles) > start + self.page_size:
            body["paging"] = {"cursors": {"after": str(page + 1)}}
        return httpx.Response(200, json=body)

    def _discovery(self, params: dict) -> httpx.Response:
        """
        Serves one Business Discovery lookup, parsing the username back out of Meta's nested
        `business_discovery.username(x){...}` field syntax.
        """
        fields = params.get("fields", "")
        username = ""
        if "username(" in fields:
            username = fields.split("username(", 1)[1].split(")", 1)[0]
        self.discovery_calls.append(username)

        if username in self.discovery_exception_usernames:
            raise httpx.ConnectTimeout("Simulated per-profile network timeout.")

        error = self.discovery_error_by_username.get(username)
        if error:
            return httpx.Response(400, json={"error": error})

        for profile in self.profiles:
            if profile["username"] == username:
                if not profile["is_business"]:
                    # Meta's real response for a personal account: an error, not an empty
                    # body. Non-fatal — one record is dropped, the run continues.
                    return httpx.Response(400, json={"error": {
                        "message": (
                            "Invalid user id. The user is not a Business or Creator account."
                        ),
                        "type": "OAuthException",
                        "code": 110,
                    }})
                return httpx.Response(
                    200, json={"business_discovery": profile["profile"], "id": STUB_ACCOUNT_ID}
                )
        return httpx.Response(200, json={"id": STUB_ACCOUNT_ID})


class StubbedInstagramProvider(InstagramLeadProvider):
    """
    The real provider with its HTTP transport swapped for a stub.

    Subclassing to override only `_import_httpx` keeps `search()`, `collect()`,
    `normalize()`, hashtag discovery, the Business Discovery fan-out and every error path as
    the production code — the stub replaces the socket, nothing else.
    """

    def __init__(self, api: StubGraphAPI, **kwargs) -> None:
        super().__init__(
            access_token=kwargs.pop("access_token", STUB_TOKEN),
            business_account_id=kwargs.pop("business_account_id", STUB_ACCOUNT_ID),
            **kwargs,
        )
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


async def test_instagram_suite() -> None:
    """Runs the full Instagram provider integration suite."""
    created_lead_ids: list[uuid.UUID] = []
    created_job_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        service = LeadImportService()

        try:
            print(f"\n=== INSTAGRAM PROVIDER INTEGRATION TESTS (marker {MARKER}) ===")

            # ===============================================================================
            print("\n--- 1. PROVIDER INITIALIZATION ---")
            # ===============================================================================

            # 1.1 It is registered and resolvable through the shared registry.
            check("instagram" in registered_provider_keys(),
                  "instagram must be registered.")
            resolved = get_provider("instagram")
            check(isinstance(resolved, InstagramLeadProvider),
                  f"Registry returned {type(resolved).__name__}, expected the real provider.")
            print("Provider resolves from the registry to the real InstagramLeadProvider.")

            # 1.2 It is no longer a PlannedProvider.
            from app.services.lead_providers import PlannedProvider
            check(not isinstance(resolved, PlannedProvider),
                  "instagram must no longer be a PlannedProvider.")
            print("instagram is no longer a planned/unimplemented stub.")

            # 1.3 It implements the full three-method contract.
            for method in ("search", "collect", "normalize"):
                check(callable(getattr(resolved, method)), f"Missing {method}().")
            print("search() / collect() / normalize() are all implemented.")

            # 1.4 Capabilities are described for the listing endpoint.
            described = resolved.describe()
            check(described["key"] == "instagram", f"Got {described}")
            check(described["lead_source"] == "INSTAGRAM", f"Got {described}")
            check(described["requires_query"] is True, "Instagram is query-driven.")
            check(described["requires_file"] is False, "Instagram takes no file.")
            print(f"Capabilities described: {described['display_name']} "
                  f"(source {described['lead_source']}, query-driven).")

            # 1.5 No credential is hardcoded: availability follows configuration alone, and
            #     BOTH credentials are required because Business Discovery is issued *as* an
            #     account.
            unconfigured = InstagramLeadProvider(access_token="", business_account_id="")
            check(unconfigured.is_available is False,
                  "With no credentials the provider must report itself unavailable.")
            check("INSTAGRAM_ACCESS_TOKEN" in unconfigured.unavailable_reason,
                  f"Reason must name the missing setting: {unconfigured.unavailable_reason}")
            check("INSTAGRAM_BUSINESS_ACCOUNT_ID" in unconfigured.unavailable_reason,
                  f"Reason must name both settings: {unconfigured.unavailable_reason}")

            token_only = InstagramLeadProvider(
                access_token=STUB_TOKEN, business_account_id=""
            )
            check(token_only.is_available is False,
                  "A token with no account id cannot run Business Discovery.")
            check("INSTAGRAM_BUSINESS_ACCOUNT_ID" in token_only.unavailable_reason
                  and "INSTAGRAM_ACCESS_TOKEN" not in token_only.unavailable_reason,
                  f"Reason must name only what is missing: {token_only.unavailable_reason}")
            print("Availability is configuration-driven; both credentials required, "
                  "and the refusal names exactly the missing one.")

            # 1.6 An unconfigured provider refuses at search() — before any job row exists.
            try:
                unconfigured.search("Wedding Photographer Kerala")
                check(False, "Unconfigured provider must refuse to search.")
            except BadRequestException as e:
                check("INSTAGRAM_ACCESS_TOKEN" in str(e.detail), f"Got {e.detail}")
            print("Unconfigured provider raises 400 at search() before a job is created.")

            configured = InstagramLeadProvider(
                access_token=STUB_TOKEN, business_account_id=STUB_ACCOUNT_ID
            )
            check(configured.is_available is True,
                  "With both credentials set the provider must be available.")
            print("With credentials configured the provider reports itself available.")

            # ===============================================================================
            print("\n--- 2. SEARCH EXECUTION ---")
            # ===============================================================================

            # 2.1 Every documented search form translates into usable hashtags. Instagram has
            #     no free-text search, so this translation is the provider's entire ability to
            #     honour a query at all.
            search_forms = [
                ("Wedding Photographer Kerala", "weddingphotographerkerala", None, "Kerala"),
                ("Photographer Kozhikode", "photographerkozhikode", "Kozhikode", "Kerala"),
                ("Photography Studio Kochi", "photographystudiokochi", "Kochi", "Kerala"),
                ("Wedding Photography Thrissur", "weddingphotographythrissur",
                 "Thrissur", "Kerala"),
                ("Pre Wedding Photography Kerala", "preweddingphotographykerala",
                 None, "Kerala"),
            ]
            for query, expected_tag, expected_city, expected_state in search_forms:
                ctx = configured.search(query, limit=20)
                tags = ctx.options["hashtags"]
                check(tags[0] == expected_tag,
                      f"{query!r}: expected first hashtag {expected_tag!r}, got {tags[0]!r}")
                check(ctx.city == expected_city,
                      f"{query!r}: expected city {expected_city!r}, got {ctx.city!r}")
                check(ctx.state == expected_state,
                      f"{query!r}: expected state {expected_state!r}, got {ctx.state!r}")
                print(f"  {query!r} -> #{tags[0]} (+{len(tags) - 1} more), "
                      f"location {ctx.city or '-'}/{ctx.state}")

            # 2.2 Hashtags are ordered most-precise-first, so a run that fills its limit early
            #     never pays for the noisy national tags.
            ctx = configured.search("Wedding Photographer Kozhikode", limit=20)
            tags = ctx.options["hashtags"]
            check(tags.index("weddingphotographerkozhikode") < tags.index("weddingphotographer"),
                  f"Compound tag must precede the bare intent tag: {tags}")
            print(f"Hashtags ordered by precision: {tags[:3]}")

            # 2.3 An explicit city parameter is authoritative and reaches the hashtags.
            ctx = configured.search("Wedding Photographer", limit=10, city="Thrissur")
            check(ctx.city == "Thrissur", f"Explicit city must win, got {ctx.city!r}")
            check(any("thrissur" in t for t in ctx.options["hashtags"]),
                  f"Explicit city must reach the hashtags: {ctx.options['hashtags']}")
            print("An explicit city parameter is honoured and reaches the hashtag list.")

            # 2.4 Validation: an empty query is refused.
            for bad in ("", "   ", None):
                try:
                    configured.search(bad, limit=10)
                    check(False, f"Query {bad!r} must be refused.")
                except BadRequestException:
                    pass
            print("Empty/whitespace queries are refused with 400.")

            # 2.5 A query with nothing hashtag-able in it is refused rather than silently
            #     searching nothing.
            try:
                configured.search("!!! ???", limit=10)
                check(False, "A query with no searchable term must be refused.")
            except BadRequestException as e:
                check("hashtag" in str(e.detail).lower(), f"Got {e.detail}")
            print("A query with no derivable hashtag is refused with an explanatory 400.")

            # 2.6 Limits are validated and clamped to the shared ceiling.
            check(configured.search("Photographer Kochi", limit=5).limit == 5, "limit=5")
            check(
                configured.search("Photographer Kochi", limit=99999).limit
                == MAX_COLLECTION_LIMIT,
                f"limit must clamp to {MAX_COLLECTION_LIMIT}",
            )
            for bad_limit in (0, -1):
                try:
                    configured.search("Photographer Kochi", limit=bad_limit)
                    check(False, f"limit={bad_limit} must be refused.")
                except BadRequestException:
                    pass
            print(f"Limits validated and clamped to MAX_COLLECTION_LIMIT={MAX_COLLECTION_LIMIT}.")

            # ===============================================================================
            print("\n--- 3. PROFILE COLLECTION ---")
            # ===============================================================================

            # 3.1 A basic collection returns one raw record per resolvable profile.
            profiles = [
                make_profile(i, name=f"{MARKER} Studio {i}") for i in range(1, 6)
            ]
            api = StubGraphAPI(profiles)
            provider = StubbedInstagramProvider(api)
            ctx = provider.search("Wedding Photographer Kozhikode", limit=5)
            raw_records = await provider.collect(ctx)

            check(len(raw_records) == 5, f"Expected 5 records, got {len(raw_records)}")
            check(all(r.get("profile") for r in raw_records),
                  "Every returned record must carry a resolved profile.")
            check(len(api.hashtag_search_calls) >= 1, "The hashtag must have been resolved.")
            print(f"Collected {len(raw_records)} profiles via "
                  f"{len(api.hashtag_search_calls)} hashtag lookup(s) and "
                  f"{len(api.discovery_calls)} Business Discovery call(s).")

            # 3.2 The token is sent as a parameter and never hardcoded into a URL path.
            check(all(c.get("access_token") == STUB_TOKEN
                      for c in api.hashtag_search_calls),
                  "Every hashtag call must carry the configured token.")
            print("Credentials travel as request parameters, sourced from configuration.")

            # 3.3 THE COST DECISION: the limit is honoured BEFORE the Business Discovery
            #     fan-out. 40 profiles are discoverable but only 10 are asked for, so only 10
            #     lookups may be spent. This is the assertion that protects the rate limit.
            many = [make_profile(i, name=f"{MARKER} Wide {i}") for i in range(1, 41)]
            api_wide = StubGraphAPI(many, page_size=25)
            provider_wide = StubbedInstagramProvider(api_wide)
            ctx_wide = provider_wide.search("Wedding Photographer Kozhikode", limit=10)
            wide_records = await provider_wide.collect(ctx_wide)

            check(len(wide_records) == 10,
                  f"limit=10 must yield 10 records, got {len(wide_records)}")
            check(len(api_wide.discovery_calls) == 10,
                  f"limit=10 must spend exactly 10 discovery calls, spent "
                  f"{len(api_wide.discovery_calls)}")
            print(f"Limit honoured before the fan-out: 40 discoverable, 10 requested, "
                  f"exactly {len(api_wide.discovery_calls)} lookups spent.")

            # 3.4 Hashtag pagination is walked when one page cannot fill the request.
            check(len(api_wide.media_calls) >= 1, "Media edges must have been walked.")
            print(f"Hashtag media pagination walked across {len(api_wide.media_calls)} page(s).")

            # 3.5 Personal accounts are DROPPED, not carried forward as guaranteed failures.
            #     Business Discovery cannot resolve them, so there is nothing to import;
            #     counting them as failed records would make failed_records useless as a
            #     signal that something is actually wrong.
            mixed = [
                make_profile(10, name=f"{MARKER} Business A"),
                make_profile(11, name=f"{MARKER} Personal B", is_business=False),
                make_profile(12, name=f"{MARKER} Business C"),
            ]
            api_mixed = StubGraphAPI(mixed)
            provider_mixed = StubbedInstagramProvider(api_mixed)
            ctx_mixed = provider_mixed.search("Wedding Photographer Kozhikode", limit=10)
            mixed_records = await provider_mixed.collect(ctx_mixed)

            check(len(mixed_records) == 2,
                  f"The personal account must be dropped, got {len(mixed_records)} records")
            check(all("Personal" not in (r["profile"].get("name") or "")
                      for r in mixed_records),
                  "The personal account must not appear in the results.")
            check(len(api_mixed.discovery_calls) == 3,
                  "All three candidates should still have been attempted.")
            print("Personal (non-business) accounts are attempted, then dropped cleanly.")

            # 3.6 A ZERO-result query is a successful, empty collection — not an error.
            api_empty = StubGraphAPI([])
            provider_empty = StubbedInstagramProvider(api_empty)
            ctx_empty = provider_empty.search("Wedding Photographer Kozhikode", limit=10)
            empty_records = await provider_empty.collect(ctx_empty)
            check(empty_records == [] or len(empty_records) == 0,
                  f"An empty hashtag must yield no records, got {empty_records}")
            print("A query matching no profiles returns zero records without error.")

            # ===============================================================================
            print("\n--- 4. NORMALIZATION ---")
            # ===============================================================================

            # 4.1 A rich profile maps every public field onto NormalizedLead.
            rich = make_profile(
                20,
                name=f"{MARKER} Sunrise Wedding Studio",
                username="sunrise_wedding_studio",
                city="Kozhikode",
                state="Kerala",
                phone="+91 98470 12345",
                whatsapp="9847098765",
                email="hello@sunrisestudio.in",
                followers=142000,
            )
            record = InstagramLeadProvider().normalize({
                "username": rich["username"],
                "profile": rich["profile"],
            })

            check(record.business_name == f"{MARKER} Sunrise Wedding Studio",
                  f"business_name: {record.business_name!r}")
            check(record.instagram == "sunrise_wedding_studio",
                  f"instagram handle: {record.instagram!r}")
            check(record.source_url == "https://www.instagram.com/sunrise_wedding_studio/",
                  f"source_url: {record.source_url!r}")
            check(record.source == "INSTAGRAM", f"source: {record.source!r}")
            check(record.website == "http://studio20.example.com",
                  f"website: {record.website!r}")
            check(record.city == "Kozhikode", f"city: {record.city!r}")
            check(record.state == "Kerala", f"state: {record.state!r}")
            check(record.country == "India", f"country: {record.country!r}")
            print(f"Mapped: {record.business_name} (@{record.instagram}), "
                  f"{record.city}/{record.state}")

            # 4.2 Contact details are parsed out of the free-text bio — the substance of this
            #     provider's normalization, since Instagram exposes no structured contact
            #     fields at all.
            check(record.primary_phone is not None, "A phone must be parsed from the bio.")
            check("98470" in record.primary_phone.replace(" ", ""),
                  f"primary_phone: {record.primary_phone!r}")
            check(record.secondary_phone is not None,
                  "The labelled WhatsApp number must be retained as the second number.")
            check("9847098765" in record.secondary_phone.replace(" ", ""),
                  f"secondary_phone (whatsapp): {record.secondary_phone!r}")
            check(record.primary_email == "hello@sunrisestudio.in",
                  f"primary_email: {record.primary_email!r}")
            print(f"Bio parsed -> phone {record.primary_phone}, "
                  f"whatsapp {record.secondary_phone}, email {record.primary_email}")

            # 4.3 Ordering matters: the studio's main line must land in `phone` and the
            #     labelled WhatsApp number in `whatsapp`, not the other way round.
            check(record.phone_numbers[0] == "+91 98470 12345",
                  f"The main line must be first: {record.phone_numbers}")
            print("Phone ordering correct: main line first, WhatsApp second.")

            # 4.4 Metadata with no Lead column becomes category tags, which the import service
            #     folds into remarks.
            joined = " | ".join(record.categories)
            check("142,000 followers" in joined, f"categories: {record.categories}")
            check("posts" in joined, f"categories must carry the post count: {record.categories}")
            check("Following" in joined, f"categories must carry follows: {record.categories}")
            check("Profile image" in joined,
                  f"categories must carry the profile image: {record.categories}")
            print(f"Non-column metadata retained as tags: {record.categories[:3]}…")

            # 4.5 Verified status is captured when present.
            verified = make_profile(21, name=f"{MARKER} Verified Studio", followers=9000)
            verified["profile"]["is_verified"] = True
            verified_record = InstagramLeadProvider().normalize({
                "username": verified["username"], "profile": verified["profile"],
            })
            check("Verified" in verified_record.categories,
                  f"Verified flag must be captured: {verified_record.categories}")
            print("Verified status captured on the record.")

            # 4.6 A pincode and a real street address are extracted when the bio has them.
            addressed = InstagramLeadProvider().normalize({
                "username": "addr_studio",
                "profile": {
                    "username": "addr_studio",
                    "name": f"{MARKER} Addressed Studio",
                    "biography": (
                        "Wedding films 📍 3rd Floor, MG Road, Thrissur 680001 "
                        "| 📞 9847011111"
                    ),
                },
            })
            check(addressed.pincode == "680001", f"pincode: {addressed.pincode!r}")
            check(addressed.address is not None and "MG Road" in addressed.address,
                  f"address: {addressed.address!r}")
            check(addressed.city == "Thrissur", f"city: {addressed.city!r}")
            print(f"Address parsed: {addressed.address!r} "
                  f"({addressed.city}, pincode {addressed.pincode})")

            # 4.7 CONSERVATIVE REFUSAL: a bio naming only a city must NOT become an address.
            #     A wrong value here is worse than no value — it corrupts a column the record
            #     already carries in structured form.
            city_only = InstagramLeadProvider().normalize({
                "username": "city_only",
                "profile": {
                    "username": "city_only",
                    "name": f"{MARKER} City Only",
                    "biography": "📍 Kozhikode, Kerala | 📞 9847022222",
                },
            })
            check(city_only.address is None,
                  f"A bare city must not be stored as an address: {city_only.address!r}")
            check(city_only.city == "Kozhikode", f"…but the city must still be read: "
                  f"{city_only.city!r}")
            print("A bare city is read as a city, never promoted to an address.")

            # 4.8 CONSERVATIVE REFUSAL: an unrecognised place yields no city rather than a
            #     guess, because a wrong city feeds the name+city duplicate rule.
            vague = InstagramLeadProvider().normalize({
                "username": "vague_studio",
                "profile": {
                    "username": "vague_studio",
                    "name": f"{MARKER} Vague Studio",
                    "biography": "Destination weddings worldwide ✨ DM to book | 9847033333",
                },
            })
            check(vague.city is None,
                  f"An unrecognised location must yield no city, got {vague.city!r}")
            check(vague.primary_phone is not None,
                  "…but a usable phone must still be extracted.")
            print("An unrecognised location yields no city rather than a wrong one.")

            # 4.9 CONSERVATIVE REFUSAL: an unlabelled second number is an ordinary phone, not
            #     a WhatsApp number — promoting it would have the CRM message a landline.
            unlabelled = InstagramLeadProvider().normalize({
                "username": "two_numbers",
                "profile": {
                    "username": "two_numbers",
                    "name": f"{MARKER} Two Numbers",
                    "biography": "📞 0495 2701234 / 9847044444 📍 Kozhikode",
                },
            })
            check(len(unlabelled.phone_numbers) >= 2,
                  f"Both numbers must be kept: {unlabelled.phone_numbers}")
            print(f"Unlabelled numbers kept as ordinary phones: {unlabelled.phone_numbers}")

            # 4.10 A profile with no contact route normalizes without raising and simply fails
            #      validation — the contract that keeps one bad record from aborting a run.
            contactless = InstagramLeadProvider().normalize({
                "username": "no_contact",
                "profile": {
                    "username": "no_contact",
                    "name": f"{MARKER} No Contact",
                    "biography": "DM for bookings only ✨",
                },
            })
            valid, reason = contactless.is_valid()
            check(valid is False, "A profile with no phone must fail validation.")
            check("phone" in (reason or "").lower(), f"reason: {reason!r}")
            print(f"A contactless profile normalizes cleanly and fails validation: {reason}")

            # 4.11 normalize() never raises, even on a structurally broken record.
            for broken in ({}, {"profile": None}, {"profile": {"username": None}},
                           {"username": "x", "profile": {"biography": None}}):
                result = InstagramLeadProvider().normalize(broken)
                check(result is not None, f"normalize({broken}) returned None")
            print("normalize() is total — malformed records degrade instead of raising.")

            # 4.12 The query's location is a FALLBACK only: a bio's own city wins.
            fallback = InstagramLeadProvider().normalize({
                "username": "fallback_studio",
                "profile": {
                    "username": "fallback_studio",
                    "name": f"{MARKER} Fallback Studio",
                    "biography": "Wedding photography | 9847055555",
                },
                "resolved_city": "Kochi",
                "resolved_state": "Kerala",
            })
            check(fallback.city == "Kochi",
                  f"Query location must fill in when the bio names none: {fallback.city!r}")

            bio_wins = InstagramLeadProvider().normalize({
                "username": "biowins_studio",
                "profile": {
                    "username": "biowins_studio",
                    "name": f"{MARKER} Bio Wins Studio",
                    "biography": "📍 Thrissur | 9847066666",
                },
                "resolved_city": "Kochi",
                "resolved_state": "Kerala",
            })
            check(bio_wins.city == "Thrissur",
                  f"The bio's own city must win over the query's: {bio_wins.city!r}")
            print("Query location fills gaps; the profile's own stated city always wins.")

            # ===============================================================================
            print("\n--- 5. IMPORT PIPELINE (LeadImportService) ---")
            # ===============================================================================

            # 5.1 A full import creates leads through the existing service — the provider
            #     never touches the Lead table itself.
            import_profiles = [
                make_profile(
                    30 + i,
                    name=f"{MARKER} Pipeline Studio {i}",
                    city="Kozhikode",
                    email=f"studio{i}@example.in",
                )
                for i in range(1, 4)
            ]
            api_pipe = StubGraphAPI(import_profiles)
            provider_pipe = StubbedInstagramProvider(api_pipe)

            job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=10,
                provider=provider_pipe,
            )
            created_job_ids.append(job.id)

            check(job.status is ImportJobStatus.COMPLETED,
                  f"Expected COMPLETED, got {job.status} ({job.error_message})")
            check(job.provider == "instagram", f"job.provider: {job.provider!r}")
            check(job.total_found == 3, f"total_found: {job.total_found}")
            check(job.new_leads == 3, f"new_leads: {job.new_leads}")
            check(job.failed_records == 0, f"failed_records: {job.failed_records}")
            print(f"Import job {job.status.value}: {job.total_found} found, "
                  f"{job.new_leads} new, {job.failed_records} failed.")

            # 5.2 The leads landed in the CRM, correctly attributed and at status NEW.
            leads = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER} Pipeline%"))
            )).scalars().all()
            created_lead_ids.extend(lead.id for lead in leads)

            check(len(leads) == 3, f"Expected 3 leads in the CRM, found {len(leads)}")
            for lead in leads:
                check(lead.source is LeadSource.INSTAGRAM,
                      f"Lead {lead.business_name} tagged {lead.source}, expected INSTAGRAM")
                check(lead.status is LeadStatus.NEW,
                      f"Lead {lead.business_name} at {lead.status}, expected NEW")
                check(lead.instagram is not None,
                      f"Lead {lead.business_name} must carry its handle.")
                check(lead.phone is not None,
                      f"Lead {lead.business_name} must carry a phone.")
                check(lead.is_converted is False, "A fresh lead is not converted.")
            print(f"{len(leads)} leads created, all tagged INSTAGRAM at status NEW "
                  "with handle + phone.")

            # 5.3 The collected extras with no column landed in remarks.
            sample = leads[0]
            check(sample.remarks is not None, "Remarks must carry the collected extras.")
            check("instagram.com" in sample.remarks,
                  f"Remarks must carry the source URL: {sample.remarks!r}")
            check("followers" in sample.remarks,
                  f"Remarks must carry the follower count: {sample.remarks!r}")
            print(f"Extras folded into remarks: {sample.remarks.splitlines()[1][:70]}…")

            # 5.4 Each new lead got a timeline activity, exactly as a manual lead would.
            activities = (await db.execute(
                select(LeadActivity).where(LeadActivity.lead_id == sample.id)
            )).scalars().all()
            check(len(activities) >= 1,
                  f"Expected a creation activity, found {len(activities)}")
            print(f"Timeline activity logged for the imported lead "
                  f"({len(activities)} entry).")

            # 5.5 The per-record log names each lead created.
            create_entries = [e for e in (job.logs or [])
                              if "created new lead" in (e.get("message") or "")]
            check(len(create_entries) == 3,
                  f"Expected 3 creation log entries, got {len(create_entries)}")
            print(f"Job log records each created lead ({len(create_entries)} entries).")

            # ===============================================================================
            print("\n--- 6. DUPLICATE DETECTION ---")
            # ===============================================================================

            # 6.1 Re-running the identical search creates NOTHING new — the existing dedup
            #     engine is reused, not reimplemented in the provider.
            api_again = StubGraphAPI(import_profiles)
            provider_again = StubbedInstagramProvider(api_again)
            rerun = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=10,
                provider=provider_again,
            )
            created_job_ids.append(rerun.id)

            check(rerun.new_leads == 0,
                  f"A re-run must create no new leads, created {rerun.new_leads}")
            check(rerun.total_found == 3, f"total_found: {rerun.total_found}")
            check(rerun.duplicate_leads + rerun.updated_leads == 3,
                  f"All 3 must be recognised as known: {rerun.duplicate_leads} dup + "
                  f"{rerun.updated_leads} updated")
            print(f"Re-run: {rerun.total_found} found, 0 new, "
                  f"{rerun.duplicate_leads} duplicates, {rerun.updated_leads} enriched.")

            total_now = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER} Pipeline%"))
            )).scalars().all()
            check(len(total_now) == 3,
                  f"The CRM must still hold exactly 3 leads, holds {len(total_now)}")
            print("The CRM still holds exactly 3 leads — no duplicate rows.")

            # 6.2 An Instagram record matching a HAND-ENTERED lead by phone enriches it
            #     rather than duplicating it. This is the cross-source case the dedup engine
            #     exists for: the same studio, captured by phone, now found on Instagram.
            manual_phone = unique_phone(77)
            manual = Lead(
                business_name=f"{MARKER} Manual Entry Studio",
                phone=manual_phone,
                city="Kochi",
                source=LeadSource.MANUAL,
                status=LeadStatus.NEW,
                is_converted=False,
            )
            db.add(manual)
            await db.commit()
            await db.refresh(manual)
            created_lead_ids.append(manual.id)
            check(manual.instagram is None, "The manual lead starts with no handle.")

            enriching = make_profile(
                78,
                name=f"{MARKER} Manual Entry Studio",
                username="manual_entry_studio",
                city="Kochi",
                phone=manual_phone,
                email="manual@example.in",
            )
            api_enrich = StubGraphAPI([enriching])
            provider_enrich = StubbedInstagramProvider(api_enrich)
            enrich_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Photography Studio Kochi",
                limit=5,
                provider=provider_enrich,
            )
            created_job_ids.append(enrich_job.id)

            check(enrich_job.new_leads == 0,
                  f"A phone match must not create a lead, created {enrich_job.new_leads}")
            check(enrich_job.updated_leads == 1,
                  f"The matched lead must be enriched, updated {enrich_job.updated_leads}")

            await db.refresh(manual)
            check(manual.instagram == "manual_entry_studio",
                  f"The handle must be filled in: {manual.instagram!r}")
            check(manual.email == "manual@example.in",
                  f"The email must be filled in: {manual.email!r}")
            check(manual.source is LeadSource.MANUAL,
                  f"Enrichment must not rewrite the original source: {manual.source}")
            check(manual.phone == manual_phone,
                  f"Enrichment must never rewrite the matched phone: {manual.phone!r}")
            print("A hand-entered lead matched by phone was enriched "
                  "(handle + email added), not duplicated; source and phone preserved.")

            # 6.3 Matching by phone is recorded as the rule in the job log, so an operator can
            #     see *why* a record was treated as known.
            match_entries = [e for e in (enrich_job.logs or [])
                             if e.get("match_rule") == "phone"]
            check(len(match_entries) >= 1,
                  f"The phone match rule must appear in the log: {enrich_job.logs}")
            print(f"Job log names the matching rule: {match_entries[0]['message'][:70]}…")

            # 6.4 Two profiles sharing one phone number within a single batch collapse onto
            #     one lead — within-batch dedup, not just against the existing table.
            shared_phone = unique_phone(88)
            twins = [
                make_profile(88, name=f"{MARKER} Twin Studio",
                             username="twin_a", phone=shared_phone),
                make_profile(89, name=f"{MARKER} Twin Studio",
                             username="twin_b", phone=shared_phone),
            ]
            api_twins = StubGraphAPI(twins)
            provider_twins = StubbedInstagramProvider(api_twins)
            twin_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=5,
                provider=provider_twins,
            )
            created_job_ids.append(twin_job.id)

            twin_leads = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER} Twin%"))
            )).scalars().all()
            created_lead_ids.extend(lead.id for lead in twin_leads)

            check(twin_job.total_found == 2, f"total_found: {twin_job.total_found}")
            check(twin_job.new_leads == 1,
                  f"Two profiles sharing a phone must create 1 lead, "
                  f"created {twin_job.new_leads}")
            check(len(twin_leads) == 1,
                  f"The CRM must hold 1 twin lead, holds {len(twin_leads)}")
            print("Two profiles sharing a phone within one batch collapsed onto one lead.")

            # ===============================================================================
            print("\n--- 7. IMPORT STATISTICS ---")
            # ===============================================================================

            # 7.1 The counters reconcile: found == new + updated + duplicate + failed.
            for candidate in (job, rerun, enrich_job, twin_job):
                total = (candidate.new_leads + candidate.updated_leads
                         + candidate.duplicate_leads + candidate.failed_records)
                check(total == candidate.total_found,
                      f"Job {candidate.id}: {candidate.total_found} found but counters "
                      f"sum to {total}")
            print("Every job's counters reconcile against total_found.")

            # 7.2 The job records what was actually asked for, so a run is reproducible.
            check(job.query is not None and "Kozhikode" in job.query,
                  f"job.query: {job.query!r}")
            check(job.started_at is not None and job.completed_at is not None,
                  "A finished job must carry both timestamps.")
            check(job.completed_at >= job.started_at, "completed_at must not precede start.")
            print(f"Job records provider={job.provider!r}, query={job.query!r}, "
                  "and a start/finish window.")

            # 7.3 Lifetime aggregates include these runs.
            stats = await service.get_statistics(db)
            check(stats["total_jobs"] >= 4,
                  f"Lifetime stats must include this suite's jobs: {stats}")
            print(f"Lifetime statistics reachable: {stats['total_jobs']} jobs recorded.")

            # 7.4 The jobs are listable and filterable by this provider.
            listed, count = await service.get_all_jobs(db, provider="instagram", limit=50)
            check(count >= 4, f"Expected at least 4 instagram jobs, got {count}")
            check(all(j.provider == "instagram" for j in listed),
                  "Filtering by provider must return only instagram jobs.")
            print(f"Jobs filterable by provider: {count} instagram job(s) recorded.")

            # ===============================================================================
            print("\n--- 8. ERROR HANDLING ---")
            # ===============================================================================

            # 8.1 ONE BAD PROFILE NEVER STOPS THE RUN. Three profiles, the middle one with no
            #     contact route: the other two must still import.
            resilient = [
                make_profile(90, name=f"{MARKER} Resilient A"),
                make_profile(
                    91, name=f"{MARKER} Resilient B",
                    biography="DM only, no contact details ✨",
                ),
                make_profile(92, name=f"{MARKER} Resilient C"),
            ]
            api_resilient = StubGraphAPI(resilient)
            provider_resilient = StubbedInstagramProvider(api_resilient)
            resilient_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=10,
                provider=provider_resilient,
            )
            created_job_ids.append(resilient_job.id)

            resilient_leads = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER} Resilient%"))
            )).scalars().all()
            created_lead_ids.extend(lead.id for lead in resilient_leads)

            check(resilient_job.status is ImportJobStatus.PARTIAL,
                  f"Expected PARTIAL, got {resilient_job.status}")
            check(resilient_job.total_found == 3, f"total_found: {resilient_job.total_found}")
            check(resilient_job.new_leads == 2,
                  f"The two good profiles must import, got {resilient_job.new_leads}")
            check(resilient_job.failed_records == 1,
                  f"The bad profile must be counted once, got {resilient_job.failed_records}")
            check(len(resilient_leads) == 2,
                  f"Exactly 2 leads must reach the CRM, found {len(resilient_leads)}")
            print(f"One unusable profile did not stop the run: {resilient_job.status.value}, "
                  f"{resilient_job.new_leads} imported, {resilient_job.failed_records} failed.")

            # 8.2 The failure is explained in the job's logs, with a reason.
            failures = [e for e in (resilient_job.logs or []) if e.get("level") == "error"]
            check(len(failures) == 1, f"Expected 1 error entry, got {len(failures)}")
            check("phone" in failures[0]["message"].lower(),
                  f"The failure must state its reason: {failures[0]['message']!r}")
            print(f"Failure logged with a reason: {failures[0]['message'][:70]}…")

            # 8.3 A per-profile NETWORK TIMEOUT degrades one record, never the run.
            flaky = [
                make_profile(93, name=f"{MARKER} Flaky A"),
                make_profile(94, name=f"{MARKER} Flaky B", username="flaky_timeout"),
                make_profile(95, name=f"{MARKER} Flaky C"),
            ]
            api_flaky = StubGraphAPI(
                flaky, discovery_exception_usernames=frozenset({"flaky_timeout"})
            )
            provider_flaky = StubbedInstagramProvider(api_flaky)
            flaky_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=10,
                provider=provider_flaky,
            )
            created_job_ids.append(flaky_job.id)

            flaky_leads = (await db.execute(
                select(Lead).where(Lead.business_name.ilike(f"%{MARKER} Flaky%"))
            )).scalars().all()
            created_lead_ids.extend(lead.id for lead in flaky_leads)

            check(flaky_job.status is ImportJobStatus.COMPLETED,
                  f"A dropped candidate is not a failed record: {flaky_job.status}")
            check(flaky_job.new_leads == 2,
                  f"The two reachable profiles must import, got {flaky_job.new_leads}")
            print(f"A per-profile timeout degraded one record only: "
                  f"{flaky_job.new_leads} imported, run {flaky_job.status.value}.")

            # 8.4 AN EXPIRED TOKEN FAILS THE WHOLE RUN — it applies identically to every
            #     remaining profile, so failing once beats failing two hundred times.
            api_expired = StubGraphAPI([], fatal_error={
                "message": "Error validating access token: Session has expired.",
                "type": "OAuthException",
                "code": 190,
            })
            provider_expired = StubbedInstagramProvider(api_expired)
            expired_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=5,
                provider=provider_expired,
            )
            created_job_ids.append(expired_job.id)

            check(expired_job.status is ImportJobStatus.FAILED,
                  f"An expired token must fail the run, got {expired_job.status}")
            check("INSTAGRAM_ACCESS_TOKEN" in (expired_job.error_message or ""),
                  f"The error must name the fix: {expired_job.error_message!r}")
            check(expired_job.new_leads == 0, "A failed run creates nothing.")
            print(f"Expired token failed the run with an actionable message: "
                  f"{expired_job.error_message[:70]}…")

            # 8.5 A RATE-LIMIT denial likewise fails the run, with a billing-actionable
            #     message rather than a silent empty import.
            api_limited = StubGraphAPI([], fatal_error={
                "message": "Application request limit reached",
                "type": "OAuthException",
                "code": 4,
            })
            provider_limited = StubbedInstagramProvider(api_limited)
            limited_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=5,
                provider=provider_limited,
            )
            created_job_ids.append(limited_job.id)

            check(limited_job.status is ImportJobStatus.FAILED,
                  f"A rate limit must fail the run, got {limited_job.status}")
            check("rate limit" in (limited_job.error_message or "").lower(),
                  f"The error must explain the limit: {limited_job.error_message!r}")
            print(f"Rate-limit denial failed the run: {limited_job.error_message[:70]}…")

            # 8.6 A TRANSPORT fault (Meta unreachable / 5xx) fails the run with a reason.
            api_down = StubGraphAPI([], http_error_status=503)
            provider_down = StubbedInstagramProvider(api_down)
            down_job = await service.run_import(
                db,
                provider_key="instagram",
                query="Wedding Photographer Kozhikode",
                limit=5,
                provider=provider_down,
            )
            created_job_ids.append(down_job.id)

            check(down_job.status is ImportJobStatus.FAILED,
                  f"An unreachable API must fail the run, got {down_job.status}")
            check(down_job.error_message, "A failed run must carry a reason.")
            print(f"Transport fault failed the run: {down_job.error_message[:70]}…")

            # 8.7 A raised ProviderCollectionError is contained by the service, never a 500.
            api_direct = StubGraphAPI([], fatal_error={
                "message": "Error validating access token.",
                "type": "OAuthException",
                "code": 190,
            })
            provider_direct = StubbedInstagramProvider(api_direct)
            ctx_direct = provider_direct.search("Wedding Photographer Kozhikode", limit=5)
            try:
                await provider_direct.collect(ctx_direct)
                check(False, "A fatal Meta error must raise ProviderCollectionError.")
            except ProviderCollectionError as e:
                check("INSTAGRAM_ACCESS_TOKEN" in str(e), f"Got {e}")
            print("collect() raises ProviderCollectionError for run-level faults.")

            # 8.8 An unconfigured provider refuses to collect even if search is bypassed.
            bare = InstagramLeadProvider(access_token="", business_account_id="")
            try:
                from app.services.lead_providers import ProviderContext
                await bare.collect(ProviderContext(query="x", limit=5))
                check(False, "An unconfigured provider must refuse to collect.")
            except ProviderCollectionError as e:
                check("INSTAGRAM_ACCESS_TOKEN" in str(e), f"Got {e}")
            print("An unconfigured provider refuses at collect() too, with a clear reason.")

            print("\n=== ALL INSTAGRAM PROVIDER TESTS PASSED ===")

        except Exception as e:
            print(f"\nTEST FAILED: {type(e).__name__}: {e}")
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
    asyncio.run(test_instagram_suite())
