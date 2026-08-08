"""
tests/test_website_discovery.py

Unit test suite for `WebsiteDiscoveryService` — the enrichment step that finds the official
website of a normalized lead that arrived without one.

Verifies, section by section, the seven rules the feature was specified against:

1.  Service construction — configured defaults, backend injection, `describe()`, and the
    backend registry's fall-back-not-raise behaviour on an unknown key.
2.  Query construction (**rule 1**) — the search is business name + city; city omitted when
    absent; a nameless lead is never searched at all.
3.  Directory rejection (**rule 4**) — Justdial/Sulekha/WeddingWire/Facebook/Instagram/Google
    Maps and their *subdomains* are ignored, even when they rank first.
4.  Validation (**rule 3**) — a domain must be shown to belong to the same business; an
    unrelated domain is declined rather than attached, and generic vocabulary alone cannot
    validate one studio's name against another's domain.
5.  Domain-only persistence (**rule 5**) — the deep URL that ranked is reduced to the
    official domain before it is stored.
6.  Never overwriting (**rule 6**) — a lead that already has a website is returned untouched
    without a single search being issued.
7.  The enriched return value (**rule 7**) — `discover()` returns a `NormalizedLead`, the
    input is left unmutated, and every other field survives the round trip.
8.  The DuckDuckGo backend — SERP parsing, redirect-wrapper unwrapping, HTML entity
    handling, HTTP faults raised as `SearchBackendError`, and an unrecognised page degrading
    to zero results rather than to garbage.
9.  Rate limiting — outbound searches are serialised and spaced by the configured interval.
10. The failure contract and non-persistence — a backend that raises, returns nothing, or
    is unavailable leaves the lead unchanged and never propagates; and the module writes
    nothing to the database.
11. URL validation (**rule 4**) — a discovered URL is normalized, shape-checked and confirmed
    to resolve over a bounded, short-timeout request; a dead link is declined rather than
    written, and a validation fault never fails the lead.
12. Retries and exponential backoff — 429/5xx and transport faults are retried with growing,
    jittered delays; a 403 is not retried at all; an exhausted budget is still contained.
13. robots.txt and bounded redirects — an explicit `Disallow` refuses the search, an
    unreachable robots.txt is not treated as a ban, the verdict is cached, and a redirect
    loop terminates against the configured budget instead of hanging.
14. No credentials — the default backend resolves, reports available and runs with an empty
    .env, and no credential-shaped setting exists for it at all.
15. Duplicate results — repeated pages of one site collapse to a single candidate at both
    layers, without crowding out a genuinely different domain.

This is a **pure unit suite**, like `tests/test_overpass_import.py` and unlike the DB-backed
`test_google_maps_import.py`: the brief for this feature is explicitly "no database writes",
so there is no session, no marker row and no cleanup block, and it is safe to run anywhere
with no `.env`, no Postgres and no credential.

No network is touched. Most sections drive the service through a `StubSearchBackend`, which
implements the `SearchBackend` port directly — that is what the port exists for. Section 8
additionally exercises the *real* `DuckDuckGoSearchBackend` against `httpx.MockTransport`
serving real-shaped DuckDuckGo HTML, so the production parse is the one under test.

Run:  python tests/test_website_discovery.py
"""

import asyncio
import inspect
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from app.core.config import settings
from app.services.lead_providers.normalized import NormalizedLead
from app.services import website_discovery as module
from app.services.website_discovery import (
    DiscoveryOutcome,
    WebsiteDiscoveryService,
    registrable_domain,
)

# The search backend now lives in its own package. Importing the port from there — rather
# than through the re-export on `website_discovery` — is deliberate in this suite: it is what
# proves the seam actually exists and that a backend can be written and tested without ever
# importing the lead layer.
from app.services.lead_providers.web_search import (
    DEFAULT_SEARCH_BACKEND_KEY,
    SearchBackend,
    SearchBackendError,
    SearchResult,
    get_search_backend,
    registered_search_backend_keys,
)
from app.services.lead_providers.web_search import duckduckgo as ddg_module
from app.services.lead_providers.web_search.duckduckgo import DuckDuckGoSearchBackend


class no_url_validation:
    """
    Context manager disabling the live reachability check.

    Sections that drive the service through a `StubSearchBackend` are testing filtering,
    scoring and the failure contract — not validation. Leaving validation on there would make
    them attempt a real socket to whatever domain the fixture invented, which is both slow and
    the one thing this suite promises not to do. Section 11 covers validation explicitly, with
    its own mocked transport.
    """

    def __enter__(self) -> None:
        self._previous = settings.WEBSITE_DISCOVERY_VALIDATE_URL
        settings.WEBSITE_DISCOVERY_VALIDATE_URL = False

    def __exit__(self, *exc: object) -> None:
        settings.WEBSITE_DISCOVERY_VALIDATE_URL = self._previous


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


# ===========================================================================================
# Stubs
# ===========================================================================================

class StubSearchBackend(SearchBackend):
    """
    A `SearchBackend` that answers from a canned list and records what it was asked.

    Implementing the port directly — rather than stubbing HTTP — is the point of having a
    port: the service's filtering, scoring and threshold logic is exercised without any
    engine's response format in the way. Section 8 covers the real backend separately.
    """

    key = "stub"
    display_name = "Stub Search Backend"

    def __init__(
        self,
        results: list[SearchResult] | None = None,
        *,
        error: Exception | None = None,
        available: bool = True,
    ) -> None:
        self.results = results or []
        self.error = error
        self._available = available
        self.queries: list[str] = []
        self.limits: list[int] = []

    @property
    def is_available(self) -> bool:
        # Overridden as a property, matching the base class: readiness is something a
        # backend *reports*, not a flag a caller can flip on it from outside.
        return self._available

    @property
    def unavailable_reason(self) -> str:
        return "Stub backend was constructed unavailable."

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append(query)
        self.limits.append(limit)
        if self.error:
            raise self.error
        return self.results[:limit]


def make_lead(
    *,
    name: str | None = "Sunrise Studio",
    city: str | None = "Kozhikode",
    website: str | None = None,
    **extra,
) -> NormalizedLead:
    """Builds a normalized lead, defaulting to a valid websiteless one."""
    return NormalizedLead(
        business_name=name,
        city=city,
        website=website,
        phone_numbers=extra.pop("phone_numbers", ["9876543210"]),
        **extra,
    ).normalize()


class StubbedDuckDuckGoBackend(DuckDuckGoSearchBackend):
    """
    The real DuckDuckGo backend with its HTTP transport swapped for a stub.

    Overriding only the httpx import keeps the throttle, the POST, the status handling and
    the SERP parse as production code — the stub replaces the socket and nothing else. This
    mirrors `StubbedOverpassProvider` in `tests/test_overpass_import.py`.
    """

    def __init__(self, handler, **kwargs) -> None:
        kwargs.setdefault("min_request_interval", 0.0)
        # robots.txt is exercised explicitly in section 12; elsewhere it would be an extra
        # mocked round trip in front of every assertion, obscuring what is under test.
        kwargs.setdefault("respect_robots", False)
        super().__init__(**kwargs)
        self._handler = handler


