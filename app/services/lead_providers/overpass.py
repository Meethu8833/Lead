"""
app/services/lead_providers/overpass.py

This file implements `OverpassLeadProvider` — the adapter that collects photography
businesses from OpenStreetMap via the public Overpass API, as a zero-cost replacement for
the billed Google Places adapter in `google_maps.py`.

It is an adapter in the strict sense, exactly like its predecessor: it knows how to talk to
Overpass and how to shape Overpass JSON into a `NormalizedLead`, and it knows nothing else.
Lead creation, deduplication, enrichment, audit logging and job statistics all remain in
`LeadImportService`. Nothing downstream changes when an operator switches provider — which
is the property that makes replacing a paid source with a free one a one-line choice at
request time rather than a migration.

Why two services, and why the geocode comes first
-------------------------------------------------
Overpass is a *query* API over a geographic database, not a search engine. It cannot answer
"photographers in Kozhikode"; it can only answer "objects with these tags inside this
bounding shape". The shape has to be supplied as coordinates. So collection is necessarily
two hops:

  1. **Nominatim** turns the operator's `city` into a (lat, lon). One call, cached per run.
  2. **Overpass** runs one QL query for photography tags inside `around:radius_km` of that
     point. One call, returning every match at once.

That is *two* network calls for an entire import, against Google's N+1 (one Text Search page
plus one billed Details call per business). The cost model that dominated the Google adapter
— honour the limit before the fan-out, bound the concurrency, let an operator switch details
off — simply does not exist here. There is no fan-out to bound and nothing is billed.

What replaces cost as the thing to be careful about
---------------------------------------------------
The public Overpass and Nominatim instances are donated capacity governed by a usage policy,
not a paid quota. The failure mode is not a surprise invoice, it is being blocked. Three
things in this file exist solely for that reason, and they are the main design decisions:

  * **Serialised, spaced requests.** `_RateLimiter` holds a lock across the whole call and
    enforces `OVERPASS_MIN_REQUEST_INTERVAL_SECONDS` between releases, so two concurrent
    imports cannot burst at the endpoint. The policy asks for roughly one query at a time
    from a client; this is that, mechanically enforced rather than hoped for.
  * **Retry with exponential backoff**, honouring `Retry-After`. Overpass answers 429 and
    504 under load and both are transient — the documented correct response is to wait and
    retry, and treating them as fatal would fail runs that were always going to succeed.
  * **A real User-Agent.** Both policies require a client to identify itself.

The one thing OSM gives that Google does not: email
----------------------------------------------------
Google Places returns no email address at any price. OSM contributors tag `email` and
`contact:email` directly, so this adapter populates `NormalizedLead.emails` from data the
paid provider structurally could not supply.

The corresponding loss is coverage and contactability. OSM's photography coverage in India is
thinner than Google's, and — the operational fact that matters most — many OSM nodes carry a
name and a location but **no phone**, which `NormalizedLead.is_valid()` rejects. A run here
will show a higher failed-record count than the same search on Google Places. That is
expected, it is visible in the job log per record, and it is the trade being made for a
provider that costs nothing.

The failure contract
--------------------
Unchanged from the rest of the engine, and the reason this file drops in cleanly.
`ProviderCollectionError` is raised **only** for faults that invalidate the whole run: the
city cannot be geocoded, the endpoint is unreachable, or it is still refusing after every
retry. Anything wrong with a single OSM element — no phone, an unparseable coordinate, a
malformed tag — degrades that one record via `is_valid()` and never the run.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Sequence

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.services.lead_providers.base import (
    LeadProvider,
    ProviderCollectionError,
    ProviderContext,
    register_provider,
)
from app.services.lead_providers.normalized import NormalizedLead

logger = logging.getLogger(__name__)


#: OSM tag filters that identify a photography business, as (key, value) pairs. These are
#: the three the brief names, plus the two `craft` spellings that are in fact the dominant
#: tagging for a photography studio in OSM's own data — `craft=photographer` outnumbers
#: `office=photographer` substantially, and omitting it would silently halve the yield.
#:
#: Each pair becomes one clause per element type in the generated QL. `studio=photography`
#: is the documented value for a photo studio and is paired with `amenity=studio` in the
#: wild; both are queried because contributors use them inconsistently.
_PHOTOGRAPHY_FILTERS: tuple[tuple[str, str], ...] = (
    ("shop", "photo"),
    ("shop", "photo_studio"),
    ("office", "photographer"),
    ("craft", "photographer"),
    ("studio", "photography"),
)

#: OSM element types queried. `node` is a point, `way` is a building outline, `relation` is
#: a multipolygon. A studio may be tagged as any of the three, and querying only nodes — the
#: obvious simplification — drops every business mapped as a building, which in Indian towns
#: is a large share of the commercial POIs.
_ELEMENT_TYPES: tuple[str, ...] = ("node", "way", "relation")

#: Tag keys carrying a phone number, in preference order. OSM has no single canonical key:
#: `phone` is the modern form, `contact:phone` the older namespaced one, and both coexist in
#: current data. `mobile` is listed last because a landline on `phone` is more often the
#: business's published number, and `NormalizedLead` promotes the first entry to the CRM's
#: `phone` column.
_PHONE_KEYS: tuple[str, ...] = (
    "phone",
    "contact:phone",
    "contact:mobile",
    "mobile",
    "phone:mobile",
)

#: Tag keys carrying an email address, same namespacing story as phones.
_EMAIL_KEYS: tuple[str, ...] = ("email", "contact:email")

#: Tag keys carrying a website.
_WEBSITE_KEYS: tuple[str, ...] = ("website", "contact:website", "url", "contact:url")

#: Tag keys carrying a name, in preference order. `name:en` is preferred over `name` for a
#: CRM whose operators work in English — a Malayalam-script `name` is correct OSM data but
#: unusable in a call list — and `official_name`/`brand` are last-resort fallbacks.
_NAME_KEYS: tuple[str, ...] = ("name:en", "name", "official_name", "brand", "operator")

#: `addr:*` tag -> the address line component it contributes, in the order an Indian address
#: is written. OSM stores addresses as separate tagged parts rather than one formatted
#: string, so a displayable address has to be assembled here.
_ADDRESS_PART_KEYS: tuple[str, ...] = (
    "addr:housenumber",
    "addr:housename",
    "addr:street",
    "addr:place",
    "addr:suburb",
    "addr:neighbourhood",
)

#: Tag keys carrying the city, district, state and postcode. `addr:city` is the standard;
#: the fallbacks matter because Indian addresses are frequently tagged at town or village
#: granularity instead, and taking no city at all would disable the business-name+city
#: duplicate rule for those records.
_CITY_KEYS: tuple[str, ...] = ("addr:city", "addr:town", "addr:village", "addr:suburb")
_DISTRICT_KEYS: tuple[str, ...] = ("addr:district", "addr:county", "addr:subdistrict")
_STATE_KEYS: tuple[str, ...] = ("addr:state", "addr:province")
_POSTCODE_KEYS: tuple[str, ...] = ("addr:postcode", "postal_code")
_COUNTRY_KEYS: tuple[str, ...] = ("addr:country",)

#: HTTP statuses worth retrying. 429 is Overpass's explicit rate-limit signal and 504 its
#: "query load too high, try later"; the 5xx entries are ordinary transient server faults.
#: A 400 (malformed QL) or 403 is *not* here — those are bugs or blocks, and retrying them
#: just adds load to an endpoint that has already said no.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

#: Kilometres to metres, for the `around:` filter which is specified in metres.
_KM_TO_M = 1000.0


class _RateLimiter:
    """
    Serialises outbound calls and enforces a minimum gap between them.

    Deliberately a lock plus a timestamp rather than a token bucket: the Overpass usage
    policy asks for roughly *one query at a time* from a given client, so the correct model
    is a queue, not a burst allowance. Holding the lock for the duration of the request —
    not merely while sleeping — is what delivers that, and it is why this class cannot be
    replaced with a bare `asyncio.sleep` between calls.

    One instance is shared per provider instance, so two concurrent imports running through
    the same registry-resolved provider queue behind each other instead of doubling the load
    the endpoint sees.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = max(0.0, min_interval_seconds)
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def acquire(self) -> None:
        """
        Waits until it is polite to issue the next request. The caller must call `release()`
        when its request finishes, so a `try/finally` is mandatory at the call site — see
        `_request_with_retry`.
        """
        await self._lock.acquire()
        if self._last_request_at is not None and self._min_interval > 0:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_request_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

    def release(self) -> None:
        """Marks the request finished and lets the next caller through."""
        try:
            self._last_request_at = asyncio.get_running_loop().time()
        except RuntimeError:  # pragma: no cover - only if released outside a loop
            self._last_request_at = None
        if self._lock.locked():
            self._lock.release()


