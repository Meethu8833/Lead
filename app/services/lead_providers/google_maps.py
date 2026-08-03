"""
app/services/lead_providers/google_maps.py

This file implements `GoogleMapsLeadProvider` — the adapter that collects photography
businesses from Google Maps via the official Google Places API.

It is the first *network-bound* adapter in the Lead Collection Engine, and it is an adapter
in the strict sense: it knows how to talk to Google and how to shape Google's JSON into a
`NormalizedLead`, and it knows nothing else. Lead creation, deduplication, enrichment, audit
logging and job statistics all remain in `LeadImportService`, exactly as they are for the
CSV and mock providers. Swapping this provider out changes nothing downstream.

Why two API calls per business
------------------------------
Google's Text Search endpoint answers "what places match 'Wedding Photographer Thrissur'"
but returns neither a phone number nor a website — and a lead without a phone number is
rejected by `NormalizedLead.is_valid()`, so a Text-Search-only adapter would produce a run
where every record failed. Phone, website, opening hours and the address components we split
into city/district/state/pincode come only from Place Details, which is a second call keyed
by `place_id`.

That makes collection N+1 calls for N businesses, which is the actual cost driver here:
Details is billed per call. Three things follow, and they are the main design decisions in
this file:

  * `context.limit` is honoured *before* the Details fan-out, so an operator asking for 20
    businesses is billed for 20 Details calls, not for the 60 that Text Search would happily
    paginate to.
  * Details calls are bounded-concurrency (`_DETAILS_CONCURRENCY`) rather than sequential,
    because 20 sequential round-trips to Google inside a synchronous HTTP request is the
    difference between a 2-second import and a 30-second one.
  * `GOOGLE_MAPS_FETCH_DETAILS=False` turns the fan-out off entirely for an operator who
    wants a cheap survey of what exists and accepts that most records will fail for want of
    a phone number.

The failure contract, and why it is the whole point
---------------------------------------------------
`ProviderCollectionError` is raised **only** for faults that invalidate the entire run: a
missing or rejected API key, a quota denial, an unreachable host. Everything that can go
wrong with a single business — a Details call that times out, a malformed address, a place
that turns out to have no phone — degrades that one record and never the run. A Details
failure is not even a failed record: the Text Search half of that business is still a real
listing, so it is kept with a `detail_error` breadcrumb in `raw` and simply lacks the fields
Details would have supplied. It then fails validation on its own merits (no phone) and is
counted and logged by the import service like any other unusable record.

This is why `_fetch_details` returns `(payload, error)` instead of raising: at the point of
failure we do not yet know whether the record is salvageable, and deciding that here would
duplicate a judgement the engine already makes.

Configuration
-------------
Every knob lives in `app/core/config.py` and is read from the environment. No key, URL or
tuning constant is hardcoded, and `is_available` is computed from whether a key is actually
configured — so an unconfigured deployment gets the same clear "declared but not runnable"
400 that a `PlannedProvider` gives, rather than a 403 from Google halfway through a run.
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


#: Google returns 20 results per Text Search page and requires a short delay before a
#: `next_page_token` becomes valid. This is Google's own documented behaviour, not a guess:
#: querying too early returns INVALID_REQUEST.
_PAGE_TOKEN_DELAY_SECONDS = 2.0

#: Number of Place Details calls in flight at once. Bounded so a 60-result run does not open
#: 60 concurrent sockets to Google and trip per-second quota limits.
_DETAILS_CONCURRENCY = 5

#: Fields requested from Place Details. Google bills Details by field group, so asking for
#: exactly what maps onto a `NormalizedLead` — and nothing more — is a direct cost decision.
_DETAIL_FIELDS = ",".join([
    "place_id",
    "name",
    "formatted_address",
    "address_components",
    "formatted_phone_number",
    "international_phone_number",
    "website",
    "url",
    "rating",
    "user_ratings_total",
    "types",
    "geometry/location",
    "opening_hours/weekday_text",
    "business_status",
])

#: Google `status` values that mean the whole run is doomed, mapped to an operator-readable
#: explanation. Anything not listed here is treated as a per-request problem instead.
_FATAL_STATUSES: dict[str, str] = {
    "REQUEST_DENIED": (
        "Google rejected the request. The API key is missing, invalid, or the Places API "
        "is not enabled for it."
    ),
    "OVER_QUERY_LIMIT": (
        "Google's query quota for this API key is exhausted. Check billing and quota limits "
        "in the Google Cloud console."
    ),
}

#: Google `address_component` type -> `NormalizedLead` field. Google returns a flat list of
#: typed components rather than a structured address, so this is how a formatted address is
#: split into the CRM's city / district / state / pincode columns.
#:
#: `locality` is the city. `administrative_area_level_2` is the district (Google's own
#: modelling of Indian districts — "Kozhikode" the district vs "Kozhikode" the city), and
#: `administrative_area_level_1` is the state. The fallbacks matter in practice: many Kerala
#: studios sit in a `sublocality` or a `postal_town` rather than a `locality`, and taking no
#: city at all would silently disable the business-name+city duplicate rule for them.
_CITY_TYPES = ("locality", "postal_town", "sublocality_level_1", "sublocality")
_DISTRICT_TYPES = ("administrative_area_level_2",)
_STATE_TYPES = ("administrative_area_level_1",)
_PINCODE_TYPES = ("postal_code",)
_COUNTRY_TYPES = ("country",)

#: Business statuses worth importing. A permanently closed studio is not a lead, and
#: importing one wastes an operator's call. Google omits this field on some records, which
#: is treated as operational rather than assumed closed.
_SKIP_BUSINESS_STATUSES = frozenset({"CLOSED_PERMANENTLY"})


def _first_component(
    components: Sequence[dict[str, Any]], wanted_types: Sequence[str]
) -> str | None:
    """
    Returns the long name of the first address component matching any of `wanted_types`.

    Types are tried in the order given rather than all at once, so the caller's preference
    order is honoured — `locality` beats `sublocality` when a record carries both, which is
    the difference between a city of "Kozhikode" and a city of "West Hill".
    """
    for wanted in wanted_types:
        for component in components or []:
            if wanted in (component.get("types") or []):
                name = (component.get("long_name") or component.get("short_name") or "").strip()
                if name:
                    return name
    return None


@register_provider
class GoogleMapsLeadProvider(LeadProvider):
    """
    Adapter that collects photography businesses from the Google Places API.

    Collection is a Text Search (paginated, up to Google's 3-page ceiling) followed by one
    Place Details call per retained result. Both halves are merged into a single raw record,
    which `normalize()` then maps onto `NormalizedLead`.

    The instance holds no run state: the query, limit and geographic scope all travel on the
    `ProviderContext`, so one instance is safe to reuse across concurrent imports.
    """

    key = "google_maps"
    display_name = "Google Maps"
    lead_source = "GOOGLE_MAPS"
    requires_query = True
    requires_file = False

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """
        Args:
            api_key / base_url: Explicit overrides for the configured values. These exist so
                a test can drive the adapter against a stub server; production construction
                (via the registry, which takes no arguments) always reads settings.
        """
        self._api_key = api_key if api_key is not None else settings.GOOGLE_MAPS_API_KEY
        self._base_url = (base_url or settings.GOOGLE_MAPS_BASE_URL).rstrip("/")

    # -----------------------------------------------------------------------------------
    # Availability
    # -----------------------------------------------------------------------------------

    @property
    def is_available(self) -> bool:  # type: ignore[override]
        """
        Reports whether this adapter can actually run, which for a keyed API means "is a key
        configured".

        Computed rather than a class constant because availability is a deployment fact, not
        a code fact: the same build is unavailable in a dev environment with no key and
        available in production. `LeadProvider.search` already refuses when this is False, so
        an unconfigured deployment produces a clear 400 at request time instead of a 403 from
        Google partway through a run that has already been marked RUNNING.
        """
        return bool((self._api_key or "").strip())

    @property
    def unavailable_reason(self) -> str:
        """
        States the actual fix — set a key — rather than the base class's "not yet
        implemented", which would send an operator looking for a missing feature when the
        provider is fully built and merely unconfigured.
        """
        return (
            "Google Maps lead collection is not configured: GOOGLE_MAPS_API_KEY is unset. "
            "Set it in the environment to enable this provider."
        )

    # -----------------------------------------------------------------------------------
    # search()
    # -----------------------------------------------------------------------------------

    def search(self, query: str | None = None, **kwargs: Any) -> ProviderContext:
        """
        Validates a Google Maps collection request and returns its run context.

        Beyond the shared checks in `LeadProvider.search` (availability, non-empty query,
        limit bounds), this composes `city` and `state` into the query text when they are
        supplied and not already present. Places has no separate locality parameter for Text
        Search — location scope is expressed in the query string itself — so "Photographer"
        with city "Kozhikode" must become "Photographer Kozhikode" to search what the
        operator meant.

        The substring guard keeps "Photographer Kozhikode" with city "Kozhikode" from
        becoming "Photographer Kozhikode Kozhikode", which measurably degrades Google's
        matching.

        Raises:
            BadRequestException: the request cannot be serviced — no API key configured, no
                query, or an out-of-range limit.
        """
        context = super().search(query, **kwargs)

        terms: list[str] = [context.query or ""]
        for scope in (context.city, context.state):
            cleaned = (scope or "").strip()
            if cleaned and cleaned.lower() not in (context.query or "").lower():
                terms.append(cleaned)
        context.query = " ".join(term for term in terms if term).strip()

        if not context.query:
            raise BadRequestException(
                f"Provider '{self.key}' requires a non-empty search query."
            )
        return context

    # -----------------------------------------------------------------------------------
    # collect()
    # -----------------------------------------------------------------------------------

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        """
        Collects raw business records for the context's query.

        Runs Text Search (walking `next_page_token` up to the configured page ceiling or
        `context.limit`, whichever binds first), drops permanently-closed businesses, then
        enriches the retained results with Place Details concurrently.

        Returns raw merged dicts — deliberately un-normalized, so `normalize()` stays a pure
        mapping that can be tested without a network, and so the untouched Google payload
        travels with the record for diagnosis.

        Raises:
            ProviderCollectionError: a run-level fault — no API key, `httpx` unavailable,
                Google unreachable, credentials rejected, or quota exhausted.
        """
        if not self.is_available:
            raise ProviderCollectionError(
                "GOOGLE_MAPS_API_KEY is not configured, so Google Maps collection cannot run."
            )

        httpx = self._import_httpx()

        timeout = httpx.Timeout(settings.GOOGLE_MAPS_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                places = await self._text_search(client, context)

                # Drop closed businesses before spending a Details call on them.
                open_places = [
                    place for place in places
                    if (place.get("business_status") or "") not in _SKIP_BUSINESS_STATUSES
                ]

                # Honour the limit BEFORE the Details fan-out — this is the billing decision
                # documented in the module docstring.
                selected = open_places[: context.limit]

                if settings.GOOGLE_MAPS_FETCH_DETAILS:
                    return await self._enrich_with_details(client, selected)
                return [{"search": place, "details": None} for place in selected]

        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport fault is a run-level fault
            logger.exception("Google Maps collection failed for query %r.", context.query)
            raise ProviderCollectionError(
                f"Google Maps collection failed: {exc}"
            ) from exc

    @staticmethod
    def _import_httpx() -> Any:
        """
        Imports `httpx` lazily, converting an absent dependency into a run-level provider
        error rather than an import-time crash.

        Deferred deliberately: `app/services/lead_providers/__init__.py` imports this module
        at startup for its registration side effect, so a top-level `import httpx` would take
        the entire API down on a deployment that never uses this provider. This mirrors the
        deferred-import discipline already used for optional integrations.
        """
        try:
            import httpx  # noqa: PLC0415 - deferred on purpose, see docstring
        except ImportError as exc:  # pragma: no cover - depends on the deployment image
            raise ProviderCollectionError(
                "The 'httpx' package is required for Google Maps collection but is not "
                "installed. Install it with: pip install httpx"
            ) from exc
        return httpx

    async def _text_search(
        self, client: Any, context: ProviderContext
    ) -> list[dict[str, Any]]:
        """
        Runs Text Search and walks its pagination, returning the raw place summaries.

        Stops as soon as `context.limit` results are in hand, the page ceiling is reached, or
        Google stops issuing a `next_page_token`. Duplicate `place_id`s across pages are
        dropped: Google occasionally repeats a result between pages, and letting that through
        would show up as a within-batch duplicate in the job log rather than being recognised
        as the API artefact it is.
        """
        collected: list[dict[str, Any]] = []
        seen_place_ids: set[str] = set()
        page_token: str | None = None
        max_pages = max(1, settings.GOOGLE_MAPS_MAX_PAGES)

        for page in range(max_pages):
            params: dict[str, Any] = {"key": self._api_key}
            if page_token:
                # Google requires a brief pause before a next_page_token becomes valid.
                await asyncio.sleep(_PAGE_TOKEN_DELAY_SECONDS)
                params["pagetoken"] = page_token
            else:
                params["query"] = context.query
                params["region"] = settings.GOOGLE_MAPS_REGION
                params["language"] = settings.GOOGLE_MAPS_LANGUAGE

            payload = await self._request(client, "textsearch/json", params)
            status = payload.get("status") or ""

            if status == "ZERO_RESULTS":
                # A query that matches nothing is a correct, successful answer — the import
                # service records it as a COMPLETED run with zero records.
                break
            self._raise_if_fatal(status, payload)
            if status != "OK":
                logger.warning(
                    "Google Text Search returned status %s on page %d: %s",
                    status, page + 1, payload.get("error_message"),
                )
                break

            for place in payload.get("results") or []:
                place_id = place.get("place_id")
                if place_id and place_id in seen_place_ids:
                    continue
                if place_id:
                    seen_place_ids.add(place_id)
                collected.append(place)

            if len(collected) >= context.limit:
                break

            page_token = payload.get("next_page_token")
            if not page_token:
                break

        return collected

    async def _enrich_with_details(
        self, client: Any, places: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Fetches Place Details for every place, concurrently but bounded, and merges each
        result with its search summary.

        A Details failure degrades exactly one record: the search half is retained and the
        reason is recorded in `raw["detail_error"]`, so the operator can see in the job log
        why that business arrived without a phone number. Ordering is preserved so the job
        log's record numbers correspond to Google's own relevance ranking.
        """
        semaphore = asyncio.Semaphore(_DETAILS_CONCURRENCY)

        async def fetch(place: dict[str, Any]) -> dict[str, Any]:
            place_id = place.get("place_id")
            if not place_id:
                return {
                    "search": place,
                    "details": None,
                    "detail_error": "Google returned no place_id for this result.",
                }
            async with semaphore:
                details, error = await self._fetch_details(client, place_id)
            record: dict[str, Any] = {"search": place, "details": details}
            if error:
                record["detail_error"] = error
            return record

        # `gather` preserves input order, which is what keeps job-log record numbers aligned
        # with Google's ranking. `return_exceptions` guards the contract that no single
        # business can abort the batch even if `fetch` itself fails unexpectedly.
        results = await asyncio.gather(
            *(fetch(place) for place in places), return_exceptions=True
        )

        merged: list[dict[str, Any]] = []
        for place, result in zip(places, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Place Details failed for %r: %s", place.get("name"), result
                )
                merged.append({
                    "search": place,
                    "details": None,
                    "detail_error": f"Place Details lookup failed: {result}",
                })
            else:
                merged.append(result)
        return merged

    async def _fetch_details(
        self, client: Any, place_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Fetches one place's details, returning `(payload, error)`.

        Returns rather than raises for a per-place problem, because at this point we cannot
        yet tell whether the record is salvageable — that judgement belongs to the import
        service's validity check. A *fatal* status (rejected key, exhausted quota) is
        re-raised, since it will apply identically to every remaining place and failing 200
        times in a row is strictly worse than failing once.
        """
        params = {
            "key": self._api_key,
            "place_id": place_id,
            "fields": _DETAIL_FIELDS,
            "language": settings.GOOGLE_MAPS_LANGUAGE,
        }
        try:
            payload = await self._request(client, "details/json", params)
        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - per-place isolation, see docstring
            return None, f"Place Details request failed: {exc}"

        status = payload.get("status") or ""
        self._raise_if_fatal(status, payload)
        if status != "OK":
            return None, (
                f"Place Details returned status {status}"
                + (f": {payload['error_message']}" if payload.get("error_message") else "")
            )
        return payload.get("result") or {}, None

    async def _request(
        self, client: Any, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Performs one GET against the Places API and returns its decoded JSON body.

        HTTP-level failures are raised as `ProviderCollectionError`: a 5xx or an unparseable
        body from Google is not something a single record can be blamed for, and the caller
        decides whether to contain it (`_fetch_details` does, for one place) or let it fail
        the run (`_text_search` does, since without search results there is no run).
        """
        url = f"{self._base_url}/{path}"
        response = await client.get(url, params=params)

        if response.status_code >= 400:
            raise ProviderCollectionError(
                f"Google Places API returned HTTP {response.status_code} for {path}."
            )
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - a non-JSON body is a source-level fault
            raise ProviderCollectionError(
                f"Google Places API returned an unreadable response for {path}: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderCollectionError(
                f"Google Places API returned an unexpected payload shape for {path}."
            )
        return payload

    @staticmethod
    def _raise_if_fatal(status: str, payload: dict[str, Any]) -> None:
        """
        Converts a run-invalidating Google status into `ProviderCollectionError`.

        Only credential and quota failures qualify (see `_FATAL_STATUSES`). `NOT_FOUND` and
        `ZERO_RESULTS` are ordinary per-request outcomes and must not fail a run.
        """
        explanation = _FATAL_STATUSES.get(status)
        if not explanation:
            return
        detail = payload.get("error_message")
        raise ProviderCollectionError(
            f"{explanation}" + (f" Google said: {detail}" if detail else "")
        )

    # -----------------------------------------------------------------------------------
    # normalize()
    # -----------------------------------------------------------------------------------

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        """
        Maps one merged Google record onto the uniform `NormalizedLead` shape.

        Pure and offline: it takes the dict `collect()` built and touches nothing external,
        which is what makes the whole mapping — address splitting, phone ordering, opening
        hours — testable without an API key.

        Details values win over Text Search values where both exist, because Details is the
        authoritative, per-place payload while the search summary is a ranked-list
        projection. Where Details is missing (a failed lookup, or the fetch disabled), the
        search half still supplies name, address, rating and coordinates — so the record is
        as complete as it can be rather than empty.

        Never raises: a record it cannot make sense of comes back missing the fields
        `is_valid()` requires, which the import service counts and logs as one failed record.
        """
        search = raw.get("search") or {}
        details = raw.get("details") or {}

        components = details.get("address_components") or []

        # International form first: it carries the +91 country code, which is the form the
        # CRM's phone normalisation collapses most reliably and the form an operator can dial
        # from anywhere. The national form follows as the second number when it is genuinely
        # different, so a business is never reduced to one contact route by our formatting
        # preference alone.
        phones: list[str] = []
        for candidate in (
            details.get("international_phone_number"),
            details.get("formatted_phone_number"),
        ):
            if candidate and candidate not in phones:
                phones.append(candidate)

        maps_url = details.get("url") or self._maps_url_for(search.get("place_id"))

        lead = NormalizedLead(
            business_name=details.get("name") or search.get("name"),
            # Google Places exposes no owner/contact person for a business listing. Left
            # None rather than guessed at, so `_build_enrichment` never overwrites a real
            # contact name a human typed with something derived from a business name.
            owner_name=None,
            phone_numbers=phones,
            # Places does not return email addresses at all. The field stays empty rather
            # than being scraped from the website, which would be a different integration
            # with different consent implications.
            emails=[],
            website=details.get("website"),
            address=(
                details.get("formatted_address")
                or search.get("formatted_address")
                or search.get("vicinity")
            ),
            city=_first_component(components, _CITY_TYPES),
            district=_first_component(components, _DISTRICT_TYPES),
            state=_first_component(components, _STATE_TYPES),
            country=_first_component(components, _COUNTRY_TYPES),
            pincode=_first_component(components, _PINCODE_TYPES),
            latitude=self._coordinate(details, search, "lat"),
            longitude=self._coordinate(details, search, "lng"),
            rating=details.get("rating", search.get("rating")),
            review_count=details.get(
                "user_ratings_total", search.get("user_ratings_total")
            ),
            source=self.lead_source,
            source_url=maps_url,
            categories=self._categories(details, search),
            raw=raw,
        )

        normalized = lead.normalize()

        # City fallback: when Google returns no `locality` component (common for listings
        # placed on a highway or in an unincorporated area), derive it from the formatted
        # address. Without a city the business-name+city duplicate rule cannot produce a key
        # at all, so the same studio re-collected next month would import a second time.
        if not normalized.city:
            derived = self._city_from_address(normalized.address)
            if derived:
                normalized.city = derived

        return normalized

    @staticmethod
    def _maps_url_for(place_id: str | None) -> str | None:
        """
        Builds the canonical Google Maps link for a place when Details did not supply one,
        so an operator can always click through to verify the listing they are being asked
        to call.
        """
        if not place_id:
            return None
        return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    @staticmethod
    def _coordinate(
        details: dict[str, Any], search: dict[str, Any], axis: str
    ) -> float | None:
        """
        Reads one geometry axis, preferring Details over the search summary. Returns None if
        neither carries it; `NormalizedLead.normalize` range-checks whatever comes back.
        """
        for source in (details, search):
            location = ((source.get("geometry") or {}).get("location") or {})
            value = location.get(axis)
            if value is not None:
                return value
        return None

    @staticmethod
    def _categories(details: dict[str, Any], search: dict[str, Any]) -> list[str]:
        """
        Renders Google's `types` into readable category tags ("wedding_photographer" ->
        "Wedding Photographer").

        Google's structural types carry no information about what the business does and
        would crowd out the useful tags in the lead's remarks, so they are dropped.
        """
        raw_types = details.get("types") or search.get("types") or []
        skip = {"point_of_interest", "establishment", "store", "food"}
        return [
            str(value).replace("_", " ").title()
            for value in raw_types
            if value and value not in skip
        ]

    @staticmethod
    def _city_from_address(address: str | None) -> str | None:
        """
        Derives a city from a formatted Indian address as a last resort.

        Indian formatted addresses end "..., City, State PIN, India", so the city is the
        segment two before the country, or the one before a "State 560001" segment. Returns
        None when the shape does not match rather than guessing — a wrong city creates false
        duplicate matches, which is worse than having no city at all.
        """
        if not address:
            return None
        parts = [part.strip() for part in address.split(",") if part.strip()]
        if len(parts) < 3:
            return None
        # Drop a trailing country segment.
        if parts[-1].lower() in {"india", "in"}:
            parts = parts[:-1]
        if len(parts) < 2:
            return None
        # The last remaining segment is typically "Kerala 673001"; the city precedes it.
        if re.search(r"\d{6}", parts[-1]):
            candidate = parts[-2]
        else:
            candidate = parts[-1]
        candidate = re.sub(r"\s*\d{6}\s*", "", candidate).strip()
        # A segment that is only digits or a fragment is not a city name.
        if not candidate or len(candidate) < 3 or candidate.isdigit():
            return None
        return candidate

    # -----------------------------------------------------------------------------------
    # Opening hours
    # -----------------------------------------------------------------------------------

    @staticmethod
    def opening_hours(raw: dict[str, Any]) -> list[str]:
        """
        Extracts a place's weekday opening-hours lines from a raw collected record.

        Exposed as a helper rather than folded into `NormalizedLead` because the DTO has no
        opening-hours field and the `leads` table has no column for one. Adding either would
        widen a shared contract for a single provider's convenience, which the collection
        engine's design explicitly avoids — the same reasoning that put `rating`,
        `review_count` and `categories` into the lead's `remarks` rather than into new
        columns.

        The hours are therefore collected and retained on the record's `raw` payload (so they
        are visible in the job's diagnostics and available to any later phase that gives them
        a column), and this helper is how a caller reads them back out. Promoting them to a
        queryable field is listed as a follow-up in task.md.
        """
        details = raw.get("details") or {}
        hours = (details.get("opening_hours") or {}).get("weekday_text") or []
        return [str(line) for line in hours if line]
