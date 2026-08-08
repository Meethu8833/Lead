"""
app/services/website_discovery.py

This file implements `WebsiteDiscoveryService` — the enrichment step that finds the official
website of a normalized lead that arrived without one.

Where it sits
-------------
It is an Application-layer *service*, deliberately not a `LeadProvider`. A provider answers
"what businesses exist for this query"; this answers "given a business I already have, what
is its website". Those are different questions with different failure modes, and folding
discovery into an adapter would mean re-implementing it in every adapter that returns
websiteless records (Overpass and Instagram both do). Keeping it separate means it composes
with all of them and is testable on a hand-built `NormalizedLead` with no provider at all.

It is also **read-only with respect to the database**: it imports no model, no repository and
no session, takes `NormalizedLead` objects and returns `NormalizedLead` objects. Persistence
stays exactly where it already is, in `LeadImportService`. This is asserted structurally in
the test suite.

The pipeline, per lead
----------------------
    website already present ──▶ returned untouched (never overwritten)
    website empty ──▶ search(name + city) ──▶ candidates
                  ──▶ drop directories ──▶ score & validate ──▶ best domain, or unchanged

Why the search backend is a port
--------------------------------
"Search the public web" has no single correct implementation: an operator with a Google CSE
or Brave key wants that, an operator with neither still wants the feature to work. So the
backend is a small ABC (`SearchBackend`) living in `app/services/lead_providers/web_search/`,
with a zero-credential `DuckDuckGoSearchBackend` as the default — mirroring the reason
`OverpassLeadProvider` exists alongside the billed Google adapter.

That package is a hard boundary in both directions. It knows nothing about leads (no model,
no repository, no session, no scoring), and this module knows nothing about HTML SERPs. The
seam is `SearchResult`: three strings. Adding a keyed engine is a new module plus a
`@register_search_backend` decorator and a `WEB_SEARCH_BACKEND` value; **this service does not
change**, which is the property the split exists to buy.

Why validation is the hard part, not search
-------------------------------------------
A search for "Sunrise Studio Kozhikode" reliably returns *something*. The risk is not finding
nothing — it is confidently attaching the wrong domain to a lead, which is worse than leaving
the field empty, because an empty field is visibly a gap while a wrong one looks like data.
Two defences, in order:

  1. **Directories are rejected outright** (`_DIRECTORY_DOMAINS`). Justdial, Sulekha,
     IndiaMART, WeddingWire, Facebook, Instagram and their kin rank *above* a small studio's
     own site for exactly the query we issue, so an unfiltered "first result" implementation
     would attach a directory to the majority of leads. This list is the single highest-value
     component in the file.
  2. **What survives must still be shown to belong to the business** (`_score_candidate`).
     A domain earns its place by token overlap between the business name and the host, plus
     corroboration from the result title and the city. Below `_MIN_CONFIDENCE` we return the
     lead unchanged. Declining to guess is a supported outcome, not a failure.

`discover()` never raises for an ordinary miss. A network fault, a blocked SERP or a lead
that simply has no website all resolve to "returned unchanged", because this is enrichment:
an import of two hundred leads must not fail because one of them could not be resolved.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

from app.core.config import settings
from app.services.lead_providers.normalized import NormalizedLead, normalize_url
from app.services.lead_providers.web_search import (
    SearchBackend,
    SearchBackendError,
    SearchResult,
    get_search_backend,
)

#: Re-exported so `from app.services.website_discovery import SearchResult` keeps working for
#: callers written before the backend moved into its own package. The definitions live in
#: `app/services/lead_providers/web_search/`; these names are an alias, not a second copy.
__all__ = [
    "SearchBackend",
    "SearchBackendError",
    "SearchResult",
    "get_search_backend",
    "DiscoveryCandidate",
    "DiscoveryOutcome",
    "WebsiteDiscoveryService",
    "registrable_domain",
]

logger = logging.getLogger(__name__)


# ===========================================================================================
# Directory / aggregator rejection
# ===========================================================================================
# Hosts that are never a photography business's *own* site. Matched on the registrable domain
# and on any subdomain of it, so "kozhikode.justdial.com" is rejected along with
# "justdial.com".
#
# This is intentionally broad. A false negative here (a directory slips through) writes a
# wrong website onto a lead; a false positive (a legitimate site is skipped) leaves the field
# empty, which is the state the lead was already in. The costs are not symmetric, so the list
# errs toward rejecting.
_DIRECTORY_DOMAINS: frozenset[str] = frozenset({
    # Indian business directories — the dominant noise for this query shape.
    "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com", "yellowpages.in",
    "asklaila.com", "grotal.com", "indiacom.com", "yalwa.in", "quikr.com", "olx.in",
    "getdistributors.com", "exportersindia.com", "connect2india.com", "bizbangboom.com",
    "indianyellowpages.com", "citiesagent.com", "fyple.in", "tuugo.in", "cylex.in",
    # Wedding / photography marketplaces — rank extremely well for studio names.
    "weddingwire.in", "weddingwire.com", "wedmegood.com", "shaadisaga.com", "weddingz.in",
    "bookeventz.com", "weddingsutra.com", "themangoevents.com", "urbanclap.com",
    "urbancompany.com", "sulekha.in", "eventjuice.in", "photographers.co.in",
    "canvera.com", "wedmeplz.com", "brideside.com", "zankyou.com", "mywed.com",
    # Social and content platforms — a profile is not an official website.
    "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "pinterest.com", "tumblr.com", "reddit.com", "whatsapp.com",
    "threads.net", "vimeo.com", "flickr.com", "behance.net", "dribbble.com",
    # Maps, reviews and aggregators.
    "google.com", "google.co.in", "goo.gl", "maps.app.goo.gl", "bing.com", "yahoo.com",
    "duckduckgo.com", "tripadvisor.in", "tripadvisor.com", "yelp.com", "foursquare.com",
    "zomato.com", "openstreetmap.org", "wikipedia.org", "wikidata.org",
    # Generic hosting / link-in-bio, which is a landing page rather than a domain we can
    # attribute to one business with any confidence.
    "linktr.ee", "bit.ly", "tinyurl.com", "wa.me", "t.me", "medium.com",
    "blogspot.com", "wordpress.com", "wixsite.com", "weebly.com", "godaddysites.com",
    "business.site", "sites.google.com", "amazonaws.com", "cloudfront.net",
})

#: Path-bearing hosts that are directories even though their registrable domain is generic.
#: Kept separate because the check is a prefix match on the whole URL, not a host match.
_DIRECTORY_URL_PREFIXES: tuple[str, ...] = (
    "https://www.google.com/maps",
    "https://maps.google.com",
)

#: Hosts that are shorteners or redirectors. Distinguished from directories only for the
#: log message — both are rejected.
_NON_SITE_SUFFIXES: tuple[str, ...] = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")


# ===========================================================================================
# Name / token handling
# ===========================================================================================
# Words that carry no identifying signal for a photography business, because they appear in
# a large share of *all* such business names. "Sunrise Photography" and "Lakeside
# Photography" share "photography" and are unrelated; matching on it would let any studio's
# domain validate against any other studio's name.
_GENERIC_TOKENS: frozenset[str] = frozenset({
    "photography", "photographs", "photograph", "photographer", "photographers", "photo",
    "photos", "studio", "studios", "digital", "colour", "color", "labs", "lab", "media",
    "films", "film", "productions", "production", "creations", "creation", "creative",
    "capture", "captures", "clicks", "click", "frames", "frame", "shoot", "shoots",
    "wedding", "weddings", "candid", "event", "events", "art", "arts", "picture",
    "pictures", "pix", "image", "images", "imaging", "video", "videos", "videography",
    "the", "and", "of", "in", "at", "for", "by", "with", "a", "an",
    "pvt", "ltd", "private", "limited", "llp", "inc", "co", "company", "enterprises",
    "india", "indian",
})

#: Domain suffixes stripped when reducing a host to comparable tokens. Ordered longest-first
#: so ".co.in" is removed before ".in" would take only the tail.
_DOMAIN_SUFFIXES: tuple[str, ...] = (
    ".co.in", ".net.in", ".org.in", ".gen.in", ".firm.in", ".ind.in", ".co.uk", ".com.au",
    ".com", ".net", ".org", ".in", ".co", ".io", ".me", ".biz", ".info", ".studio",
    ".photography", ".photos", ".art", ".site", ".online", ".xyz", ".shop", ".store",
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokenize(value: str | None) -> list[str]:
    """Reduces a string to lowercase alphanumeric tokens, in source order."""
    if not value:
        return []
    return [t for t in _TOKEN_SPLIT.split(value.strip().lower()) if t]


def _significant_tokens(value: str | None) -> list[str]:
    """
    Tokenizes and drops the generic vocabulary, leaving the tokens that actually identify
    *this* business.

    Falls back to the full token list when everything was generic — a business genuinely
    named "The Photo Studio" has no distinctive token, and returning an empty list there
    would make every candidate score zero and every such lead unresolvable. Matching on
    generic tokens is weak, which is correct: the confidence threshold is what then decides.
    """
    tokens = _tokenize(value)
    significant = [t for t in tokens if t not in _GENERIC_TOKENS and len(t) > 1]
    return significant or tokens


def registrable_domain(host: str | None) -> str | None:
    """
    Reduces a hostname to the domain we would store: lowercased, `www.` stripped.

    Deliberately *not* a public-suffix-list implementation. A real PSL lookup needs a
    bundled, periodically-refreshed dataset; what this function is used for is comparison
    and directory matching, and for those, "the host without www" is sufficient and has no
    stale-data failure mode.
    """
    if not host:
        return None
    cleaned = host.strip().lower().rstrip(".")
    if not cleaned:
        return None
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned or None


def _domain_of(url: str | None) -> str | None:
    """Extracts the registrable domain from a URL, or None if it has no parseable host."""
    if not url:
        return None
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return None
    return registrable_domain(parsed.hostname)


def _is_directory_domain(domain: str | None) -> bool:
    """
    Reports whether a domain is a known directory, aggregator or social platform.

    Matches the domain itself and any subdomain of it, because directories serve city and
    category pages from subdomains ("kozhikode.justdial.com") that are the same site.
    """
    if not domain:
        return True
    if domain in _DIRECTORY_DOMAINS:
        return True
    return any(domain.endswith(f".{known}") for known in _DIRECTORY_DOMAINS)


def _domain_tokens(domain: str) -> list[str]:
    """
    Reduces a domain to its comparable tokens by stripping the public suffix and splitting
    on separators.

    "sunrisestudio.co.in" becomes ["sunrisestudio"], which will not token-match "sunrise" on
    equality — hence `_score_candidate` also does substring containment against the
    concatenated form. Studios overwhelmingly register their name without separators, so
    that path is the common one, not the exception.
    """
    stem = domain
    for suffix in _DOMAIN_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return [t for t in _TOKEN_SPLIT.split(stem) if t]


# ===========================================================================================
# Candidate scoring
# ===========================================================================================

@dataclass(frozen=True)
class DiscoveryCandidate:
    """One surviving search result with the evidence that earned it its score."""
    url: str
    domain: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryOutcome:
    """
    The full result of discovering one lead's website: the (possibly enriched) lead plus why.

    Returned by `discover_with_outcome` so a caller that wants to log or display the decision
    can, while `discover()` stays a plain `NormalizedLead -> NormalizedLead` function for the
    common case. `status` is one of: `already_present`, `discovered`, `no_candidates`,
    `below_threshold`, `not_searchable`, `search_failed`, `validation_failed`. Only
    `discovered` changes the lead; every other status returns it untouched.
    """
    lead: NormalizedLead
    status: str
    website: str | None = None
    confidence: float = 0.0
    reasons: tuple[str, ...] = ()
    candidates_considered: int = 0
    rejected_directories: tuple[str, ...] = ()
    detail: str | None = None


#: Minimum score a candidate must reach to be attached to a lead. Tuned so that a domain
#: sharing one distinctive name token with the business (the "sunrisestudio.com" for "Sunrise
#: Studio" case) clears it, while a domain matching only on generic vocabulary does not.
#: Raising it costs recall on studios whose domain is an abbreviation; lowering it starts
#: attaching plausible-looking neighbours, which is the failure that matters.
_MIN_CONFIDENCE = 0.5


class WebsiteDiscoveryService:
    """
    Finds and validates the official website of leads that arrived without one.

    Stateless with respect to any single run — the lead travels through as an argument — so
    one instance is safe to reuse across concurrent imports. The backend's rate limiter *is*
    shared instance state, on purpose: it exists so concurrent discoveries queue rather than
    burst against the public endpoint.

    Writes nothing to the database. This class imports no model, no repository and no
    session, and returns new `NormalizedLead` objects for the caller to do with as it wishes.
    """

    def __init__(
        self,
        backend: SearchBackend | None = None,
        min_confidence: float | None = None,
        max_results: int | None = None,
        concurrency: int | None = None,
    ) -> None:
        """
        Args:
            backend: Explicit search backend. Injected in tests and available to a caller
                that wants a specific engine; production construction resolves the configured
                default.
            min_confidence: Score a candidate must reach to be accepted.
            max_results: How many search results to consider per lead.
            concurrency: How many leads `discover_many` resolves at once.
        """
        self._backend = backend or get_search_backend()
        self._min_confidence = (
            min_confidence if min_confidence is not None
            else settings.WEBSITE_DISCOVERY_MIN_CONFIDENCE
        )
        self._max_results = (
            max_results if max_results is not None
            else settings.WEBSITE_DISCOVERY_MAX_RESULTS
        )
        self._concurrency = max(
            1,
            concurrency if concurrency is not None
            else settings.WEBSITE_DISCOVERY_CONCURRENCY,
        )

    # -----------------------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------------------

    async def discover(self, lead: NormalizedLead) -> NormalizedLead:
        """
        Returns `lead` enriched with a discovered website, or `lead` unchanged.

        This is the method the brief describes: for one normalized lead, if the website is
        empty, search, validate, and save only an official domain. It **never overwrites** an
        existing website and **never raises** — every failure path returns the input lead, so
        an enrichment pass cannot fail an import.
        """
        return (await self.discover_with_outcome(lead)).lead

    async def discover_with_outcome(self, lead: NormalizedLead) -> DiscoveryOutcome:
        """
        `discover()` plus the reasoning, for callers that want to log or display why a lead
        was or was not enriched.

        Separated so the common path stays a clean lead-in/lead-out function while the
        decision remains inspectable — the same split `LeadProvider` makes between
        `collect()` and `collect_normalized()`.
        """
        # Rule 6: an existing website is authoritative and is never overwritten. Checked
        # first, before any work, because it is also the cheapest branch — a run over leads
        # that mostly have websites issues almost no searches.
        if _has_website(lead):
            return DiscoveryOutcome(
                lead=lead, status="already_present", website=lead.website,
                detail="Lead already has a website; left untouched.",
            )

        query = self._build_query(lead)
        if not query:
            return DiscoveryOutcome(
                lead=lead, status="not_searchable",
                detail="Lead has no business name to search on.",
            )

        if not self._backend.is_available:
            return DiscoveryOutcome(
                lead=lead, status="search_failed",
                detail=self._backend.unavailable_reason,
            )

        try:
            results = await self._backend.search(query, self._max_results)
        except SearchBackendError as exc:
            # Enrichment is best-effort: a search fault leaves the lead exactly as it was.
            logger.warning("Website discovery search failed for %r: %s", query, exc)
            return DiscoveryOutcome(
                lead=lead, status="search_failed", detail=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - a backend bug must not fail an import
            logger.exception("Website discovery backend raised for %r.", query)
            return DiscoveryOutcome(
                lead=lead, status="search_failed", detail=f"Unexpected backend error: {exc}"
            )

        candidates, rejected = self._evaluate(lead, results)
        if not candidates:
            return DiscoveryOutcome(
                lead=lead, status="no_candidates",
                candidates_considered=len(results),
                rejected_directories=tuple(rejected),
                detail=(
                    "No non-directory result could be attributed to this business."
                    if results else "Search returned no results."
                ),
            )

        best = candidates[0]
        if best.score < self._min_confidence:
            # Declining to guess is a supported outcome. A wrong website looks like data;
            # an empty one visibly reads as a gap.
            return DiscoveryOutcome(
                lead=lead, status="below_threshold", website=None,
                confidence=best.score, reasons=best.reasons,
                candidates_considered=len(results),
                rejected_directories=tuple(rejected),
                detail=(
                    f"Best candidate {best.domain} scored {best.score:.2f}, below the "
                    f"{self._min_confidence:.2f} threshold; lead left unchanged."
                ),
            )

        # Rule 5: only the official *domain* is saved, not the deep result URL that happened
        # to rank. A lead's website field is the business's site, not the one page a search
        # engine chose to surface.
        website = normalize_url(best.domain)
        if not website:
            return DiscoveryOutcome(
                lead=lead, status="no_candidates",
                candidates_considered=len(results),
                rejected_directories=tuple(rejected),
                detail=f"Candidate domain {best.domain!r} is not a storable URL.",
            )

        # Rule 4: the URL must also *resolve*. Shape validation above proves it is well-formed;
        # this proves something answers at it. A domain that scored well but serves nothing is
        # a dead link written onto a lead — indistinguishable from real data in the UI, which
        # is the exact failure this service exists to avoid.
        reachable, validation_detail = await self._validate_website(website)
        if not reachable:
            return DiscoveryOutcome(
                lead=lead, status="validation_failed", website=None,
                confidence=best.score, reasons=best.reasons,
                candidates_considered=len(results),
                rejected_directories=tuple(rejected),
                detail=f"Candidate {website} failed validation: {validation_detail}",
            )

        enriched = replace(lead, website=website)
        return DiscoveryOutcome(
            lead=enriched, status="discovered", website=website,
            confidence=best.score, reasons=best.reasons,
            candidates_considered=len(results),
            rejected_directories=tuple(rejected),
            detail=f"Discovered {website} for {lead.business_name!r}.",
        )

    async def _validate_website(self, url: str) -> tuple[bool, str]:
        """
        Confirms that `url` actually resolves, returning `(is_valid, detail)`.

        Three guards, matching the brief:

          * **Shape** — scheme must be http/https with a real host. Checked without touching
            the network, so a malformed candidate costs nothing.
          * **Bounded redirects** — `WEB_SEARCH_MAX_REDIRECTS`, never unlimited. A parked
            domain that redirects in a loop must terminate rather than eat the timeout.
          * **Short timeout** — `WEBSITE_DISCOVERY_VALIDATE_TIMEOUT_SECONDS`, deliberately
            shorter than the search timeout since this runs once per discovered lead.

        A HEAD request first, falling back to GET: HEAD is far cheaper, but enough small hosts
        answer it with 405 that treating that as a failure would discard working sites.

        **Any failure returns False rather than raising** — including a missing `httpx`. A
        lead whose website could not be confirmed is returned unchanged, exactly as if nothing
        had been found, because an unverifiable website is not worth more than an empty field.
        """
        if not settings.WEBSITE_DISCOVERY_VALIDATE_URL:
            return True, "validation disabled"

        try:
            parsed = urlparse(url)
        except ValueError as exc:
            return False, f"unparseable URL ({exc})"
        if parsed.scheme not in ("http", "https"):
            return False, f"scheme {parsed.scheme!r} is not http/https"
        if not parsed.hostname or "." not in parsed.hostname:
            return False, "URL has no resolvable host"

        try:
            import httpx  # noqa: PLC0415 - deferred; see _import_httpx in the ddg backend
        except ImportError:
            # Without httpx we cannot check. Accept on shape alone rather than discarding
            # every discovery: the candidate already cleared directory filtering and scoring.
            logger.debug("httpx unavailable; accepting %s on shape alone.", url)
            return True, "httpx unavailable, shape-validated only"

        timeout = httpx.Timeout(settings.WEBSITE_DISCOVERY_VALIDATE_TIMEOUT_SECONDS)
        headers = {"User-Agent": settings.WEB_SEARCH_USER_AGENT}
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                max_redirects=settings.WEB_SEARCH_MAX_REDIRECTS,
            ) as client:
                response = await client.head(url)
                if response.status_code in (405, 501) or response.status_code >= 400:
                    # Some hosts reject HEAD outright; confirm with a GET before giving up.
                    response = await client.get(url)
        except Exception as exc:  # noqa: BLE001 - any fault means "could not confirm"
            logger.debug("Website validation failed for %s: %s", url, exc)
            return False, f"request failed ({type(exc).__name__}: {exc})"

        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}"
        return True, f"HTTP {response.status_code}"

    async def discover_many(
        self, leads: Sequence[NormalizedLead]
    ) -> list[NormalizedLead]:
        """
        Runs `discover()` across a batch, preserving input order.

        Bounded-concurrency rather than sequential for the same reason the Google adapter
        fans out its Details calls: a hundred sequential round-trips inside one import is the
        difference between a fast run and a timeout. The bound is low by default because the
        default backend is an unmetered public endpoint whose limiter serialises anyway — the
        semaphore is there to keep a keyed backend from being fanned out unboundedly.
        """
        semaphore = asyncio.Semaphore(self._concurrency)

        async def resolve(lead: NormalizedLead) -> NormalizedLead:
            async with semaphore:
                return await self.discover(lead)

        return list(await asyncio.gather(*(resolve(lead) for lead in leads)))

    # -----------------------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------------------

    @staticmethod
    def _build_query(lead: NormalizedLead) -> str | None:
        """
        Builds the search query from the business name plus city, per the brief.

        City is appended when present because it is what disambiguates the many studios
        sharing a common name across India — the same reason `normalize_business_key`
        includes it. `official website` is *not* appended: it biases the engine toward
        directory pages that use that phrase in their boilerplate, which is the exact noise
        this service exists to filter out.
        """
        name = (lead.business_name or "").strip()
        if not name:
            return None
        city = (lead.city or "").strip()
        return f"{name} {city}".strip() if city else name

    def _evaluate(
        self, lead: NormalizedLead, results: Iterable[SearchResult]
    ) -> tuple[list[DiscoveryCandidate], list[str]]:
        """
        Filters and scores search results, returning `(candidates, rejected_directories)`
        with candidates ordered best-first.

        Directory rejection happens before scoring, not after, so a highly-ranked Justdial
        page can never win on score. Ties break toward the earlier search result, since the
        engine's own ranking is real evidence.
        """
        name_tokens = _significant_tokens(lead.business_name)
        city_tokens = set(_tokenize(lead.city))
        candidates: list[DiscoveryCandidate] = []
        rejected: list[str] = []
        seen_domains: set[str] = set()

        for rank, result in enumerate(results):
            url = (result.url or "").strip()
            if not url or any(
                url.lower().startswith(prefix) for prefix in _DIRECTORY_URL_PREFIXES
            ):
                continue
            if url.lower().endswith(_NON_SITE_SUFFIXES):
                continue

            domain = _domain_of(url)
            if not domain:
                continue

            # Rule 4: directory websites are ignored entirely.
            if _is_directory_domain(domain):
                if domain not in rejected:
                    rejected.append(domain)
                continue

            # One entry per domain: a site ranking three of its own pages is one candidate,
            # and its best-ranked page is the one that represents it.
            if domain in seen_domains:
                continue
            seen_domains.add(domain)

            score, reasons = _score_candidate(
                domain=domain, result=result, name_tokens=name_tokens,
                city_tokens=city_tokens, rank=rank,
            )
            candidates.append(
                DiscoveryCandidate(
                    url=url, domain=domain, score=score, reasons=tuple(reasons)
                )
            )

        candidates.sort(key=lambda c: -c.score)
        return candidates, rejected

    def describe(self) -> dict[str, Any]:
        """Renders this service's effective configuration, for diagnostics."""
        return {
            "backend": self._backend.describe(),
            "min_confidence": self._min_confidence,
            "max_results": self._max_results,
            "concurrency": self._concurrency,
            "validates_urls": settings.WEBSITE_DISCOVERY_VALIDATE_URL,
        }