def _first_tag(tags: dict[str, Any], keys: Sequence[str]) -> str | None:
    """
    Returns the first non-empty tag value among `keys`, honouring the caller's preference
    order rather than the dict's.

    Preference order is the whole point: `name:en` beating `name`, and `phone` beating
    `mobile`, are the two decisions that determine what an operator actually sees and dials.
    """
    for key in keys:
        value = tags.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _split_multi(value: str | None) -> list[str]:
    """
    Splits an OSM multi-value tag into its parts.

    OSM's convention is semicolon separation (`phone=+91 495 111;+91 495 222`), and a studio
    publishing two numbers in one tag is common. Comma is also accepted because contributors
    use it despite the convention. Returned in source order, since `NormalizedLead` promotes
    the first phone to the CRM's primary column.
    """
    if not value:
        return []
    return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]


@register_provider
class OverpassLeadProvider(LeadProvider):
    """
    Adapter that collects photography businesses from OpenStreetMap via the Overpass API.

    Collection is one Nominatim geocode of the requested city followed by one Overpass QL
    query for photography tags within `radius_km` of the resulting point. `normalize()` then
    maps each returned OSM element onto a `NormalizedLead`.

    The instance holds no run state — query, city, limit and radius all travel on the
    `ProviderContext` — so one instance is safe to reuse across concurrent imports. The rate
    limiter *is* instance state, and is shared on purpose: it exists precisely to make those
    concurrent imports queue rather than burst.
    """

    key = "overpass"
    display_name = "OpenStreetMap (Overpass)"

    #: Overpass leads are map-listing leads, tagged with the same `LeadSource` member the
    #: Google Places adapter used. Reusing the member rather than adding one keeps this a
    #: pure provider-layer change: no `LeadSource` edit, no enum migration, and existing
    #: dashboards and dedup rules that group map-sourced leads keep working unchanged.
    lead_source = "GOOGLE_MAPS"

    #: A city is what this provider actually needs (it geocodes it), but the query is what
    #: the shared `search()` validates and what the engine records on the job. It stays
    #: required so a bare "collect everything near here" run is impossible.
    requires_query = True
    requires_file = False

    #: Unconditionally available: OSM data is open and the public endpoints need no
    #: credential. This is the substantive difference from `GoogleMapsLeadProvider`, whose
    #: availability is computed from whether an API key is configured.
    is_available = True

    def __init__(
        self,
        base_url: str | None = None,
        nominatim_url: str | None = None,
        min_request_interval: float | None = None,
    ) -> None:
        """
        Args:
            base_url / nominatim_url: Explicit endpoint overrides. These exist so a test can
                drive the adapter against a stub server, and so an operator running their
                own Overpass instance — what the usage policy recommends for heavy use — can
                point at it without a code change. Production construction goes through the
                registry, which takes no arguments and therefore reads settings.
            min_request_interval: Override for the politeness gap, so a test does not have to
                spend a real second per request.
        """
        self._base_url = (base_url or settings.OVERPASS_BASE_URL).strip()
        self._nominatim_url = (nominatim_url or settings.NOMINATIM_BASE_URL).strip()
        interval = (
            min_request_interval
            if min_request_interval is not None
            else settings.OVERPASS_MIN_REQUEST_INTERVAL_SECONDS
        )
        self._rate_limiter = _RateLimiter(interval)

    # -----------------------------------------------------------------------------------
    # search()
    # -----------------------------------------------------------------------------------

    def search(self, query: str | None = None, **kwargs: Any) -> ProviderContext:
        """
        Validates an Overpass collection request and returns its run context.

        Beyond the shared checks in `LeadProvider.search` (non-empty query, limit bounds),
        this enforces the two inputs specific to this provider:

          * **city is mandatory.** Unlike Google Text Search, which accepts a free-text
            locality inside the query string, Overpass needs coordinates. With no city there
            is nothing to geocode and therefore no query to build at all. Refusing here — at
            request time — is much better than failing after the job is marked RUNNING.
          * **radius_km is parsed, defaulted and clamped.** It arrives through
            `ProviderContext.options`, which is exactly what that free-form field is for: a
            parameter no other adapter has, added without widening the shared dataclass. The
            clamp to `OVERPASS_MAX_RADIUS_KM` is a politeness measure — a state-sized radius
            is a multi-minute query on donated infrastructure.

        The parsed radius is written back into `context.options["radius_km"]` as a float, so
        `collect()` reads one already-validated value rather than re-parsing operator input.

        Raises:
            BadRequestException: no query, no city, or an unusable radius.
        """
        context = super().search(query, **kwargs)

        city = (context.city or "").strip()
        if not city:
            raise BadRequestException(
                f"Provider '{self.key}' requires a `city`: OpenStreetMap is queried by "
                f"coordinates, and the city is what gets geocoded to produce them."
            )
        context.city = city

        context.options["radius_km"] = self._resolve_radius(context.options.get("radius_km"))
        return context

    def _resolve_radius(self, value: Any) -> float:
        """
        Parses, defaults and clamps the requested radius in kilometres.

        `None` means "not supplied" and takes the configured default. A supplied-but-garbage
        value is an error rather than a silent fallback to the default: an operator who typed
        "10km" into a numeric field should be told, not quietly given something else. A value
        above the ceiling is clamped with a log line rather than refused, because the request
        is coherent and answerable — just not at the size asked for.
        """
        if value is None or value == "":
            return float(settings.OVERPASS_DEFAULT_RADIUS_KM)
        try:
            radius = float(value)
        except (TypeError, ValueError):
            raise BadRequestException("`radius_km` must be a number of kilometres.")
        if radius <= 0:
            raise BadRequestException("`radius_km` must be greater than 0.")

        ceiling = float(settings.OVERPASS_MAX_RADIUS_KM)
        if radius > ceiling:
            logger.info(
                "Overpass radius %.1fkm exceeds the %.1fkm ceiling; clamping.",
                radius, ceiling,
            )
            radius = ceiling
        return radius

    # -----------------------------------------------------------------------------------
    # collect()
    # -----------------------------------------------------------------------------------

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        """
        Collects raw OSM elements for the context's city, category and radius.

        Geocodes the city, builds and executes one Overpass QL query, then returns the raw
        elements — deliberately un-normalized, so `normalize()` stays a pure mapping testable
        without a network, and so the untouched OSM payload travels with each record for
        diagnosis.

        Elements carrying no tags at all are dropped here rather than passed on: an untagged
        way is a geometry fragment, not a business, and letting it through would inflate the
        job's failed-record count with noise that tells the operator nothing. Everything that
        looks like a business is kept even when it lacks a phone, so the operator sees it
        counted and logged as an unusable record rather than silently vanishing.

        Raises:
            ProviderCollectionError: a run-level fault — `httpx` unavailable, the city cannot
                be geocoded, or the endpoint is unreachable or still refusing after retries.
        """
        httpx = self._import_httpx()
        city = (context.city or "").strip()
        if not city:
            raise ProviderCollectionError(
                "Overpass collection requires a city to geocode; none was supplied."
            )

        radius_km = self._resolve_radius(context.options.get("radius_km"))
        category = self._resolve_category(context)

        timeout = httpx.Timeout(settings.OVERPASS_TIMEOUT_SECONDS)
        headers = {
            # Required by both usage policies. See the module docstring.
            "User-Agent": settings.OVERPASS_USER_AGENT,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                latitude, longitude, place = await self._geocode_city(
                    client, httpx, city, context.state
                )

                query = self.build_query(latitude, longitude, radius_km)
                logger.info(
                    "Overpass query for %r (%.5f, %.5f) r=%.1fkm",
                    city, latitude, longitude, radius_km,
                )
                payload = await self._request_with_retry(
                    client, httpx, self._base_url, method="POST", data={"data": query},
                )

                elements = payload.get("elements")
                if not isinstance(elements, list):
                    raise ProviderCollectionError(
                        "Overpass returned a payload with no `elements` list; the endpoint "
                        "may be returning an error page rather than JSON."
                    )

                records: list[dict[str, Any]] = []
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    # No tags means no business — a bare geometry node belonging to a way.
                    if not (element.get("tags") or {}):
                        continue
                    records.append({
                        "element": element,
                        "search_city": city,
                        "search_state": context.state,
                        "search_category": category,
                        "search_radius_km": radius_km,
                        "geocode": place,
                    })
                    if len(records) >= context.limit:
                        break

                logger.info(
                    "Overpass returned %d elements, %d retained (limit %d).",
                    len(elements), len(records), context.limit,
                )
                return records

        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport fault is a run-level fault
            logger.exception("Overpass collection failed for city %r.", city)
            raise ProviderCollectionError(f"Overpass collection failed: {exc}") from exc

    @staticmethod
    def _resolve_category(context: ProviderContext) -> str | None:
        """
        Reads the operator's requested category.

        Accepted from `options["category"]` and falling back to the query text, because the
        engine's generic entry point supplies a `query` while a caller driving this provider
        directly supplies a `category`. It is recorded on every raw record and surfaces as a
        lead category tag; it does **not** narrow the Overpass query itself, since OSM has no
        free-text index to narrow *with* — the tag filters are the whole selectivity this API
        offers, and pretending otherwise by filtering names client-side would drop correctly
        tagged studios whose names simply do not contain the operator's word.
        """
        category = context.options.get("category")
        text = str(category).strip() if category is not None else ""
        return text or (context.query or "").strip() or None

    @staticmethod
    def _import_httpx() -> Any:
        """
        Imports `httpx` lazily, converting an absent dependency into a run-level provider
        error rather than an import-time crash.

        Deferred deliberately, for the same reason as in `google_maps.py`:
        `app/services/lead_providers/__init__.py` imports this module at startup for its
        registration side effect, so a top-level `import httpx` would take the whole API down
        on a deployment that never uses this provider.
        """
        try:
            import httpx  # noqa: PLC0415 - deferred on purpose, see docstring
        except ImportError as exc:  # pragma: no cover - depends on the deployment image
            raise ProviderCollectionError(
                "The 'httpx' package is required for Overpass collection but is not "
                "installed. Install it with: pip install httpx"
            ) from exc
        return httpx

    # -----------------------------------------------------------------------------------
    # Geocoding
    # -----------------------------------------------------------------------------------

    async def _geocode_city(
        self, client: Any, httpx: Any, city: str, state: str | None
    ) -> tuple[float, float, dict[str, Any]]:
        """
        Resolves a city name to `(latitude, longitude, raw_place)` via Nominatim.

        State is appended to the search text when supplied, because "Thrissur" alone is
        ambiguous across countries and Nominatim's first result for a bare Indian town name
        is not reliably the Indian one. `countrycodes=in` biases the same way the Google
        adapter's `region=in` did.

        A city that cannot be geocoded is a **run-level** failure, not a per-record one:
        without coordinates there is no query to run at all, so there is nothing to degrade
        gracefully into. This is the one place this adapter fails a run for something the
        operator typed, and the message says so plainly.

        Raises:
            ProviderCollectionError: Nominatim is unreachable, or the city matched nothing.
        """
        search_terms = city if not (state or "").strip() else f"{city}, {state.strip()}"
        params = {
            "q": search_terms,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "in",
        }

        payload = await self._request_with_retry(
            client, httpx, self._nominatim_url, method="GET", params=params,
        )

        # Nominatim returns a bare JSON array, unlike Overpass's object.
        results = payload if isinstance(payload, list) else payload.get("results") or []
        if not results:
            raise ProviderCollectionError(
                f"Could not geocode '{search_terms}': OpenStreetMap's Nominatim returned no "
                f"match. Check the spelling, or supply a larger nearby city."
            )

        place = results[0] if isinstance(results[0], dict) else {}
        try:
            latitude = float(place["lat"])
            longitude = float(place["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderCollectionError(
                f"Nominatim returned an unusable location for '{search_terms}'."
            ) from exc

        logger.info("Geocoded %r to (%.5f, %.5f).", search_terms, latitude, longitude)
        return latitude, longitude, place

    # -----------------------------------------------------------------------------------
    # Query construction
    # -----------------------------------------------------------------------------------

    def build_query(self, latitude: float, longitude: float, radius_km: float) -> str:
        """
        Builds the Overpass QL query for photography businesses around a point.

        Public and pure so the generated QL is directly assertable in a unit test without any
        network — the query string *is* the contract with Overpass, and a silent change to it
        changes what an import returns.

        Shape notes:
          * `[out:json]` — the JSON encoding this adapter parses.
          * `[timeout:N]` — tells the *server* its budget. Kept below the client timeout so
            the server aborts and explains, rather than the client hanging up on live work.
          * One clause per (tag, element type) pair inside a union `( ... )`. Overpass has no
            "any of these tags" operator across differing keys, so the union is how a
            multi-tag search is expressed.
          * `out center tags;` — `center` gives ways and relations a single representative
            coordinate, which is what the CRM's `latitude`/`longitude` columns want; without
            it a way comes back as a list of node references and has no usable point.
        """
        radius_m = int(round(max(0.0, radius_km) * _KM_TO_M))
        server_timeout = int(settings.OVERPASS_QUERY_TIMEOUT_SECONDS)

        clauses: list[str] = []
        for key, value in _PHOTOGRAPHY_FILTERS:
            for element_type in _ELEMENT_TYPES:
                clauses.append(
                    f'  {element_type}["{key}"="{value}"]'
                    f'(around:{radius_m},{latitude},{longitude});'
                )

        body = "\n".join(clauses)
        return (
            f"[out:json][timeout:{server_timeout}];\n"
            f"(\n{body}\n);\n"
            f"out center tags;"
        )

    # -----------------------------------------------------------------------------------
    # HTTP with rate limiting and exponential backoff
    # -----------------------------------------------------------------------------------

    async def _request_with_retry(
        self,
        client: Any,
        httpx: Any,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """
        Performs one rate-limited request with retries and exponential backoff, returning the
        decoded JSON body.

        The retry policy, and why each part is there:

          * **Retryable statuses only** (`_RETRYABLE_STATUS_CODES`). 429 and 504 are how
            Overpass says "busy, come back"; retrying them is the documented correct
            response. A 400 or 403 is a malformed query or a block — retrying those adds load
            to an endpoint that has already given its final answer, so they fail immediately.
          * **Transport errors retry too.** A dropped connection to a shared public endpoint
            is far more often transient than terminal.
          * **`Retry-After` wins over the computed backoff** when the server sends it. The
            server knows when it will be ready and we do not; ignoring an explicit instruction
            is exactly the behaviour that gets a client blocked.
          * **Exponential, capped.** Delay is `base * 2**attempt`, capped at
            `OVERPASS_BACKOFF_MAX_SECONDS` so growth cannot park an import for minutes.
          * **No sleep after the final attempt.** Waiting 8 seconds only to give up is pure
            latency for the operator.

        The rate limiter wraps each attempt in `try/finally`, so a raising attempt still
        releases the lock — otherwise one timeout would deadlock every later import running
        through this provider instance.

        Raises:
            ProviderCollectionError: every attempt failed, or the body was not JSON.
        """
        max_retries = max(0, int(settings.OVERPASS_MAX_RETRIES))
        base_delay = float(settings.OVERPASS_BACKOFF_BASE_SECONDS)
        max_delay = float(settings.OVERPASS_BACKOFF_MAX_SECONDS)
        last_error = "no attempt was made"

        for attempt in range(max_retries + 1):
            is_final = attempt == max_retries

            await self._rate_limiter.acquire()
            try:
                if method.upper() == "POST":
                    response = await client.post(url, data=data)
                else:
                    response = await client.get(url, params=params)
            except Exception as exc:  # noqa: BLE001 - transport faults are retryable
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Overpass request to %s failed on attempt %d/%d: %s",
                    url, attempt + 1, max_retries + 1, last_error,
                )
                if is_final:
                    break
                await self._sleep_backoff(attempt, base_delay, max_delay, None)
                continue
            finally:
                self._rate_limiter.release()

            status_code = response.status_code

            if status_code in _RETRYABLE_STATUS_CODES:
                last_error = f"HTTP {status_code}"
                retry_after = self._parse_retry_after(response)
                logger.warning(
                    "Overpass returned %s on attempt %d/%d%s.",
                    status_code, attempt + 1, max_retries + 1,
                    f"; Retry-After {retry_after}s" if retry_after else "",
                )
                if is_final:
                    break
                await self._sleep_backoff(attempt, base_delay, max_delay, retry_after)
                continue

            if status_code >= 400:
                # Terminal by design — see the docstring on why these are not retried.
                raise ProviderCollectionError(
                    f"Overpass request to {url} was rejected with HTTP {status_code}. "
                    f"This is not a transient error and was not retried."
                )

            try:
                return response.json()
            except Exception as exc:  # noqa: BLE001 - a non-JSON body is a source-level fault
                raise ProviderCollectionError(
                    f"Overpass returned an unreadable (non-JSON) response from {url}: {exc}"
                ) from exc

        raise ProviderCollectionError(
            f"Overpass request to {url} failed after {max_retries + 1} attempts "
            f"(last error: {last_error}). The public endpoint may be rate limiting or "
            f"overloaded; try again shortly or configure a dedicated instance."
        )

    async def _sleep_backoff(
        self, attempt: int, base_delay: float, max_delay: float, retry_after: float | None
    ) -> None:
        """
        Waits before the next attempt: the server's `Retry-After` when it gave one, otherwise
        `base * 2**attempt`, capped either way at `OVERPASS_BACKOFF_MAX_SECONDS`.
        """
        if retry_after is not None:
            delay = min(retry_after, max_delay)
        else:
            delay = min(base_delay * (2 ** attempt), max_delay)
        if delay > 0:
            logger.info("Backing off %.1fs before Overpass retry %d.", delay, attempt + 2)
            await asyncio.sleep(delay)

    @staticmethod
    def _parse_retry_after(response: Any) -> float | None:
        """
        Reads a `Retry-After` header as seconds, or None when absent or in the HTTP-date form
        this adapter does not attempt to parse (Overpass sends the seconds form).
        """
        try:
            raw = response.headers.get("Retry-After")
        except Exception:  # noqa: BLE001 - a stub response may not carry headers
            return None
        if not raw:
            return None
        try:
            seconds = float(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return seconds if seconds >= 0 else None

    # -----------------------------------------------------------------------------------
    # normalize()
    # -----------------------------------------------------------------------------------

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        """
        Maps one raw OSM element onto the uniform `NormalizedLead` shape.

        Pure and offline: it takes the dict `collect()` built and touches nothing external,
        which is what makes the whole mapping — tag preference, multi-value splitting, address
        assembly, the way/relation `center` fallback — testable without a network.

        Never raises. An element it cannot make sense of comes back missing the fields
        `is_valid()` requires, which the import service counts and logs as one failed record.

        Two mappings deserve note:

        *Address.* OSM has no formatted-address field, so a displayable line is assembled from
        the `addr:*` parts in written order. When an element carries none of them the address
        falls back to the element's own `addr:full`, and failing that stays None — a fabricated
        address would be worse than none, since it would be shown to an operator as fact.

        *City.* Falls back to the searched city when the element carries no `addr:city`. That
        is sound here in a way it would not be for a general geocoder: every element in the
        result set is by construction within `radius_km` of that city's centre. Without it,
        the business-name+city duplicate key cannot be produced at all, so the same studio
        re-collected next month would import a second time.
        """
        element = raw.get("element") or {}
        tags = element.get("tags") or {}

        phones: list[str] = []
        for key in _PHONE_KEYS:
            for candidate in _split_multi(tags.get(key)):
                if candidate not in phones:
                    phones.append(candidate)

        emails: list[str] = []
        for key in _EMAIL_KEYS:
            for candidate in _split_multi(tags.get(key)):
                if candidate not in emails:
                    emails.append(candidate)

        latitude, longitude = self._coordinates(element)

        lead = NormalizedLead(
            business_name=_first_tag(tags, _NAME_KEYS),
            # OSM's `operator` tag names the operating company, not a contact person, and is
            # already used as a name fallback above. Left None rather than guessed at, so
            # enrichment never overwrites a real contact name a human typed.
            owner_name=None,
            phone_numbers=phones,
            emails=emails,
            website=_first_tag(tags, _WEBSITE_KEYS),
            address=self._build_address(tags),
            city=_first_tag(tags, _CITY_KEYS) or raw.get("search_city"),
            district=_first_tag(tags, _DISTRICT_KEYS),
            state=_first_tag(tags, _STATE_KEYS) or raw.get("search_state"),
            country=_first_tag(tags, _COUNTRY_KEYS) or "India",
            pincode=_first_tag(tags, _POSTCODE_KEYS),
            latitude=latitude,
            longitude=longitude,
            # OSM carries no ratings or review counts at all — it is a geographic database,
            # not a review site. Left None rather than invented; the CRM treats both as
            # optional enrichment.
            rating=None,
            review_count=None,
            source=self.lead_source,
            source_url=self._osm_url(element),
            categories=self._categories(tags, raw.get("search_category")),
            raw=raw,
        )
        return lead.normalize()

    @staticmethod
    def _coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
        """
        Reads an element's representative point.

        A `node` carries `lat`/`lon` directly. A `way` or `relation` has no single point, so
        the query asks for `out center` and Overpass supplies a computed `center` object —
        this is why the query cannot be simplified to a bare `out;`. Returns `(None, None)`
        when neither is present; `NormalizedLead.normalize` range-checks whatever comes back.
        """
        if element.get("lat") is not None and element.get("lon") is not None:
            return element.get("lat"), element.get("lon")
        center = element.get("center") or {}
        return center.get("lat"), center.get("lon")

    @staticmethod
    def _build_address(tags: dict[str, Any]) -> str | None:
        """
        Assembles a displayable address line from OSM's separate `addr:*` parts, in the order
        an Indian address is written, then appends city / state / postcode.

        Duplicate segments are dropped case-insensitively: an element tagged with both
        `addr:suburb` and `addr:city` holding the same value is common, and "Kozhikode,
        Kozhikode, Kerala" reads as a data error to the operator reading the call list.
        """
        parts: list[str] = []
        for key in _ADDRESS_PART_KEYS + _CITY_KEYS[:1] + _DISTRICT_KEYS[:1] + _STATE_KEYS[:1]:
            value = tags.get(key)
            text = str(value).strip() if value is not None else ""
            if text and text.lower() not in {p.lower() for p in parts}:
                parts.append(text)

        postcode = _first_tag(tags, _POSTCODE_KEYS)
        if postcode:
            parts.append(postcode)

        if parts:
            return ", ".join(parts)
        # Some contributors write the whole address into one tag instead.
        return _first_tag(tags, ("addr:full", "address"))

    @staticmethod
    def _osm_url(element: dict[str, Any]) -> str | None:
        """
        Builds the canonical openstreetmap.org link for an element, so an operator can click
        through and verify — or correct — the listing they are being asked to call.
        """
        element_type = element.get("type")
        element_id = element.get("id")
        if not element_type or element_id is None:
            return None
        return f"https://www.openstreetmap.org/{element_type}/{element_id}"

    @staticmethod
    def _categories(tags: dict[str, Any], requested: str | None) -> list[str]:
        """
        Renders the element's photography tags into readable category tags
        (`craft=photographer` -> "Photographer"), prefixed by the operator's requested
        category when they gave one.

        Only the tags this provider actually queried on are rendered. An OSM element carries
        many incidental tags (`building`, `wheelchair`, `opening_hours`) which say nothing
        about what the business does and would crowd out the useful entries in the lead's
        remarks — the same reasoning that dropped Google's structural `types`.
        """
        categories: list[str] = []
        requested_text = (requested or "").strip()
        if requested_text:
            categories.append(requested_text)

        for key, value in _PHOTOGRAPHY_FILTERS:
            if str(tags.get(key) or "").strip().lower() == value:
                label = value.replace("_", " ").title()
                if label.lower() not in {c.lower() for c in categories}:
                    categories.append(label)
        return categories

    # -----------------------------------------------------------------------------------
    # Extras
    # -----------------------------------------------------------------------------------

    @staticmethod
    def opening_hours(raw: dict[str, Any]) -> list[str]:
        """
        Extracts an element's `opening_hours` tag from a raw collected record.

        Exposed as a helper rather than folded into `NormalizedLead` for the same reason as
        the Google adapter's namesake: the DTO has no opening-hours field and the `leads`
        table has no column for one, and widening a shared contract for one provider's
        convenience is what this engine's design avoids. The value is retained on `raw`, so it
        is visible in the job diagnostics and available to any later phase that gives it a
        column.

        Returned as a single-element list to match the Google adapter's signature, since OSM
        encodes the whole week in one opaque string ("Mo-Sa 09:00-20:00").
        """
        tags = (raw.get("element") or {}).get("tags") or {}
        value = _first_tag(tags, ("opening_hours", "opening_hours:covid19"))
        return [value] if value else []