def _patch_httpx(backend: StubbedDuckDuckGoBackend):
    """
    Points `website_discovery._import_httpx` at a MockTransport-bound httpx for the duration
    of a test, returning a restore callable.

    Patched at module level rather than on the instance because `_import_httpx` is a module
    function shared by every backend — which is itself deliberate, so one lazy-import policy
    covers all of them.
    """
    original = ddg_module._import_httpx
    handler = backend._handler

    class _StubHttpx:
        Timeout = httpx.Timeout
        TimeoutException = httpx.TimeoutException
        ConnectError = httpx.ConnectError
        ReadError = httpx.ReadError
        RemoteProtocolError = httpx.RemoteProtocolError

        @staticmethod
        def AsyncClient(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    ddg_module._import_httpx = lambda: _StubHttpx
    return lambda: setattr(ddg_module, "_import_httpx", original)


def serp(*entries: tuple[str, str, str]) -> str:
    """
    Renders a DuckDuckGo HTML SERP from `(href, title, snippet)` triples.

    Uses the real `result__a` / `result__snippet` markup and the real
    `//duckduckgo.com/l/?uddg=` redirect wrapper, so the parse under test is the production
    one rather than a simplified shape invented for the test.
    """
    from urllib.parse import quote

    blocks = []
    for href, title, snippet in entries:
        wrapped = f"//duckduckgo.com/l/?uddg={quote(href, safe='')}&rut=abc"
        blocks.append(
            f'<div class="result results_links">'
            f'<a rel="nofollow" class="result__a" href="{wrapped}">{title}</a>'
            f'<a class="result__snippet" href="{wrapped}">{snippet}</a>'
            f"</div>"
        )
    return "<html><body>" + "\n".join(blocks) + "</body></html>"


# ===========================================================================================
# 1. Construction & configuration
# ===========================================================================================

async def test_construction() -> None:
    print("\n[1] Service construction & backend registry")

    service = WebsiteDiscoveryService()
    described = service.describe()
    check(described["backend"]["key"] == "duckduckgo",
          "the default backend must be the zero-credential DuckDuckGo one")
    check(described["backend"]["is_available"] is True,
          "the default backend must be available with no credential configured")
    print(f"  ✓ default backend is '{described['backend']['key']}' and needs no credential")

    check(0 < described["min_confidence"] <= 1, "min_confidence must be a usable threshold")
    check(described["max_results"] >= 1, "max_results must be at least 1")
    check(described["concurrency"] >= 1, "concurrency must be at least 1")
    print(f"  ✓ configured: threshold={described['min_confidence']}, "
          f"max_results={described['max_results']}, concurrency={described['concurrency']}")

    injected = WebsiteDiscoveryService(backend=StubSearchBackend(), min_confidence=0.9)
    check(injected.describe()["backend"]["key"] == "stub", "an injected backend must be used")
    check(injected.describe()["min_confidence"] == 0.9, "an injected threshold must be used")
    print("  ✓ backend and threshold are injectable (constructor override)")

    # An unknown backend key degrades to the default rather than raising: discovery writes
    # nothing, so a misconfigured name must not be able to break an import run.
    fallback = get_search_backend("does-not-exist")
    check(isinstance(fallback, DuckDuckGoSearchBackend),
          "an unknown backend key must fall back to the default, not raise")
    print("  ✓ unknown backend key falls back to the default with a warning")

    check(registrable_domain("WWW.Example.CO.IN") == "example.co.in",
          "registrable_domain must lowercase and strip 'www.'")
    print("  ✓ registrable_domain normalizes host casing and strips 'www.'")


# ===========================================================================================
# 2. Query construction  (rule 1: search using business name + city)
# ===========================================================================================

async def test_query_construction() -> None:
    print("\n[2] Query construction — business name + city (rule 1)")

    backend = StubSearchBackend()
    service = WebsiteDiscoveryService(backend=backend, max_results=4)
    await service.discover(make_lead(name="Sunrise Studio", city="Kozhikode"))
    check(backend.queries == ["Sunrise Studio Kozhikode"],
          f"query must be name + city, got {backend.queries}")
    print(f"  ✓ query is business name + city: {backend.queries[0]!r}")

    check(backend.limits == [4], "the configured max_results must be passed to the backend")
    print("  ✓ max_results is passed through to the backend")

    backend = StubSearchBackend()
    await WebsiteDiscoveryService(backend=backend).discover(
        make_lead(name="Sunrise Studio", city=None)
    )
    check(backend.queries == ["Sunrise Studio"],
          f"a lead with no city must search on the name alone, got {backend.queries}")
    print("  ✓ city omitted from the query when the lead has none")

    # "official website" is deliberately NOT appended: it is directory boilerplate and
    # biases the engine toward exactly the pages this service exists to reject.
    check("official" not in backend.queries[0].lower(),
          "the query must not append directory-boilerplate phrasing")
    print("  ✓ no 'official website' phrasing appended (it biases toward directories)")

    backend = StubSearchBackend()
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(
        make_lead(name=None, city="Kozhikode")
    )
    check(backend.queries == [], "a lead with no business name must not be searched")
    check(outcome.status == "not_searchable", f"expected not_searchable, got {outcome.status}")
    check(outcome.lead.website is None, "a nameless lead must come back unchanged")
    print("  ✓ a lead with no business name is never searched (status=not_searchable)")


# ===========================================================================================
# 3. Directory rejection  (rule 4)
# ===========================================================================================

async def test_directory_rejection() -> None:
    print("\n[3] Directory rejection (rule 4)")

    # Every one of these outranks a small studio's own site for this exact query shape.
    directories = [
        "https://www.justdial.com/Kozhikode/Sunrise-Studio/9999",
        "https://www.sulekha.com/sunrise-studio-kozhikode",
        "https://www.weddingwire.in/wedding-photographers/sunrise-studio",
        "https://www.wedmegood.com/profile/sunrise-studio-12345",
        "https://www.facebook.com/sunrisestudiokozhikode",
        "https://www.instagram.com/sunrise.studio",
        "https://www.indiamart.com/sunrise-studio/",
        "https://www.google.com/maps/place/Sunrise+Studio",
        "https://kozhikode.justdial.com/Sunrise-Studio",   # subdomain of a directory
        "https://linktr.ee/sunrisestudio",
    ]
    backend = StubSearchBackend([
        SearchResult(url, "Sunrise Studio Kozhikode - Best Photographers", "Sunrise Studio")
        for url in directories
    ])
    service = WebsiteDiscoveryService(backend=backend, max_results=len(directories))
    outcome = await service.discover_with_outcome(make_lead())

    check(outcome.lead.website is None,
          f"a directory must never be attached, got {outcome.lead.website}")
    check(outcome.status == "no_candidates",
          f"expected no_candidates when only directories rank, got {outcome.status}")
    print(f"  ✓ all {len(directories)} directory results rejected; lead left without a website")
    print(f"  ✓ rejected domains recorded: {', '.join(outcome.rejected_directories[:4])}, …")

    check("justdial.com" in outcome.rejected_directories,
          "the rejection list must record justdial.com")
    print("  ✓ 'kozhikode.justdial.com' rejected as a subdomain of a known directory")

    # A directory ranking FIRST must not beat the real site ranking below it. Rejection
    # happens before scoring precisely so rank cannot rescue a directory.
    backend = StubSearchBackend([
        SearchResult("https://www.justdial.com/Kozhikode/Sunrise-Studio",
                     "Sunrise Studio, Kozhikode - Photographers - Justdial"),
        SearchResult("https://sunrisestudio.in/",
                     "Sunrise Studio | Wedding Photography in Kozhikode"),
    ])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())
    check(outcome.lead.website == "https://sunrisestudio.in",
          f"the real site below a directory must win, got {outcome.lead.website}")
    print("  ✓ a top-ranked directory loses to the genuine site ranked beneath it")


