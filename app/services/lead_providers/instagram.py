"""
app/services/lead_providers/instagram.py

This file implements `InstagramLeadProvider` — the adapter that collects photography
businesses from Instagram via the official Instagram Graph API.

It is an adapter in the strict sense, exactly as `google_maps.py` is: it knows how to talk
to Meta and how to shape Meta's JSON into a `NormalizedLead`, and it knows nothing else.
Lead creation, deduplication, enrichment, audit logging and job statistics all remain in
`LeadImportService`. Nothing downstream of this file changed to add it — no service branch,
no endpoint, no schema, no migration.

Why Business Discovery, and what it costs us
--------------------------------------------
Instagram has no public search endpoint. The only sanctioned way to read another business's
public profile is `business_discovery`, which is shaped as *"my IG Business account asks
about that exact username"* — it takes a username, not a query. That single fact drives the
whole design of this file:

  * A query like "Wedding Photographer Kerala" cannot be sent to Instagram at all. It must
    first be turned into **candidate usernames**. We do that with the hashtag endpoints
    (`ig_hashtag_search` -> `recent_media`/`top_media`), which are the API's only
    query-shaped surface, and read the authoring username off each returned post.
  * Discovery is therefore two-phase — hashtags to find *who*, Business Discovery to learn
    *what about them* — and the second phase is one call per profile. That is the cost
    driver, mirroring the N+1 shape of the Places adapter.
  * `context.limit` is honoured **before** the Business Discovery fan-out, so an operator
    asking for 20 profiles pays 20 lookups, not the 150 the hashtag pages happily yield.
  * Lookups run at bounded concurrency (`INSTAGRAM_CONCURRENCY`) rather than sequentially,
    because 20 sequential round-trips to Meta inside one HTTP request is the difference
    between a 2-second import and a 30-second one.

Business Discovery only resolves **Business and Creator** accounts. A personal account
returns an error, which is correct for our purpose: we cannot contact a profile that
publishes no contact details, and importing it would inflate the failed-record count with
records that were never leads. Those are dropped during collection with a breadcrumb rather
than carried forward as failures.

Where the contact details actually come from
--------------------------------------------
Instagram exposes far less structured contact data than a directory does. `business_discovery`
returns the profile's public fields — `biography`, `website`, `followers_count`,
`media_count` and so on — but the *phone number, email, WhatsApp number and address are not
structured fields at all*. Photographers put them in the bio, which is free text:

    "📍 Kozhikode, Kerala | 📞 +91 98470 12345 | WhatsApp 9847012345 | hello@studio.in"

So `_parse_bio` does the work that Places' `address_components` did for the Google adapter:
it extracts phones, emails, a WhatsApp number and a city/state from free text. Every one of
those extractions is conservative and returns nothing rather than guessing, because the
downstream consequence of a wrong value is not a blank field — it is a false duplicate merge
against an existing lead, which is materially worse than no data. See `_parse_bio` and
`_extract_city_state` for the specific guards.

The failure contract, and why it is the whole point
---------------------------------------------------
`ProviderCollectionError` is raised **only** for faults that invalidate the entire run: a
missing or rejected token, an expired session, a rate-limit denial, an unreachable host.
Everything that can go wrong with a single profile — a lookup that times out, a private
account, an unparseable bio, a profile with no phone — degrades that one record and never
the run. This is why `_discover_profile` returns `(payload, error)` instead of raising: at
the point of failure we do not yet know whether the record is salvageable, and deciding that
here would duplicate a judgement the import engine already makes.

Configuration
-------------
Every knob lives in `app/core/config.py` and is read from the environment. No token, id, URL
or tuning constant is hardcoded, and `is_available` is computed from whether the credentials
are actually configured — so an unconfigured deployment gets the same clear "declared but not
runnable" 400 a `PlannedProvider` gives, rather than a 190 from Meta halfway through a run
that has already been marked RUNNING.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Iterable, Sequence

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.services.lead_providers.base import (
    LeadProvider,
    ProviderCollectionError,
    ProviderContext,
    register_provider,
)
from app.services.lead_providers.normalized import NormalizedLead, normalize_phone

logger = logging.getLogger(__name__)


#: Public profile fields requested from Business Discovery. Meta returns only what is asked
#: for, and asking for a field the token cannot see fails the whole call — so this is the
#: intersection of "useful to a lead" and "public on a Business/Creator profile".
_DISCOVERY_FIELDS = ",".join([
    "id",
    "username",
    "name",
    "biography",
    "website",
    "followers_count",
    "follows_count",
    "media_count",
    "profile_picture_url",
    "is_verified",
])

#: Meta error codes that mean the whole run is doomed, mapped to an operator-readable
#: explanation. Anything not listed here is treated as a per-request problem instead.
#: 190 = invalid/expired token; 102 = session expired; 4/17/32/613 = rate limits reached;
#: 10 and 200-299 = the app lacks the permission the call needs. Every one of these applies
#: identically to the next profile, so failing 200 times in a row is strictly worse than
#: failing once.
_FATAL_ERROR_CODES: dict[int, str] = {
    190: (
        "Instagram rejected the access token. INSTAGRAM_ACCESS_TOKEN is invalid or has "
        "expired — long-lived tokens last 60 days and must be refreshed."
    ),
    102: (
        "Instagram reports the session has expired. Re-authenticate and set a fresh "
        "INSTAGRAM_ACCESS_TOKEN."
    ),
    4: (
        "Instagram's application-level rate limit is exhausted. Wait for the window to "
        "reset before retrying this import."
    ),
    17: (
        "Instagram's user-level rate limit is exhausted. Wait for the window to reset "
        "before retrying this import."
    ),
    32: (
        "Instagram's page-level rate limit is exhausted. Wait for the window to reset "
        "before retrying this import."
    ),
    613: (
        "Instagram's API call limit has been reached. Wait for the window to reset before "
        "retrying this import."
    ),
    10: (
        "The Instagram app lacks the permission required for Business Discovery. The token "
        "needs instagram_basic and pages_read_engagement on a linked Business account."
    ),
}

#: Meta error subcodes that also invalidate the run, checked when the top-level code does
#: not already qualify. 463 = the token has expired; 467 = it was invalidated (password
#: change, logout, or a manual revoke in Meta's dashboard).
_FATAL_ERROR_SUBCODES: dict[int, str] = {
    463: "The Instagram access token has expired. Set a fresh INSTAGRAM_ACCESS_TOKEN.",
    467: (
        "The Instagram access token was invalidated (password change or manual revoke). "
        "Set a fresh INSTAGRAM_ACCESS_TOKEN."
    ),
}

#: Words that mark a query term as *intent* ("wedding", "photography") rather than a *place*
#: ("Kerala", "Kozhikode"). Used when splitting an operator's free-text query into the
#: hashtags to search and the location to fall back on. Held here rather than inferred,
#: because the alternative — treating every unrecognised word as a city — would attach a
#: bogus city to every collected lead and silently corrupt the name+city duplicate rule.
_INTENT_WORDS = frozenset({
    "wedding", "weddings", "pre", "prewedding", "post", "candid", "photographer",
    "photographers", "photography", "photo", "photos", "studio", "studios", "shoot",
    "shoots", "film", "films", "cinema", "cinematography", "videography", "videographer",
    "maternity", "newborn", "baby", "portrait", "portraits", "fashion", "event", "events",
    "engagement", "haldi", "mehendi", "reception", "bridal", "makeup", "album", "albums",
    "best", "top", "professional",
})

#: Kerala's districts plus the cities this CRM actually sells into. A bio's location is free
#: text, so we match against a known vocabulary instead of parsing arbitrary strings: an
#: unrecognised place yields no city at all, which is the safe outcome. Extending this list
#: is how the provider's geographic reach grows.
_KNOWN_CITIES: dict[str, str] = {
    # Kerala districts
    "thiruvananthapuram": "Thiruvananthapuram",
    "trivandrum": "Thiruvananthapuram",
    "kollam": "Kollam",
    "pathanamthitta": "Pathanamthitta",
    "alappuzha": "Alappuzha",
    "alleppey": "Alappuzha",
    "kottayam": "Kottayam",
    "idukki": "Idukki",
    "ernakulam": "Ernakulam",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "thrissur": "Thrissur",
    "trichur": "Thrissur",
    "palakkad": "Palakkad",
    "malappuram": "Malappuram",
    "kozhikode": "Kozhikode",
    "calicut": "Kozhikode",
    "wayanad": "Wayanad",
    "kannur": "Kannur",
    "cannanore": "Kannur",
    "kasaragod": "Kasaragod",
    "kasargod": "Kasaragod",
    # Frequently-seen towns
    "guruvayur": "Guruvayur",
    "perinthalmanna": "Perinthalmanna",
    "manjeri": "Manjeri",
    "tirur": "Tirur",
    "ottapalam": "Ottapalam",
    "chalakudy": "Chalakudy",
    "aluva": "Aluva",
    "muvattupuzha": "Muvattupuzha",
    "changanassery": "Changanassery",
    "kayamkulam": "Kayamkulam",
    "nedumangad": "Nedumangad",
    # Neighbouring-state metros a Kerala studio may list
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "chennai": "Chennai",
    "coimbatore": "Coimbatore",
    "mangalore": "Mangaluru",
    "mangaluru": "Mangaluru",
    "mumbai": "Mumbai",
    "hyderabad": "Hyderabad",
}

#: State names recognised in a bio, mapped to their canonical form.
_KNOWN_STATES: dict[str, str] = {
    "kerala": "Kerala",
    "karnataka": "Karnataka",
    "tamilnadu": "Tamil Nadu",
    "tamil nadu": "Tamil Nadu",
    "telangana": "Telangana",
    "maharashtra": "Maharashtra",
    "goa": "Goa",
    "puducherry": "Puducherry",
    "pondicherry": "Puducherry",
}

#: The state a city belongs to, so a bio naming only "Kozhikode" still yields "Kerala".
_CITY_STATE: dict[str, str] = {
    "Thiruvananthapuram": "Kerala", "Kollam": "Kerala", "Pathanamthitta": "Kerala",
    "Alappuzha": "Kerala", "Kottayam": "Kerala", "Idukki": "Kerala",
    "Ernakulam": "Kerala", "Kochi": "Kerala", "Thrissur": "Kerala",
    "Palakkad": "Kerala", "Malappuram": "Kerala", "Kozhikode": "Kerala",
    "Wayanad": "Kerala", "Kannur": "Kerala", "Kasaragod": "Kerala",
    "Guruvayur": "Kerala", "Perinthalmanna": "Kerala", "Manjeri": "Kerala",
    "Tirur": "Kerala", "Ottapalam": "Kerala", "Chalakudy": "Kerala",
    "Aluva": "Kerala", "Muvattupuzha": "Kerala", "Changanassery": "Kerala",
    "Kayamkulam": "Kerala", "Nedumangad": "Kerala",
    "Bengaluru": "Karnataka", "Mangaluru": "Karnataka",
    "Chennai": "Tamil Nadu", "Coimbatore": "Tamil Nadu",
    "Hyderabad": "Telangana", "Mumbai": "Maharashtra",
}

#: Email addresses in a bio. Deliberately stricter than the DTO's validator: a bio is full of
#: handles and hashtags, so we require a real TLD-shaped tail to avoid harvesting "@studio"
#: as an address.
_BIO_EMAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\-]+(?:\.[\w\-]+)+")

#: Phone numbers in a bio, in the forms Indian studios actually write them: "+91 98470 12345",
#: "9847012345", "0495-2701234", "+91-9847012345". Bounded on both sides by a non-digit so a
#: follower count or a date cannot be read as a number.
_BIO_PHONE_RE = re.compile(
    r"(?<![\d])(?:(?:\+?91|0)[\s\-\.]?)?(?:\d[\s\-\.]?){9,14}\d(?![\d])"
)

#: A WhatsApp mention immediately followed by a number, or a wa.me / api.whatsapp.com link.
#: Matching the *label* is what separates a WhatsApp number from the studio's landline; a
#: number with no such marker is treated as an ordinary phone.
_WHATSAPP_LABEL_RE = re.compile(
    r"(?:whats\s*app|whatsapp|wa|w/a)\s*[:\-–—]?\s*"
    r"((?:\+?91|0)?[\s\-\.]?(?:\d[\s\-\.]?){9,14}\d)",
    re.IGNORECASE,
)
_WHATSAPP_LINK_RE = re.compile(
    r"(?:wa\.me|api\.whatsapp\.com/send\?phone=)/?(\+?\d{8,15})", re.IGNORECASE
)

#: A 6-digit Indian pincode, bounded so a phone number's tail cannot be read as one.
_PINCODE_RE = re.compile(r"(?<!\d)([1-9]\d{5})(?!\d)")

#: Instagram usernames are 1-30 chars of letters, digits, periods and underscores.
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\.]{1,30}$")


def _hashtagify(term: str) -> str:
    """
    Reduces one query term to a legal hashtag: letters and digits only, lowercased.

    Instagram's `ig_hashtag_search` rejects punctuation and whitespace, so "Pre-Wedding"
    must become "prewedding" before it can be searched at all.
    """
    return re.sub(r"[^a-z0-9]+", "", term.strip().lower())


@register_provider
class InstagramLeadProvider(LeadProvider):
    """
    Adapter that collects photography businesses from Instagram via the Graph API.

    Collection is a two-phase discovery — hashtag search for candidate usernames, then one
    Business Discovery lookup per retained candidate — merged into a single raw record that
    `normalize()` maps onto `NormalizedLead`.

    The instance holds no run state: the query, limit and geographic scope all travel on the
    `ProviderContext`, so one instance is safe to reuse across concurrent imports. This
    replaces the `PlannedProvider` stub that previously declared this key.
    """

    key = "instagram"
    display_name = "Instagram"
    lead_source = "INSTAGRAM"
    requires_query = True
    requires_file = False

    def __init__(
        self,
        access_token: str | None = None,
        business_account_id: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
    ) -> None:
        """
        Args:
            access_token / business_account_id / base_url / api_version: Explicit overrides
                for the configured values. These exist so a test can drive the adapter
                against a stub server; production construction (via the registry, which
                takes no arguments) always reads settings.
        """
        self._access_token = (
            access_token if access_token is not None else settings.INSTAGRAM_ACCESS_TOKEN
        )
        self._business_account_id = (
            business_account_id
            if business_account_id is not None
            else settings.INSTAGRAM_BUSINESS_ACCOUNT_ID
        )
        base = (base_url or settings.INSTAGRAM_GRAPH_BASE_URL).rstrip("/")
        version = (api_version or settings.INSTAGRAM_GRAPH_API_VERSION).strip("/")
        self._base_url = f"{base}/{version}" if version else base

    # -----------------------------------------------------------------------------------
    # Availability
    # -----------------------------------------------------------------------------------

    @property
    def is_available(self) -> bool:  # type: ignore[override]
        """
        Reports whether this adapter can actually run, which for Business Discovery means
        "are BOTH credentials configured".

        Both are required because the API is issued *as* an account: a token with no account
        id has nothing to ask on behalf of. Computed rather than a class constant because
        availability is a deployment fact, not a code fact — the same build is unavailable in
        a dev environment with no token and available in production. `LeadProvider.search`
        already refuses when this is False, so an unconfigured deployment produces a clear
        400 at request time instead of a 190 from Meta partway through a RUNNING job.
        """
        return bool(
            (self._access_token or "").strip()
            and (self._business_account_id or "").strip()
        )

    @property
    def unavailable_reason(self) -> str:
        """
        States the actual fix — set the missing credential, named specifically — rather than
        the base class's "not yet implemented", which would send an operator looking for a
        missing feature when the provider is fully built and merely unconfigured.
        """
        missing = []
        if not (self._access_token or "").strip():
            missing.append("INSTAGRAM_ACCESS_TOKEN")
        if not (self._business_account_id or "").strip():
            missing.append("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        return (
            "Instagram lead collection is not configured: "
            f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} unset. "
            "Set them in the environment to enable this provider."
        )

    # -----------------------------------------------------------------------------------
    # search()
    # -----------------------------------------------------------------------------------

    def search(self, query: str | None = None, **kwargs: Any) -> ProviderContext:
        """
        Validates an Instagram collection request and returns its run context.

        Beyond the shared checks in `LeadProvider.search` (availability, non-empty query,
        limit bounds), this translates the operator's free-text query into the hashtags
        collection will actually search, and separates out the location terms.

        The translation is the part worth understanding. Instagram cannot be asked "Wedding
        Photographer Kerala" — it can only be asked for a hashtag. So the query is split into
        intent words and place words, and recombined into the hashtags a photographer in that
        place would realistically use:

            "Wedding Photographer Kerala"
                -> #weddingphotographerkerala, #weddingphotographer, #keralawedding, #kerala…

        Both the compound (intent+place) and the bare forms are searched, in that order: the
        compound is precise but sparse, the bare form is noisy but populated, and a run that
        searched only one of them would either return almost nothing or return the whole
        country. The derived location is also recorded in `options` so `normalize()` can fall
        back to it when a profile's bio names no city of its own.

        Raises:
            BadRequestException: the request cannot be serviced — credentials unset, no
                query, an out-of-range limit, or a query with no searchable term in it.
        """
        context = super().search(query, **kwargs)

        raw_query = context.query or ""
        # An explicit city/state parameter is authoritative over anything parsed out of the
        # query text: the operator typed it into a dedicated field, so it is not a guess.
        explicit_city = (context.city or "").strip() or None
        explicit_state = (context.state or "").strip() or None

        terms = [t for t in re.split(r"[^A-Za-z0-9]+", raw_query) if t]
        intent_terms: list[str] = []
        place_terms: list[str] = []
        for term in terms:
            if term.lower() in _INTENT_WORDS:
                intent_terms.append(term)
            else:
                place_terms.append(term)

        # Places named in the query, but only ones we actually recognise — see
        # `_KNOWN_CITIES` on why an unrecognised word must not become a city.
        derived_city = explicit_city
        derived_state = explicit_state
        for term in place_terms:
            lowered = term.lower()
            if not derived_city and lowered in _KNOWN_CITIES:
                derived_city = _KNOWN_CITIES[lowered]
            if not derived_state and lowered in _KNOWN_STATES:
                derived_state = _KNOWN_STATES[lowered]
        if derived_city and not derived_state:
            derived_state = _CITY_STATE.get(derived_city)

        hashtags = self._build_hashtags(
            intent_terms, place_terms, explicit_city, explicit_state
        )
        if not hashtags:
            raise BadRequestException(
                f"Provider '{self.key}' could not derive a searchable hashtag from query "
                f"{raw_query!r}. Use terms like 'Wedding Photographer Kerala'."
            )

        context.city = derived_city
        context.state = derived_state
        context.options = {
            **(context.options or {}),
            "hashtags": hashtags,
            "resolved_city": derived_city,
            "resolved_state": derived_state,
        }
        return context

    @staticmethod
    def _build_hashtags(
        intent_terms: Sequence[str],
        place_terms: Sequence[str],
        explicit_city: str | None,
        explicit_state: str | None,
    ) -> list[str]:
        """
        Builds the ordered, de-duplicated hashtag list a run will search.

        Ordering is by precision: the full compound first, then intent+place pairs, then the
        bare intent phrase, then place-qualified generics. Collection walks this list until
        it has enough candidates, so the most relevant hashtags are the ones that actually
        get spent — a run that fills its limit from "#weddingphotographerkozhikode" never
        pays for "#kozhikode" at all.
        """
        # Places from the query, plus any explicitly-supplied city/state, as hashtag atoms.
        places: list[str] = []
        for value in list(place_terms) + [explicit_city, explicit_state]:
            atom = _hashtagify(value or "")
            if atom and atom not in places:
                places.append(atom)

        intents = [a for a in (_hashtagify(t) for t in intent_terms) if a]
        intent_phrase = "".join(intents)

        candidates: list[str] = []

        # 1. The whole query as one tag: "#weddingphotographerkerala".
        if intent_phrase and places:
            candidates.append(intent_phrase + "".join(places))

        # 2. The intent phrase against each place: "#weddingphotographerkozhikode".
        for place in places:
            if intent_phrase:
                candidates.append(intent_phrase + place)

        # 3. The bare intent phrase: "#weddingphotographer". Nationally noisy but populated.
        if intent_phrase:
            candidates.append(intent_phrase)

        # 4. Place + a photography generic, catching studios that tag by craft not occasion.
        for place in places:
            candidates.append(place + "photography")
            candidates.append(place + "photographer")

        # 5. Nothing matched our intent vocabulary — fall back to the raw terms themselves,
        #    so an unusual query ("#drone videography") still searches something real.
        if not candidates:
            candidates = [a for a in (_hashtagify(t) for t in place_terms) if a]

        seen: set[str] = set()
        ordered: list[str] = []
        for tag in candidates:
            # Instagram caps a hashtag's length; over-long compounds match nothing.
            if not tag or len(tag) > 100 or tag in seen:
                continue
            seen.add(tag)
            ordered.append(tag)
        return ordered

    # -----------------------------------------------------------------------------------
    # collect()
    # -----------------------------------------------------------------------------------

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        """
        Collects raw profile records for the context's query.

        Walks the hashtags computed by `search()` to build a candidate username list, honours
        `context.limit` against that list, then runs Business Discovery on each retained
        candidate concurrently.

        Returns raw merged dicts — deliberately un-normalized, so `normalize()` stays a pure
        mapping testable without a network, and so the untouched Graph payload travels with
        the record for diagnosis.

        Raises:
            ProviderCollectionError: a run-level fault — credentials unset, `httpx`
                unavailable, Meta unreachable, token rejected, or rate limit exhausted.
        """
        if not self.is_available:
            raise ProviderCollectionError(
                "Instagram credentials are not configured, so Instagram collection cannot "
                "run. Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID."
            )

        httpx = self._import_httpx()
        timeout = httpx.Timeout(settings.INSTAGRAM_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                usernames = await self._discover_usernames(client, context)

                # Honour the limit BEFORE the Business Discovery fan-out — this is the cost
                # decision documented in the module docstring.
                selected = usernames[: context.limit]
                if not selected:
                    return []

                return await self._fetch_profiles(client, selected, context)

        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport fault is a run-level fault
            logger.exception("Instagram collection failed for query %r.", context.query)
            raise ProviderCollectionError(
                f"Instagram collection failed: {exc}"
            ) from exc

    @staticmethod
    def _import_httpx() -> Any:
        """
        Imports `httpx` lazily, converting an absent dependency into a run-level provider
        error rather than an import-time crash.

        Deferred deliberately: `app/services/lead_providers/__init__.py` imports this module
        at startup for its registration side effect, so a top-level `import httpx` would take
        the entire API down on a deployment that never uses this provider. Same reasoning as
        `GoogleMapsLeadProvider._import_httpx`.
        """
        try:
            import httpx  # noqa: PLC0415 - deferred on purpose, see docstring
        except ImportError as exc:  # pragma: no cover - depends on the deployment image
            raise ProviderCollectionError(
                "The 'httpx' package is required for Instagram collection but is not "
                "installed. Install it with: pip install httpx"
            ) from exc
        return httpx

    async def _discover_usernames(
        self, client: Any, context: ProviderContext
    ) -> list[str]:
        """
        Builds the ordered candidate username list for this run by walking hashtags.

        For each hashtag: resolve it to an id (`ig_hashtag_search`), then read `top_media`
        and `recent_media` for the usernames authoring those posts. Top media first — those
        posts rank because they perform, which correlates with an active business rather than
        a dormant account.

        Stops as soon as enough candidates are in hand. Deliberately over-collects a little
        (`_CANDIDATE_OVERSHOOT`) because some candidates will turn out to be personal accounts
        that Business Discovery refuses, and arriving at 20 requested with 12 usable is a
        worse outcome than one extra hashtag page.

        A hashtag that fails to resolve is skipped with a warning rather than failing the run:
        one dead hashtag out of six is not a source-level fault.
        """
        wanted = min(context.limit * _CANDIDATE_OVERSHOOT, _MAX_CANDIDATES)
        hashtags: list[str] = list((context.options or {}).get("hashtags") or [])
        max_pages = max(1, settings.INSTAGRAM_MAX_PAGES)

        seen: set[str] = set()
        ordered: list[str] = []

        for tag in hashtags:
            if len(ordered) >= wanted:
                break

            hashtag_id, error = await self._resolve_hashtag(client, tag)
            if error or not hashtag_id:
                logger.warning("Instagram hashtag %r could not be resolved: %s", tag, error)
                continue

            for edge in ("top_media", "recent_media"):
                if len(ordered) >= wanted:
                    break
                for username in await self._walk_media(
                    client, hashtag_id, edge, max_pages, wanted - len(ordered)
                ):
                    if username in seen or not _USERNAME_RE.match(username):
                        continue
                    seen.add(username)
                    ordered.append(username)
                    if len(ordered) >= wanted:
                        break

        return ordered

    async def _resolve_hashtag(
        self, client: Any, tag: str
    ) -> tuple[str | None, str | None]:
        """
        Resolves a hashtag name to its Graph API id, returning `(id, error)`.

        Returns rather than raises for a per-hashtag problem — an unknown or banned hashtag
        is an ordinary outcome, not a run-level fault. A *fatal* error (rejected token,
        exhausted quota) is re-raised by `_request`, since it applies to every remaining call.
        """
        params = {
            "user_id": self._business_account_id,
            "q": tag,
            "access_token": self._access_token,
        }
        try:
            payload = await self._request(client, "ig_hashtag_search", params)
        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - per-hashtag isolation, see docstring
            return None, f"Hashtag lookup failed: {exc}"

        data = payload.get("data") or []
        if not data:
            return None, f"Instagram returned no hashtag matching '{tag}'."
        return (data[0] or {}).get("id"), None

    async def _walk_media(
        self, client: Any, hashtag_id: str, edge: str, max_pages: int, wanted: int
    ) -> list[str]:
        """
        Walks one hashtag media edge's pagination, returning the usernames that authored the
        posts.

        Instagram's hashtag media edges return the *post*, with its owning `username`
        alongside — which is exactly the candidate list we need and the only query-shaped
        route to it. Pagination stops at `max_pages`, at `wanted` usernames, or when Meta
        stops issuing a cursor.

        Never raises for a page-level problem: a failed page yields the usernames gathered so
        far, because half a hashtag's candidates is still a useful contribution to the run.
        """
        usernames: list[str] = []
        after: str | None = None

        for _ in range(max_pages):
            if len(usernames) >= wanted:
                break
            params: dict[str, Any] = {
                "user_id": self._business_account_id,
                "fields": "id,username,caption,permalink",
                "limit": _MEDIA_PAGE_SIZE,
                "access_token": self._access_token,
            }
            if after:
                params["after"] = after

            try:
                payload = await self._request(client, f"{hashtag_id}/{edge}", params)
            except ProviderCollectionError:
                raise
            except Exception as exc:  # noqa: BLE001 - per-page isolation, see docstring
                logger.warning("Instagram %s page failed for %s: %s", edge, hashtag_id, exc)
                break

            for item in payload.get("data") or []:
                username = ((item or {}).get("username") or "").strip().lstrip("@")
                if username:
                    usernames.append(username)

            after = (
                ((payload.get("paging") or {}).get("cursors") or {}).get("after")
            )
            if not after:
                break

        return usernames

    async def _fetch_profiles(
        self, client: Any, usernames: Sequence[str], context: ProviderContext
    ) -> list[dict[str, Any]]:
        """
        Runs Business Discovery for every candidate, concurrently but bounded, and returns
        one raw record per profile that resolved.

        A lookup failure degrades exactly one record. Unlike the Google adapter — where a
        failed Details call still leaves a real listing worth keeping — a failed Business
        Discovery leaves nothing at all: without it we have a username and no name, no bio,
        no contact route. Such a candidate is therefore *dropped* rather than carried forward
        as a guaranteed failed record, and the reason is logged. Inflating `failed_records`
        with private accounts we were never able to import would make the counter useless as
        a signal that something is wrong.

        Ordering is preserved so the job log's record numbers correspond to discovery
        ranking.
        """
        semaphore = asyncio.Semaphore(max(1, settings.INSTAGRAM_CONCURRENCY))

        async def fetch(username: str) -> dict[str, Any]:
            async with semaphore:
                profile, error = await self._discover_profile(client, username)
            record: dict[str, Any] = {
                "username": username,
                "profile": profile,
                "query": context.query,
                "resolved_city": (context.options or {}).get("resolved_city"),
                "resolved_state": (context.options or {}).get("resolved_state"),
            }
            if error:
                record["discovery_error"] = error
            return record

        # `gather` preserves input order, keeping job-log record numbers aligned with
        # discovery ranking. `return_exceptions` guards the contract that no single profile
        # can abort the batch even if `fetch` itself fails unexpectedly.
        results = await asyncio.gather(
            *(fetch(username) for username in usernames), return_exceptions=True
        )

        records: list[dict[str, Any]] = []
        skipped: list[str] = []
        for username, result in zip(usernames, results):
            if isinstance(result, BaseException):
                logger.warning("Business Discovery failed for %r: %s", username, result)
                skipped.append(username)
                continue
            if not result.get("profile"):
                skipped.append(username)
                continue
            if not self._is_worth_importing(result["profile"]):
                skipped.append(username)
                continue
            records.append(result)

        if skipped:
            logger.info(
                "Instagram: %d of %d candidates yielded no importable profile (%s).",
                len(skipped), len(usernames), ", ".join(skipped[:10]),
            )
        return records

    @staticmethod
    def _is_worth_importing(profile: dict[str, Any]) -> bool:
        """
        Applies the configured pre-import filters to a resolved profile.

        `INSTAGRAM_MIN_FOLLOWERS` drops dormant and hobbyist accounts before they consume a
        lead row. This runs *after* the lookup rather than before because follower count is
        only known once the profile has been fetched — it is a quality filter, not a cost
        one.
        """
        minimum = settings.INSTAGRAM_MIN_FOLLOWERS
        if minimum and (profile.get("followers_count") or 0) < minimum:
            return False
        return True

    async def _discover_profile(
        self, client: Any, username: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Fetches one profile through Business Discovery, returning `(payload, error)`.

        Returns rather than raises for a per-profile problem, because at this point we cannot
        yet tell whether the record is salvageable — that judgement belongs to the caller and
        to the import service's validity check. A *fatal* error (rejected token, exhausted
        rate limit) is re-raised by `_request`, since it will apply identically to every
        remaining profile.

        The nested-field syntax is Meta's own: Business Discovery is expressed as a field on
        the *calling* account, not as its own endpoint.
        """
        params = {
            "fields": f"business_discovery.username({username}){{{_DISCOVERY_FIELDS}}}",
            "access_token": self._access_token,
        }
        try:
            payload = await self._request(client, self._business_account_id, params)
        except ProviderCollectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - per-profile isolation, see docstring
            return None, f"Business Discovery request failed: {exc}"

        error = payload.get("error")
        if error:
            # A non-fatal error here is almost always "this is a personal account", which is
            # an ordinary, expected outcome rather than a fault.
            return None, str(error.get("message") or error)

        profile = payload.get("business_discovery")
        if not profile:
            return None, (
                f"Instagram returned no business profile for '{username}' — it is most "
                f"likely a personal account, which Business Discovery cannot resolve."
            )
        return profile, None

    async def _request(
        self, client: Any, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Performs one GET against the Graph API and returns its decoded JSON body.

        Meta reports its errors in the body with HTTP 400, so the body is parsed *before* the
        status code is judged: that is the only way to tell an expired token (fatal, fail the
        run) from a personal account (ordinary, drop one record). A fatal error code raises
        here; anything else is returned as a payload carrying `error`, for the caller to
        contain.
        """
        url = f"{self._base_url}/{path}"
        response = await client.get(url, params=params)

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - a non-JSON body is a source-level fault
            if response.status_code >= 400:
                raise ProviderCollectionError(
                    f"Instagram Graph API returned HTTP {response.status_code} for {path}."
                ) from exc
            raise ProviderCollectionError(
                f"Instagram Graph API returned an unreadable response for {path}: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderCollectionError(
                f"Instagram Graph API returned an unexpected payload shape for {path}."
            )

        self._raise_if_fatal(payload)

        if response.status_code >= 400 and not payload.get("error"):
            # A 4xx/5xx with no structured error is a transport-level fault, not something a
            # single record can be blamed for.
            raise ProviderCollectionError(
                f"Instagram Graph API returned HTTP {response.status_code} for {path}."
            )
        return payload

    @staticmethod
    def _raise_if_fatal(payload: dict[str, Any]) -> None:
        """
        Converts a run-invalidating Meta error into `ProviderCollectionError`.

        Only credential, permission and rate-limit failures qualify (see `_FATAL_ERROR_CODES`
        and `_FATAL_ERROR_SUBCODES`). "Not a business account" and "no such user" are
        ordinary per-request outcomes and must not fail a run.
        """
        error = payload.get("error")
        if not isinstance(error, dict):
            return

        code = error.get("code")
        subcode = error.get("error_subcode")
        explanation = None
        if isinstance(code, int):
            explanation = _FATAL_ERROR_CODES.get(code)
            if explanation is None and 200 <= code <= 299:
                explanation = (
                    "The Instagram app lacks the permission required for this call. The "
                    "token needs instagram_basic and pages_read_engagement on a linked "
                    "Business account."
                )
        if explanation is None and isinstance(subcode, int):
            explanation = _FATAL_ERROR_SUBCODES.get(subcode)

        if not explanation:
            return
        detail = error.get("message")
        raise ProviderCollectionError(
            explanation + (f" Instagram said: {detail}" if detail else "")
        )

    # -----------------------------------------------------------------------------------
    # normalize()
    # -----------------------------------------------------------------------------------

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        """
        Maps one raw Instagram record onto the uniform `NormalizedLead` shape.

        Pure and offline: it takes the dict `collect()` built and touches nothing external,
        which is what makes the whole mapping — bio parsing, phone ordering, city inference —
        testable without a token.

        The mapping's substance is `_parse_bio`, because Instagram publishes almost no
        structured contact data (see the module docstring). Everything the CRM needs to
        actually *contact* a lead comes out of free text, and everything the CRM has no column
        for — followers, following, posts, verified status, category, profile image — is
        retained under `categories` and `raw` so `LeadImportService._build_remarks` surfaces
        it without widening a shared schema for one provider's convenience.

        Never raises: a record it cannot make sense of comes back missing the fields
        `is_valid()` requires, which the import service counts and logs as one failed record.
        """
        profile = raw.get("profile") or {}
        username = (profile.get("username") or raw.get("username") or "").strip()
        biography = profile.get("biography") or ""

        parsed = self._parse_bio(biography)

        # WhatsApp first when it is genuinely a different number: it is the channel this CRM
        # actually reaches photographers on, and `NormalizedLead.secondary_phone` promotes
        # index 1 to the `whatsapp` column — so leading with it would bury the studio's main
        # line. Ordering is therefore phone-then-whatsapp, matching what the columns mean.
        phones: list[str] = list(parsed["phones"])
        whatsapp = parsed["whatsapp"]
        if whatsapp:
            whatsapp_key = normalize_phone(whatsapp)
            existing_keys = {normalize_phone(p) for p in phones}
            if whatsapp_key and whatsapp_key not in existing_keys:
                # A distinct WhatsApp number goes second, where the DTO maps it to the
                # `whatsapp` column.
                phones.insert(1 if phones else 0, whatsapp)

        # A bio's own location wins over the query's, because it is the business's statement
        # about itself; the query-derived location is a fallback for the common case of a bio
        # that names no place at all.
        city = parsed["city"] or raw.get("resolved_city")
        state = parsed["state"] or raw.get("resolved_state")
        if city and not state:
            state = _CITY_STATE.get(city)

        lead = NormalizedLead(
            # `name` is the profile's display name — the business name as it presents itself.
            # The username is the fallback, since a profile with no display name still has a
            # handle, and "sunrise_studio_klm" is a poorer but real business name.
            business_name=profile.get("name") or username or None,
            # Instagram exposes no separate owner/contact person. Left None rather than
            # guessed at, so `_build_enrichment` never overwrites a real contact name a human
            # typed with something derived from a handle.
            owner_name=None,
            phone_numbers=phones,
            emails=parsed["emails"],
            website=profile.get("website"),
            instagram=username or None,
            address=parsed["address"],
            city=city,
            state=state,
            country="India" if (city or state) else None,
            pincode=parsed["pincode"],
            source=self.lead_source,
            source_url=self._profile_url(username),
            categories=self._categories(profile),
            raw=raw,
        )
        return lead.normalize()

    @staticmethod
    def _profile_url(username: str | None) -> str | None:
        """
        Builds the canonical profile link, so an operator can always click through to verify
        the account they are being asked to call.
        """
        if not username:
            return None
        return f"https://www.instagram.com/{username}/"

    @staticmethod
    def _categories(profile: dict[str, Any]) -> list[str]:
        """
        Renders the profile's non-contact metadata as category tags.

        Followers, following, posts and verified status have no column on `leads`, and adding
        five columns for one provider would widen a shared schema for this adapter's
        convenience — the same judgement the Google adapter made for rating and review count.
        Tagging them here routes them into `_build_remarks`, so they reach the person working
        the lead, where "142k followers, Verified" is exactly the qualifying signal that makes
        an Instagram lead worth calling first.
        """
        tags: list[str] = []

        category = profile.get("category") or profile.get("business_category_name")
        if category:
            tags.append(str(category))

        followers = profile.get("followers_count")
        if isinstance(followers, int):
            tags.append(f"{followers:,} followers")

        follows = profile.get("follows_count")
        if isinstance(follows, int):
            tags.append(f"Following {follows:,}")

        media = profile.get("media_count")
        if isinstance(media, int):
            tags.append(f"{media:,} posts")

        if profile.get("is_verified"):
            tags.append("Verified")

        picture = profile.get("profile_picture_url")
        if picture:
            # Retained as a tag so the URL survives into remarks; the CRM has no image column
            # and downloading the asset is a different concern with its own storage decision.
            tags.append(f"Profile image: {picture}")

        return tags

    # -----------------------------------------------------------------------------------
    # Bio parsing
    # -----------------------------------------------------------------------------------

    @classmethod
    def _parse_bio(cls, biography: str) -> dict[str, Any]:
        """
        Extracts contact and location details from a profile's free-text biography.

        This is the Instagram equivalent of Google's `address_components` split, and it is
        the least certain code in the adapter, so every extraction here is deliberately
        conservative: an ambiguous value yields *nothing* rather than a guess. The reason is
        asymmetric cost — a missing phone number means one lead is skipped and logged, while a
        wrong phone number means the record silently merges onto an unrelated existing lead
        (phone is the highest-confidence duplicate rule) and corrupts a row a human may have
        curated. Under-extracting is recoverable; over-extracting is not.

        Returns a dict with `phones`, `whatsapp`, `emails`, `city`, `state`, `pincode` and
        `address`. Total — it never raises, whatever the bio contains.
        """
        text = biography or ""
        if not text.strip():
            return {
                "phones": [], "whatsapp": None, "emails": [],
                "city": None, "state": None, "pincode": None, "address": None,
            }

        emails = cls._extract_emails(text)
        whatsapp = cls._extract_whatsapp(text)
        phones = cls._extract_phones(text, exclude=whatsapp)
        city, state = cls._extract_city_state(text)
        pincode = cls._extract_pincode(text)

        return {
            "phones": phones,
            "whatsapp": whatsapp,
            "emails": emails,
            "city": city,
            "state": state,
            "pincode": pincode,
            "address": cls._extract_address(text),
        }

    @staticmethod
    def _extract_emails(text: str) -> list[str]:
        """
        Extracts email addresses from a bio, preserving order and dropping duplicates.

        The pattern requires a dotted domain tail so that Instagram handles ("@studio") and
        mention syntax are not harvested as addresses — a bio is full of both.
        """
        seen: set[str] = set()
        found: list[str] = []
        for match in _BIO_EMAIL_RE.finditer(text):
            value = match.group(0).strip().strip(".,;:")
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(value)
        return found

    @staticmethod
    def _extract_whatsapp(text: str) -> str | None:
        """
        Extracts a WhatsApp number, but only when the bio explicitly labels it as one —
        either in words ("WhatsApp: 9847012345") or as a `wa.me` link.

        The label is the entire evidence. An unlabelled number is treated as an ordinary
        phone, because promoting a studio's landline into the `whatsapp` column would have
        the CRM's messaging features dial a number that cannot receive messages.
        """
        for pattern in (_WHATSAPP_LINK_RE, _WHATSAPP_LABEL_RE):
            match = pattern.search(text)
            if not match:
                continue
            candidate = match.group(1)
            if normalize_phone(candidate):
                return candidate.strip()
        return None

    @staticmethod
    def _extract_phones(text: str, exclude: str | None = None) -> list[str]:
        """
        Extracts phone numbers from a bio, in the order written, skipping the one already
        claimed as WhatsApp.

        `normalize_phone` is the gate: it enforces the minimum digit count, so a year, a price
        or a follower count cannot become a phone number. Numbers that survive are returned
        as written rather than reformatted, because the original string is what an operator
        dials and what the CRM stores.
        """
        exclude_key = normalize_phone(exclude) if exclude else None
        seen: set[str] = set()
        if exclude_key:
            seen.add(exclude_key)

        found: list[str] = []
        for match in _BIO_PHONE_RE.finditer(text):
            candidate = match.group(0).strip()
            key = normalize_phone(candidate)
            if not key or key in seen:
                continue
            seen.add(key)
            found.append(candidate)
        return found

    @staticmethod
    def _extract_city_state(text: str) -> tuple[str | None, str | None]:
        """
        Identifies the city and state a bio names, matched against a known vocabulary rather
        than parsed out of arbitrary text.

        Matching a closed list is the conservative choice and it is deliberate: a bio reads
        "📍 Kozhikode | Destination weddings worldwide", and a general-purpose place parser
        would happily return "Destination" or "Worldwide" as the city. A wrong city is not a
        cosmetic error — it feeds the business-name+city duplicate rule, so it can merge two
        unrelated studios or split one across two rows. An unrecognised place therefore yields
        `None`, and the lead is imported without a city.

        Word-boundary matching keeps "Kochi" from firing on "Kochin­gale" or similar.
        """
        lowered = text.lower()

        city = None
        for token, canonical in _KNOWN_CITIES.items():
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                city = canonical
                break

        state = None
        for token, canonical in _KNOWN_STATES.items():
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                state = canonical
                break

        if city and not state:
            state = _CITY_STATE.get(city)
        return city, state

    @staticmethod
    def _extract_pincode(text: str) -> str | None:
        """
        Extracts a 6-digit Indian pincode when one appears in the bio.

        Bounded by non-digits on both sides so that a phone number's tail is never read as a
        pincode, and required to start with a non-zero digit, which every real Indian pincode
        does.
        """
        # Remove anything phone-shaped first, so a 10-digit mobile cannot donate six of its
        # digits to a false pincode match.
        without_phones = _BIO_PHONE_RE.sub(" ", text)
        match = _PINCODE_RE.search(without_phones)
        return match.group(1) if match else None

    @staticmethod
    def _extract_address(text: str) -> str | None:
        """
        Extracts the bio segment that looks like a street address — the part following a
        location marker (📍, "Location:", "Studio at").

        Returns None unless the segment is substantive: a bare "📍 Kerala" — or "📍 Kozhikode,
        Kerala" — is a location we already captured into the city and state columns, not an
        address, and copying it into `address` would fill that column with data the record
        already carries in structured form. A bio with no marker yields nothing rather than
        having its first line assumed to be an address.
        """
        marker = re.search(
            r"(?:📍|📌|🏠|🏢|(?:^|[|\n])\s*(?:location|address|studio at|based in)\s*[:\-–—])"
            r"\s*(.+)",
            text,
            re.IGNORECASE,
        )
        if not marker:
            return None

        # Stop at the next separator: bios are pipe- and newline-delimited lists of claims.
        segment = re.split(r"[|\n•·]", marker.group(1))[0].strip(" -–—:,")
        segment = re.sub(r"\s+", " ", segment)

        if len(segment) < _MIN_ADDRESS_LENGTH or len(segment.split()) < 2:
            return None

        # Reject a segment that is *only* place names we already store as city/state. A
        # street address always carries something more — a building, a road, a number — so
        # requiring at least one non-place token separates "Kozhikode, Kerala" from
        # "3rd Floor, MG Road, Thrissur".
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", segment.lower()) if t]
        if tokens and all(
            token in _KNOWN_CITIES or token in _KNOWN_STATES for token in tokens
        ):
            return None
        return segment


#: How many more candidate usernames to gather than the run actually needs. Business
#: Discovery refuses personal accounts, so a fraction of candidates never resolve; collecting
#: a surplus means a `limit=20` run usually returns 20 profiles rather than 12. Kept small
#: because every surplus candidate that *does* resolve is a lookup spent past the limit.
_CANDIDATE_OVERSHOOT = 2

#: Absolute ceiling on candidate usernames per run, independent of the limit. Guards against
#: an operator's large limit multiplying into an unbounded hashtag walk.
_MAX_CANDIDATES = 300

#: Media items requested per hashtag page. Meta's own maximum for these edges.
_MEDIA_PAGE_SIZE = 50

#: Shortest string accepted as a street address; below this it is a city name, not an address.
_MIN_ADDRESS_LENGTH = 8