def _has_website(lead: NormalizedLead) -> bool:
    """
    Reports whether a lead already carries a website.

    Whitespace-only counts as empty, because a CSV column containing a space is empty in
    every sense that matters — but any real value, even one this service would not have
    chosen, is left alone. The brief's "do not overwrite" is about provenance, not quality:
    the provider saw the business's own listing, and that beats our inference.
    """
    return bool((lead.website or "").strip())


def _score_candidate(
    *,
    domain: str,
    result: SearchResult,
    name_tokens: Sequence[str],
    city_tokens: set[str],
    rank: int,
) -> tuple[float, list[str]]:
    """
    Scores how strongly `domain` looks like the official site of the business described by
    `name_tokens`, returning `(score, reasons)`.

    This is rule 3 — "validate that it belongs to the same business" — and it is the whole
    defence against attaching a plausible neighbour's domain. Evidence is additive and each
    piece is recorded, so a decision can be explained after the fact:

      * **Domain/name overlap** (up to 0.6) — the primary signal. Measured both as token
        equality and as substring containment against the concatenated domain stem, because
        "Sunrise Studio" registers as "sunrisestudio.com" far more often than as
        "sunrise-studio.com".
      * **Title corroboration** (up to 0.3) — the SERP title containing the business's
        distinctive tokens is independent evidence from the domain string.
      * **City corroboration** (0.1) — the city appearing in the title or snippet.
      * **Rank bonus** (up to 0.1) — the engine's own ranking, worth a little and no more:
        it is what puts directories on top in the first place.

    Capped at 1.0 so the threshold reads as a probability-like confidence.
    """
    reasons: list[str] = []
    score = 0.0

    stem_tokens = _domain_tokens(domain)
    stem = "".join(stem_tokens)
    significant = [t for t in name_tokens if t not in _GENERIC_TOKENS and len(t) > 2]
    comparable = significant or [t for t in name_tokens if len(t) > 2]

    if comparable:
        matched = [
            token for token in comparable
            if token in stem_tokens or (len(token) > 3 and token in stem)
        ]
        if matched:
            coverage = len(matched) / len(comparable)
            score += 0.6 * coverage
            reasons.append(
                f"domain '{domain}' matches name token(s) {', '.join(matched)}"
                f" ({coverage:.0%} of distinctive tokens)"
            )

    title_tokens = set(_tokenize(result.title))
    if comparable and title_tokens:
        matched_title = [t for t in comparable if t in title_tokens]
        if matched_title:
            coverage = len(matched_title) / len(comparable)
            score += 0.3 * coverage
            reasons.append(
                f"result title corroborates name token(s) {', '.join(matched_title)}"
            )

    if city_tokens:
        context_tokens = title_tokens | set(_tokenize(result.snippet))
        if city_tokens & context_tokens:
            score += 0.1
            reasons.append("result mentions the lead's city")

    if rank == 0:
        score += 0.1
        reasons.append("top-ranked non-directory result")
    elif rank <= 2:
        score += 0.05
        reasons.append(f"highly-ranked non-directory result (position {rank + 1})")

    return min(score, 1.0), reasons