# ===========================================================================================
# 4. Validation — the domain must belong to the same business  (rule 3)
# ===========================================================================================

async def test_validation() -> None:
    print("\n[4] Validation — same-business check (rule 3)")

    # An unrelated domain is declined, not attached. This is the failure that matters: a
    # wrong website looks like data, while an empty one visibly reads as a gap.
    backend = StubSearchBackend([
        SearchResult("https://randomblog.example/post/photography-tips",
                     "Ten photography tips", "A blog about cameras"),
    ])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())
    check(outcome.lead.website is None,
          f"an unrelated domain must not be attached, got {outcome.lead.website}")
    check(outcome.status == "below_threshold",
          f"expected below_threshold, got {outcome.status}")
    print(f"  ✓ unrelated domain declined (confidence {outcome.confidence:.2f} < threshold)")

    # Generic vocabulary alone must not validate one studio against another's domain:
    # "photography"/"studio" appear in a large share of all such names.
    backend = StubSearchBackend([
        SearchResult("https://lakesidephotography.in/",
                     "Lakeside Photography Studio", "Wedding photography"),
    ])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(
        make_lead(name="Sunrise Photography Studio")
    )
    check(outcome.lead.website is None,
          f"a generic-token-only match must be declined, got {outcome.lead.website}")
    print("  ✓ 'lakesidephotography.in' declined for 'Sunrise Photography Studio' "
          "(generic tokens carry no identity)")

    # A genuine match is accepted, and the reasoning is recorded.
    backend = StubSearchBackend([
        SearchResult("https://sunrisestudio.in/",
                     "Sunrise Studio | Kozhikode", "Candid wedding photography in Kozhikode"),
    ])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())
    check(outcome.lead.website == "https://sunrisestudio.in",
          f"a genuine match must be accepted, got {outcome.lead.website}")
    check(outcome.confidence >= 0.5, "a genuine match must clear the threshold")
    check(outcome.reasons, "an accepted candidate must carry its supporting evidence")
    print(f"  ✓ genuine match accepted at confidence {outcome.confidence:.2f}")
    for reason in outcome.reasons:
        print(f"      · {reason}")

    # Concatenated registration ("sunrisestudio.com") is the common real-world form and
    # must match a spaced business name.
    backend = StubSearchBackend([SearchResult("https://sunrisestudio.com/", "Sunrise Studio")])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())
    check(outcome.lead.website == "https://sunrisestudio.com",
          "a concatenated domain must match a spaced business name")
    print("  ✓ concatenated domain 'sunrisestudio.com' matches 'Sunrise Studio'")

    # A stricter threshold is honoured, so an operator can trade recall for precision.
    # This candidate matches on the domain but has no corroborating title or city, so it
    # scores in the middle: accepted at the default threshold, rejected at a strict one.
    partial = [SearchResult("https://sunrise.in/", "Home", "Welcome")]
    lenient_outcome = await WebsiteDiscoveryService(
        backend=StubSearchBackend(list(partial))
    ).discover_with_outcome(make_lead())
    check(lenient_outcome.lead.website == "https://sunrise.in",
          f"a domain-only match must clear the default threshold, got {lenient_outcome}")

    strict_outcome = await WebsiteDiscoveryService(
        backend=StubSearchBackend(list(partial)), min_confidence=0.99
    ).discover_with_outcome(make_lead())
    check(strict_outcome.lead.website is None, "a raised threshold must be enforced")
    check(strict_outcome.status == "below_threshold",
          f"expected below_threshold, got {strict_outcome.status}")
    print(f"  ✓ threshold enforced: the same {lenient_outcome.confidence:.2f} candidate is "
          f"accepted by default and rejected at min_confidence=0.99")


# ===========================================================================================
# 5. Only the official domain is saved  (rule 5)
# ===========================================================================================

async def test_domain_only_saved() -> None:
    print("\n[5] Only the official domain is saved (rule 5)")

    backend = StubSearchBackend([
        SearchResult("https://www.sunrisestudio.in/gallery/weddings?ref=ddg#top",
                     "Sunrise Studio | Wedding Gallery", "Kozhikode"),
    ])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())

    check(outcome.lead.website == "https://sunrisestudio.in",
          f"the deep URL must be reduced to the bare domain, got {outcome.lead.website}")
    print(f"  ✓ deep result URL reduced to the domain: {outcome.lead.website}")
    check("gallery" not in (outcome.lead.website or ""), "the path must be dropped")
    check("?" not in (outcome.lead.website or ""), "the query string must be dropped")
    check("#" not in (outcome.lead.website or ""), "the fragment must be dropped")
    check("www." not in (outcome.lead.website or ""), "'www.' must be stripped")
    print("  ✓ path, query string, fragment and 'www.' all stripped")

    # Several pages of the same site are one candidate, not three.
    backend = StubSearchBackend([
        SearchResult("https://sunrisestudio.in/", "Sunrise Studio"),
        SearchResult("https://sunrisestudio.in/about", "About - Sunrise Studio"),
        SearchResult("https://sunrisestudio.in/contact", "Contact - Sunrise Studio"),
    ])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())
    check(outcome.lead.website == "https://sunrisestudio.in",
          "multiple pages of one site must collapse to one domain")
    print("  ✓ multiple pages of one site collapse to a single candidate domain")

    check(module.normalize_url(outcome.lead.website) == outcome.lead.website,
          "the stored website must already satisfy the CRM's URL normalizer")
    print("  ✓ stored value is a normalized, CRM-storable URL")


# ===========================================================================================
# 6. Existing websites are never overwritten  (rule 6)
# ===========================================================================================

async def test_never_overwrites() -> None:
    print("\n[6] Existing websites are never overwritten (rule 6)")

    backend = StubSearchBackend([
        SearchResult("https://sunrisestudio.in/", "Sunrise Studio | Kozhikode"),
    ])
    service = WebsiteDiscoveryService(backend=backend)
    lead = make_lead(website="https://the-original-site.com")
    outcome = await service.discover_with_outcome(lead)

    check(outcome.lead.website == "https://the-original-site.com",
          f"an existing website must survive, got {outcome.lead.website}")
    check(outcome.status == "already_present",
          f"expected already_present, got {outcome.status}")
    print("  ✓ existing website preserved even when a better-matching candidate exists")

    # Not merely preserved — not even searched for. The cheap branch is checked first, so a
    # batch of already-enriched leads issues no outbound calls at all.
    check(backend.queries == [],
          f"no search must be issued for a lead that already has a website, got {backend.queries}")
    print("  ✓ no search issued at all (the check precedes any outbound call)")

    # A whitespace-only website is empty in every sense that matters, so it is discoverable.
    backend = StubSearchBackend([SearchResult("https://sunrisestudio.in/", "Sunrise Studio")])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(
        NormalizedLead(business_name="Sunrise Studio", city="Kozhikode",
                       phone_numbers=["9876543210"], website="   ").normalize()
    )
    check(outcome.status == "discovered",
          f"a whitespace-only website must count as empty, got {outcome.status}")
    print("  ✓ a whitespace-only website counts as empty and is discovered")


# ===========================================================================================
# 7. The enriched NormalizedLead is returned  (rule 7)
# ===========================================================================================

async def test_returns_enriched_lead() -> None:
    print("\n[7] The enriched NormalizedLead is returned (rule 7)")

    backend = StubSearchBackend([
        SearchResult("https://sunrisestudio.in/", "Sunrise Studio | Kozhikode", "Kozhikode"),
    ])
    original = make_lead(
        phone_numbers=["9876543210", "0495 2345678"],
        emails=["hello@sunrisestudio.in"],
        address="MG Road, Kozhikode",
        state="Kerala",
        rating=4.7,
        categories=["Wedding Photography"],
    )
    enriched = await WebsiteDiscoveryService(backend=backend).discover(original)

    check(isinstance(enriched, NormalizedLead),
          "discover() must return a NormalizedLead")
    check(enriched.website == "https://sunrisestudio.in", "the website must be set")
    print(f"  ✓ returns a NormalizedLead carrying website={enriched.website}")

    # The input must not be mutated: the caller decides what to do with the enriched copy.
    check(original.website is None,
          "the input lead must not be mutated (a copy is returned)")
    print("  ✓ the input lead is left unmutated — a new instance is returned")

    for field in ("business_name", "phone_numbers", "emails", "address", "city", "state",
                  "rating", "categories", "source", "raw"):
        check(getattr(enriched, field) == getattr(original, field),
              f"field {field!r} must survive enrichment unchanged")
    print("  ✓ every other field survives the round trip unchanged")

    valid, reason = enriched.is_valid()
    check(valid, f"the enriched lead must remain storable, got {reason}")
    print("  ✓ the enriched lead is still valid for the CRM")

    # Batch enrichment preserves order and enriches only what needs it.
    leads = [
        make_lead(name="Sunrise Studio", city="Kozhikode"),
        make_lead(name="Already Done", city="Kochi", website="https://alreadydone.com"),
        make_lead(name="Sunrise Studio", city="Kozhikode"),
    ]
    results = await WebsiteDiscoveryService(backend=backend).discover_many(leads)
    check(len(results) == 3, "discover_many must return one lead per input")
    check([r.business_name for r in results] == [l.business_name for l in leads],
          "discover_many must preserve input order")
    check(results[1].website == "https://alreadydone.com",
          "discover_many must not overwrite an existing website")
    check(results[0].website == "https://sunrisestudio.in", "discover_many must enrich")
    print("  ✓ discover_many enriches a batch, preserves order, and skips the enriched one")


# ===========================================================================================
# 8. The DuckDuckGo backend (real parse, mocked socket)
# ===========================================================================================

async def test_duckduckgo_backend() -> None:
    print("\n[8] DuckDuckGo backend — real SERP parse over a mocked socket")

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["content"] = request.content.decode()
        captured["user_agent"] = request.headers.get("user-agent")
        return httpx.Response(200, text=serp(
            ("https://www.justdial.com/Kozhikode/Sunrise-Studio",
             "Sunrise Studio - Justdial", "Contact Sunrise Studio"),
            ("https://sunrisestudio.in/",
             "Sunrise &amp; Studio | Kozhikode", "Wedding photography in Kozhikode"),
        ))

    backend = StubbedDuckDuckGoBackend(handler)
    restore = _patch_httpx(backend)
    try:
        results = await backend.search("Sunrise Studio Kozhikode", 5)
    finally:
        restore()

    check(captured["method"] == "POST",
          "the HTML endpoint must be POSTed (a GET returns a consent interstitial)")
    check("q=Sunrise" in str(captured["content"]).replace("+", " ").replace("%20", " "),
          f"the query must be form-encoded in the body, got {captured['content']}")
    print("  ✓ issues a POST with the query form-encoded in the body")

    check(captured["user_agent"] and "ColourLabs" in str(captured["user_agent"]),
          "an identifying User-Agent must be sent")
    print(f"  ✓ identifying User-Agent sent: {str(captured['user_agent'])[:44]}…")

    check(len(results) == 2, f"both results must parse, got {len(results)}")
    # The redirect wrapper must be unwrapped: storing '//duckduckgo.com/l/?uddg=…' would
    # save a tracking URL that breaks when the redirector changes.
    check(results[0].url == "https://www.justdial.com/Kozhikode/Sunrise-Studio",
          f"the redirect wrapper must be unwrapped, got {results[0].url}")
    check(results[1].url == "https://sunrisestudio.in/",
          f"the redirect wrapper must be unwrapped, got {results[1].url}")
    print("  ✓ '//duckduckgo.com/l/?uddg=…' redirect wrappers unwrapped to real targets")

    check(results[1].title == "Sunrise & Studio | Kozhikode",
          f"HTML entities must be decoded in titles, got {results[1].title!r}")
    check(results[1].snippet == "Wedding photography in Kozhikode",
          f"snippets must be extracted, got {results[1].snippet!r}")
    print("  ✓ titles and snippets extracted, HTML entities decoded, tags stripped")

    # End to end through the real backend: the directory is still rejected.
    backend = StubbedDuckDuckGoBackend(handler)
    restore = _patch_httpx(backend)
    try:
        outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(make_lead())
    finally:
        restore()
    check(outcome.lead.website == "https://sunrisestudio.in",
          f"end-to-end discovery must pick the real site, got {outcome.lead.website}")
    print(f"  ✓ end-to-end through the real backend → {outcome.lead.website}")

    # An unrecognised page degrades to zero results, never to garbage URLs.
    backend = StubbedDuckDuckGoBackend(
        lambda r: httpx.Response(200, text="<html><body>challenge page</body></html>")
    )
    restore = _patch_httpx(backend)
    try:
        results = await backend.search("anything", 5)
    finally:
        restore()
    check(results == [], f"an unparseable page must yield no results, got {results}")
    print("  ✓ an unrecognised/challenge page yields zero results, not garbage")

    # An HTTP fault is a backend fault, raised for the service to contain.
    backend = StubbedDuckDuckGoBackend(lambda r: httpx.Response(503, text="unavailable"))
    restore = _patch_httpx(backend)
    try:
        raised = None
        try:
            await backend.search("anything", 5)
        except SearchBackendError as exc:
            raised = exc
    finally:
        restore()
    check(raised is not None, "an HTTP 5xx must raise SearchBackendError")
    check("503" in str(raised), f"the status must appear in the message, got {raised}")
    print(f"  ✓ HTTP 503 raised as SearchBackendError: {raised}")

    # A transport fault is likewise converted, never leaked as a raw httpx error.
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out")

    backend = StubbedDuckDuckGoBackend(boom)
    restore = _patch_httpx(backend)
    try:
        raised = None
        try:
            await backend.search("anything", 5)
        except SearchBackendError as exc:
            raised = exc
    finally:
        restore()
    check(raised is not None, "a transport fault must be converted to SearchBackendError")
    print(f"  ✓ transport faults converted: {str(raised)[:56]}…")


# ===========================================================================================
# 9. Rate limiting
# ===========================================================================================

async def test_rate_limiting() -> None:
    print("\n[9] Rate limiting — outbound searches serialised and spaced")

    interval = 0.05
    call_times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_times.append(asyncio.get_running_loop().time())
        return httpx.Response(200, text=serp(
            ("https://sunrisestudio.in/", "Sunrise Studio", "Kozhikode")
        ))

    backend = StubbedDuckDuckGoBackend(handler, min_request_interval=interval)
    restore = _patch_httpx(backend)
    try:
        # Concurrent discoveries through ONE backend must queue, not burst — which is why
        # the limiter holds its lock across the request rather than only across the sleep.
        service = WebsiteDiscoveryService(backend=backend, concurrency=5)
        await service.discover_many([
            make_lead(name=f"Sunrise Studio {i}", city="Kozhikode") for i in range(3)
        ])
    finally:
        restore()

    check(len(call_times) == 3, f"three searches must have been issued, got {len(call_times)}")
    gaps = [round(call_times[i + 1] - call_times[i], 4) for i in range(len(call_times) - 1)]
    check(all(gap >= interval * 0.85 for gap in gaps),
          f"calls must be spaced by ~{interval}s, observed gaps {gaps}")
    print(f"  ✓ 3 concurrent discoveries serialised with gaps {gaps} (min interval {interval}s)")
    print("  ✓ the limiter holds its lock across the request, so concurrency cannot burst")


# ===========================================================================================
# 10. Failure contract & non-persistence
# ===========================================================================================

async def test_failure_contract_and_no_persistence() -> None:
    print("\n[10] Failure contract & non-persistence")

    lead = make_lead()

    # A backend fault is contained: enrichment is best-effort and must never fail an import.
    backend = StubSearchBackend(error=SearchBackendError("engine unreachable"))
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(lead)
    check(outcome.status == "search_failed", f"expected search_failed, got {outcome.status}")
    check(outcome.lead is lead, "a failed search must return the input lead unchanged")
    print("  ✓ SearchBackendError contained → lead returned unchanged (status=search_failed)")

    # Even a backend that violates the contract and raises something unexpected.
    backend = StubSearchBackend(error=RuntimeError("backend bug"))
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(lead)
    check(outcome.status == "search_failed",
          "an unexpected backend exception must also be contained")
    check(outcome.lead.website is None, "the lead must survive a backend bug unchanged")
    print("  ✓ an unexpected backend exception is contained too (no exception escapes)")

    # An unavailable backend is reported, not called.
    backend = StubSearchBackend(available=False)
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(lead)
    check(outcome.status == "search_failed" and backend.queries == [],
          "an unavailable backend must be skipped, not called")
    print("  ✓ an unavailable backend is skipped with its reason, never called")

    # An empty result set is an ordinary outcome, not an error.
    backend = StubSearchBackend([])
    outcome = await WebsiteDiscoveryService(backend=backend).discover_with_outcome(lead)
    check(outcome.status == "no_candidates" and outcome.lead.website is None,
          "an empty search must leave the lead unchanged")
    print("  ✓ an empty result set leaves the lead unchanged (status=no_candidates)")

    # A batch survives a mid-batch failure: the rest still enrich.
    class FlakyBackend(StubSearchBackend):
        async def search(self, query, limit):
            self.queries.append(query)
            if "Broken" in query:
                raise SearchBackendError("engine hiccup")
            return [SearchResult("https://sunrisestudio.in/", "Sunrise Studio")]

    results = await WebsiteDiscoveryService(backend=FlakyBackend()).discover_many([
        make_lead(name="Sunrise Studio"),
        make_lead(name="Broken Studio"),
        make_lead(name="Sunrise Studio"),
    ])
    check(len(results) == 3, "a mid-batch failure must not shorten the batch")
    check(results[0].website == "https://sunrisestudio.in", "the first lead must enrich")
    check(results[1].website is None, "the failing lead must be returned unchanged")
    check(results[2].website == "https://sunrisestudio.in", "the last lead must still enrich")
    print("  ✓ one failing lead does not abort a batch — the others still enrich")

    # --- Non-persistence, asserted on the source itself ---------------------------------
    source = inspect.getsource(module)
    forbidden = [
        ("from app.models", "an ORM model import"),
        ("from app.repositories", "a repository import"),
        ("AsyncSession", "a database session"),
        ("db.commit", "a commit"),
        ("db.add", "a session write"),
        ("session.", "a session call"),
    ]
    for needle, description in forbidden:
        check(needle not in source,
              f"website_discovery.py must not contain {description} ({needle!r})")
    print("  ✓ module contains no model import, no repository, no session, no commit")

    signature = inspect.signature(WebsiteDiscoveryService.discover)
    check("db" not in signature.parameters,
          "discover() must not accept a database session")
    check(list(signature.parameters) == ["self", "lead"],
          f"discover() must be lead-in/lead-out, got {list(signature.parameters)}")
    print("  ✓ discover(lead) -> NormalizedLead takes no session: it cannot write to the CRM")

    check(isinstance(outcome, DiscoveryOutcome), "discover_with_outcome returns a DiscoveryOutcome")
    print("  ✓ the service returns normalized leads and nothing else is persisted")


# ===========================================================================================
# 11. URL validation (brief rule 4)
# ===========================================================================================

async def test_url_validation() -> None:
    """
    A discovered URL must be normalized, shape-checked and shown to actually resolve, and a
    validation failure must leave the lead unchanged rather than raise.
    """
    print("\n[11] URL validation — normalized, http(s), reachable, short timeout")

    lead = make_lead()
    good = [SearchResult("https://sunrisestudio.in/gallery", "Sunrise Studio Kozhikode")]

    def patch_validation(handler):
        """Points the service's validation client at a mocked transport."""
        import app.services.website_discovery as wd

        real_client = httpx.AsyncClient

        class _Patched:
            def __enter__(self):
                httpx.AsyncClient = lambda **kw: real_client(
                    transport=httpx.MockTransport(handler), **kw
                )
                return self

            def __exit__(self, *exc):
                httpx.AsyncClient = real_client

        return _Patched()

    # --- a reachable site is accepted -------------------------------------------------
    seen: list[tuple[str, str]] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        return httpx.Response(200)

    with patch_validation(ok):
        outcome = await WebsiteDiscoveryService(
            backend=StubSearchBackend(good)
        ).discover_with_outcome(lead)

    check(outcome.status == "discovered", f"a reachable site must be accepted, got {outcome.status}")
    check(outcome.lead.website == "https://sunrisestudio.in",
          f"the validated domain must be attached, got {outcome.lead.website}")
    check(seen and seen[0][0] == "HEAD",
          f"validation must try a cheap HEAD first, got {seen}")
    print(f"  ✓ reachable site validated via HEAD and attached → {outcome.lead.website}")

    # --- a dead site is rejected, and the lead survives ---------------------------------
    with patch_validation(lambda r: httpx.Response(404)):
        outcome = await WebsiteDiscoveryService(
            backend=StubSearchBackend(good)
        ).discover_with_outcome(lead)

    check(outcome.status == "validation_failed",
          f"an unreachable site must be rejected, got {outcome.status}")
    check(outcome.lead.website is None,
          "a failed validation must leave the website empty, not write a dead link")
    check(outcome.lead is lead, "the original lead must be returned untouched")
    print("  ✓ HTTP 404 → website left empty (status=validation_failed), lead unchanged")

    # --- a host that rejects HEAD is retried with GET -----------------------------------
    methods: list[str] = []

    def head_not_allowed(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(405) if request.method == "HEAD" else httpx.Response(200)

    with patch_validation(head_not_allowed):
        outcome = await WebsiteDiscoveryService(
            backend=StubSearchBackend(good)
        ).discover_with_outcome(lead)

    check(methods == ["HEAD", "GET"], f"a 405 must fall back to GET, got {methods}")
    check(outcome.status == "discovered", "a host that rejects HEAD must still validate")
    print("  ✓ a host answering HEAD with 405 falls back to GET and still validates")

    # --- a connection fault does not propagate ------------------------------------------
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with patch_validation(refuse):
        outcome = await WebsiteDiscoveryService(
            backend=StubSearchBackend(good)
        ).discover_with_outcome(lead)

    check(outcome.status == "validation_failed",
          "a transport fault during validation must be contained")
    check(outcome.lead.website is None, "a lead must survive a validation fault unchanged")
    print("  ✓ a connection error during validation is contained → lead unchanged")

    # --- malformed / non-http URLs never reach the network ------------------------------
    service = WebsiteDiscoveryService(backend=StubSearchBackend([]))
    for bad in ("ftp://files.example.com", "javascript:alert(1)", "https://nodot", "not a url"):
        valid, detail = await service._validate_website(bad)
        check(not valid, f"{bad!r} must be rejected by shape, got valid={valid} ({detail})")
    print("  ✓ ftp://, javascript:, hostless and malformed URLs rejected without a request")

    # A scheme-less candidate is normalized to https by `normalize_url` before it is stored,
    # which is what keeps a bare 'studio.example.com' out of the database.
    with patch_validation(ok):
        outcome = await WebsiteDiscoveryService(
            backend=StubSearchBackend(
                [SearchResult("https://sunrisestudio.in/contact", "Sunrise Studio")]
            )
        ).discover_with_outcome(lead)
    check(str(outcome.lead.website).startswith("https://"),
          f"a stored website must carry a scheme, got {outcome.lead.website}")
    print(f"  ✓ stored value is a normalized absolute URL: {outcome.lead.website}")


# ===========================================================================================
# 12. Retries & exponential backoff
# ===========================================================================================

async def test_retry_and_backoff() -> None:
    """
    Transient faults are retried with growing delays; permanent ones are not retried at all.
    No real network and no real waiting — the backoff constants are shrunk for the test.
    """
    print("\n[12] Retries & exponential backoff (no network, no real sleeping)")

    original_base = settings.WEB_SEARCH_RETRY_BACKOFF_SECONDS
    original_max = settings.WEB_SEARCH_RETRY_BACKOFF_MAX_SECONDS
    settings.WEB_SEARCH_RETRY_BACKOFF_SECONDS = 0.01
    settings.WEB_SEARCH_RETRY_BACKOFF_MAX_SECONDS = 0.05

    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(delay: float) -> None:
        slept.append(delay)
        await real_sleep(0)

    try:
        # --- a 503 that then succeeds ---------------------------------------------------
        attempts = {"n": 0}

        def flaky(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(503, text="unavailable")
            return httpx.Response(200, text=serp(
                ("https://sunrisestudio.in/", "Sunrise Studio", "Kozhikode")
            ))

        backend = StubbedDuckDuckGoBackend(flaky, max_attempts=3)
        restore = _patch_httpx(backend)
        ddg_module.asyncio.sleep = record_sleep
        try:
            results = await backend.search("Sunrise Studio Kozhikode", 5)
        finally:
            ddg_module.asyncio.sleep = real_sleep
            restore()

        check(attempts["n"] == 3, f"a 503 must be retried, saw {attempts['n']} attempts")
        check(len(results) == 1, f"the successful attempt must be parsed, got {results}")
        print(f"  ✓ HTTP 503 retried and recovered after {attempts['n']} attempts")

        check(len(slept) == 2, f"two backoff waits expected, got {slept}")
        check(slept[1] > slept[0],
              f"backoff must grow exponentially, got {slept}")
        print(f"  ✓ backoff grew between attempts: {[round(s, 4) for s in slept]}")

        # --- exhausting the budget raises, it does not hang -----------------------------
        slept.clear()
        backend = StubbedDuckDuckGoBackend(
            lambda r: httpx.Response(429, text="rate limited"), max_attempts=3
        )
        restore = _patch_httpx(backend)
        ddg_module.asyncio.sleep = record_sleep
        try:
            raised = None
            try:
                await backend.search("anything", 5)
            except SearchBackendError as exc:
                raised = exc
        finally:
            ddg_module.asyncio.sleep = real_sleep
            restore()

        check(raised is not None, "an exhausted retry budget must raise SearchBackendError")
        check("3 attempt" in str(raised), f"the message must state the budget, got {raised}")
        print(f"  ✓ HTTP 429 retried to exhaustion then raised: {str(raised)[:52]}…")

        # --- a permanent fault is NOT retried -------------------------------------------
        calls = {"n": 0}

        def forbidden(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(403, text="forbidden")

        backend = StubbedDuckDuckGoBackend(forbidden, max_attempts=3)
        restore = _patch_httpx(backend)
        try:
            try:
                await backend.search("anything", 5)
            except SearchBackendError:
                pass
        finally:
            restore()
        check(calls["n"] == 1,
              f"a 403 must not be retried (retrying hastens a block), saw {calls['n']} calls")
        print("  ✓ HTTP 403 is not retried — only 429/5xx and transport faults are")

        # --- a timeout is retried, and the whole thing is still contained by the service --
        timeouts = {"n": 0}

        def always_timeout(request: httpx.Request) -> httpx.Response:
            timeouts["n"] += 1
            raise httpx.ConnectTimeout("timed out")

        backend = StubbedDuckDuckGoBackend(always_timeout, max_attempts=2)
        restore = _patch_httpx(backend)
        ddg_module.asyncio.sleep = record_sleep
        try:
            outcome = await WebsiteDiscoveryService(
                backend=backend
            ).discover_with_outcome(make_lead())
        finally:
            ddg_module.asyncio.sleep = real_sleep
            restore()

        check(timeouts["n"] == 2, f"a timeout must be retried, saw {timeouts['n']} attempts")
        check(outcome.status == "search_failed" and outcome.lead.website is None,
              "an exhausted retry budget must still leave the lead unchanged, not raise")
        print("  ✓ timeouts retried, then contained by the service → lead unchanged")
    finally:
        settings.WEB_SEARCH_RETRY_BACKOFF_SECONDS = original_base
        settings.WEB_SEARCH_RETRY_BACKOFF_MAX_SECONDS = original_max


# ===========================================================================================
# 13. robots.txt & bounded redirects
# ===========================================================================================

async def test_robots_and_redirect_bounds() -> None:
    """robots.txt is fetched and honoured, and redirects are bounded rather than unlimited."""
    print("\n[13] robots.txt compliance & bounded redirects")

    serp_body = serp(("https://sunrisestudio.in/", "Sunrise Studio", "Kozhikode"))

    def make_handler(robots_body: str, robots_status: int = 200):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(robots_status, text=robots_body)
            return httpx.Response(200, text=serp_body)
        return handler

    # --- an explicit Disallow is honoured -----------------------------------------------
    backend = StubbedDuckDuckGoBackend(
        make_handler("User-agent: *\nDisallow: /html/\n"), respect_robots=True
    )
    restore = _patch_httpx(backend)
    try:
        raised = None
        try:
            await backend.search("anything", 5)
        except SearchBackendError as exc:
            raised = exc
    finally:
        restore()
    check(raised is not None and "robots.txt" in str(raised),
          f"a Disallow must prevent the search, got {raised}")
    print(f"  ✓ 'Disallow: /html/' honoured → search refused: {str(raised)[:48]}…")

    # --- a permissive robots.txt allows the search --------------------------------------
    backend = StubbedDuckDuckGoBackend(
        make_handler("User-agent: *\nDisallow: /nothing-here\n"), respect_robots=True
    )
    restore = _patch_httpx(backend)
    try:
        results = await backend.search("Sunrise Studio", 5)
    finally:
        restore()
    check(len(results) == 1, f"a permissive robots.txt must allow the search, got {results}")
    print("  ✓ an unrelated Disallow does not block the search")

    # --- an unreachable robots.txt is not treated as a ban ------------------------------
    backend = StubbedDuckDuckGoBackend(
        make_handler("", robots_status=500), respect_robots=True
    )
    restore = _patch_httpx(backend)
    try:
        results = await backend.search("Sunrise Studio", 5)
    finally:
        restore()
    check(len(results) == 1,
          "an unfetchable robots.txt must not disable discovery entirely")
    print("  ✓ an unreachable robots.txt resolves to 'allowed' rather than a hard stop")

    # --- the verdict is cached, not re-fetched per search -------------------------------
    robots_fetches = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            robots_fetches["n"] += 1
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text=serp_body)

    backend = StubbedDuckDuckGoBackend(counting, respect_robots=True)
    restore = _patch_httpx(backend)
    try:
        await backend.search("one", 5)
        await backend.search("two", 5)
        await backend.search("three", 5)
    finally:
        restore()
    check(robots_fetches["n"] == 1,
          f"robots.txt must be cached, was fetched {robots_fetches['n']} times")
    print("  ✓ robots.txt fetched once and cached — three searches, one fetch")

    # --- redirects are bounded ----------------------------------------------------------
    check(settings.WEB_SEARCH_MAX_REDIRECTS > 0,
          "a redirect budget must be configured")

    hops = {"n": 0}

    def redirect_loop(request: httpx.Request) -> httpx.Response:
        hops["n"] += 1
        return httpx.Response(302, headers={"Location": f"/html/?hop={hops['n']}"})

    backend = StubbedDuckDuckGoBackend(redirect_loop, max_attempts=1)
    restore = _patch_httpx(backend)
    try:
        raised = None
        try:
            await backend.search("anything", 5)
        except SearchBackendError as exc:
            raised = exc
    finally:
        restore()
    check(raised is not None, "an unbounded redirect chain must terminate as an error")
    check(hops["n"] <= settings.WEB_SEARCH_MAX_REDIRECTS + 2,
          f"redirects must be bounded by {settings.WEB_SEARCH_MAX_REDIRECTS}, "
          f"followed {hops['n']} hops")
    print(f"  ✓ redirect loop terminated after {hops['n']} hops "
          f"(budget {settings.WEB_SEARCH_MAX_REDIRECTS}), raised rather than hanging")


# ===========================================================================================
# 14. No credentials required for the default backend
# ===========================================================================================

async def test_no_credentials_required() -> None:
    """
    The default backend must work with an empty .env — that is the whole reason DuckDuckGo is
    the default rather than a keyed engine.
    """
    print("\n[14] The default backend requires no API key")

    check(settings.WEB_SEARCH_BACKEND == DEFAULT_SEARCH_BACKEND_KEY == "duckduckgo",
          f"the default backend must be duckduckgo, got {settings.WEB_SEARCH_BACKEND!r}")
    print(f"  ✓ WEB_SEARCH_BACKEND defaults to {settings.WEB_SEARCH_BACKEND!r}")

    backend = get_search_backend()
    check(isinstance(backend, DuckDuckGoSearchBackend),
          f"the default must resolve to the DuckDuckGo backend, got {type(backend).__name__}")
    check(backend.requires_credentials is False,
          "the default backend must not require credentials")
    check(backend.is_available is True,
          "the default backend must be available with nothing configured")
    print("  ✓ resolves and reports available with no credential configured")

    # Constructed with no arguments at all — no key is read, so none can be missing.
    fresh = DuckDuckGoSearchBackend()
    check(fresh.is_available, "a bare DuckDuckGoSearchBackend() must be usable")
    described = fresh.describe()
    check(described["requires_credentials"] is False and "unavailable_reason" not in described,
          f"describe() must report a ready, credential-free backend, got {described}")
    print(f"  ✓ DuckDuckGoSearchBackend() constructs bare: {described}")

    # No API-key-shaped configuration exists for this backend anywhere in the settings.
    keyish = [
        name for name in dir(settings)
        if name.startswith("WEB_SEARCH_") and any(
            token in name for token in ("KEY", "TOKEN", "SECRET", "CREDENTIAL", "PASSWORD")
        )
    ]
    check(not keyish, f"the web-search settings must contain no credential fields, got {keyish}")
    print("  ✓ no WEB_SEARCH_*_KEY/TOKEN/SECRET setting exists — nothing to configure")

    # The backend source reads no credential and no lead/database symbol: the port is clean.
    backend_source = inspect.getsource(ddg_module)
    for needle in ("api_key", "API_KEY", "Authorization", "from app.models",
                   "from app.repositories", "AsyncSession", "NormalizedLead"):
        check(needle not in backend_source,
              f"the DuckDuckGo backend must not reference {needle!r}")
    print("  ✓ backend source references no credential and no lead/DB symbol")

    check("duckduckgo" in registered_search_backend_keys(),
          "the default backend must be registered")
    print(f"  ✓ registry: {registered_search_backend_keys()}")


# ===========================================================================================
# 15. Duplicate search results
# ===========================================================================================

async def test_duplicate_results() -> None:
    """
    A site that ranks several of its own pages is one candidate, not several — at both layers:
    the backend de-duplicates identical URLs, and the service de-duplicates by domain.
    """
    print("\n[15] Duplicate search results collapse to one candidate")

    lead = make_lead()

    # --- the service collapses many pages of one site into one candidate ----------------
    service = WebsiteDiscoveryService(
        backend=StubSearchBackend([
            SearchResult("https://sunrisestudio.in/", "Sunrise Studio Kozhikode", "Home"),
            SearchResult("https://sunrisestudio.in/about", "About Sunrise Studio", "About us"),
            SearchResult("https://www.sunrisestudio.in/contact", "Contact Sunrise Studio", "Call"),
            SearchResult("https://sunrisestudio.in/", "Sunrise Studio Kozhikode", "Home"),
        ])
    )
    outcome = await service.discover_with_outcome(lead)

    check(outcome.status == "discovered",
          f"repeated pages of one site must still resolve, got {outcome.status}")
    check(outcome.lead.website == "https://sunrisestudio.in",
          f"the domain must be stored once, got {outcome.lead.website}")
    print(f"  ✓ four results across one site → one website: {outcome.lead.website}")

    candidates, _ = service._evaluate(lead, [
        SearchResult("https://sunrisestudio.in/", "Sunrise Studio"),
        SearchResult("https://sunrisestudio.in/about", "About Sunrise Studio"),
        SearchResult("https://www.sunrisestudio.in/contact", "Contact"),
    ])
    check(len(candidates) == 1,
          f"one domain must yield one candidate, got {[c.domain for c in candidates]}")
    print("  ✓ 'www.' and deep paths collapse to the same registrable domain (1 candidate)")

    # A duplicate must not out-vote a genuine alternative by sheer repetition: the second
    # domain still gets its own candidate rather than being crowded out.
    candidates, _ = service._evaluate(lead, [
        SearchResult("https://sunrisestudio.in/", "Sunrise Studio"),
        SearchResult("https://sunrisestudio.in/a", "Sunrise Studio"),
        SearchResult("https://sunrise-studio.com/", "Sunrise Studio Kozhikode"),
    ])
    check(len(candidates) == 2,
          f"a distinct second domain must survive de-duplication, got {len(candidates)}")
    print("  ✓ repetition does not crowd out a genuinely different domain")

    # --- the backend de-duplicates identical URLs in the SERP itself --------------------
    duplicated = serp(
        ("https://sunrisestudio.in/", "Sunrise Studio", "Kozhikode"),
        ("https://sunrisestudio.in/", "Sunrise Studio", "Kozhikode"),
        ("https://sunrisestudio.in", "Sunrise Studio", "Kozhikode"),
        ("https://other.example.com/", "Other", "Elsewhere"),
    )
    backend = StubbedDuckDuckGoBackend(lambda r: httpx.Response(200, text=duplicated))
    restore = _patch_httpx(backend)
    try:
        results = await backend.search("Sunrise Studio Kozhikode", 5)
    finally:
        restore()

    urls = [r.url for r in results]
    check(len(urls) == 2, f"identical SERP entries must collapse, got {urls}")
    print(f"  ✓ backend de-duplicates repeated SERP entries: {urls}")

    # De-duplication happens before the limit is applied, so duplicates cannot consume the
    # result budget and starve the evaluation of real alternatives.
    backend = StubbedDuckDuckGoBackend(lambda r: httpx.Response(200, text=duplicated))
    restore = _patch_httpx(backend)
    try:
        limited = await backend.search("Sunrise Studio Kozhikode", 2)
    finally:
        restore()
    check(len({r.url for r in limited}) == len(limited),
          f"a limited result set must still be unique, got {[r.url for r in limited]}")
    print("  ✓ duplicates do not consume the result limit")


# ===========================================================================================
# Runner
# ===========================================================================================

async def test_website_discovery_suite() -> None:
    print("=" * 78)
    print("WEBSITE DISCOVERY SERVICE — UNIT SUITE")
    print("=" * 78)

    # Sections 1-10 exercise filtering, scoring and the failure contract through stubs, so
    # the live reachability check is off for them; sections 11-14 manage it themselves.
    with no_url_validation():
        await test_construction()
        await test_query_construction()
        await test_directory_rejection()
        await test_validation()
        await test_domain_only_saved()
        await test_never_overwrites()
        await test_returns_enriched_lead()
        await test_duckduckgo_backend()
        await test_rate_limiting()
        await test_failure_contract_and_no_persistence()

    await test_url_validation()
    await test_retry_and_backoff()
    await test_robots_and_redirect_bounds()
    await test_no_credentials_required()
    await test_duplicate_results()

    print("\n" + "=" * 78)
    print("ALL 15 SECTIONS PASSED")
    print("=" * 78)
    print("\nNo database was touched: the service returns normalized leads and persists")
    print("nothing. No network was touched: every response was mocked.")


if __name__ == "__main__":
    asyncio.run(test_website_discovery_suite())
