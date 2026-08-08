"""
app/core/config.py

This file defines the application's configuration settings using Pydantic Settings (Pydantic v2).
Pydantic Settings reads variables from environment variables or a `.env` file, validates their
types, and stores them in a single, type-safe configuration object. This decouples environment
configuration from application logic, preventing starting the app with invalid or missing settings.
"""

from typing import Any, List, Union
import json
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Settings class that loads configurations from .env or environment variables.
    Provides automatic validation and computes database URIs dynamically.
    """
    model_config = SettingsConfigDict(
        # Load env vars from .env file
        env_file=".env",
        # Ignore empty values in .env, letting actual environment variables override them
        env_ignore_empty=True,
        # Ignore extra parameters passed to settings
        extra="ignore"
    )

    # Project Information
    PROJECT_NAME: str = "Colour Labs CRM"
    ENV: str = "development"  # e.g., development, staging, production
    API_V1_STR: str = "/api/v1"

    # Security & Authentication Settings
    SECRET_KEY: str = "supersecret_default_key_for_colourlabs_erp_jwt_signing"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15


    # CORS Settings
    # Supports JSON lists e.g. ["http://localhost:3000"] or comma-separated values
    BACKEND_CORS_ORIGINS: Union[List[str], str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> Union[List[str], str]:
        """
        Parses the CORS origins if configured as a JSON array or a comma-separated string.
        """
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass
            return v
        return []

    # ---------------------------------------------------------------------------------
    # Google Maps / Google Places lead collection
    # ---------------------------------------------------------------------------------
    # Credentials for the `google_maps` lead provider. The API key has no default on
    # purpose: an empty key makes the provider report itself unavailable and refuse to run
    # with a clear message, which is far better than a hardcoded placeholder that fails at
    # request time with an opaque 403 from Google.
    GOOGLE_MAPS_API_KEY: str = ""

    #: Base URL of the Places API. Configurable so a test or a proxy can point the provider
    #: at a stub server without patching the adapter.
    GOOGLE_MAPS_BASE_URL: str = "https://maps.googleapis.com/maps/api/place"

    #: Per-request timeout, in seconds, for a single call to Google.
    GOOGLE_MAPS_TIMEOUT_SECONDS: float = 15.0

    #: Region bias for Text Search (ccTLD form). The CRM's market is India, and biasing the
    #: search keeps "Photographer Kozhikode" from matching similarly-named places abroad.
    GOOGLE_MAPS_REGION: str = "in"

    #: Language for returned place names and addresses.
    GOOGLE_MAPS_LANGUAGE: str = "en"

    #: Whether to spend a Place Details call per result. Details is the only source of
    #: phone, website and opening hours, so this defaults on — but it is billed per call,
    #: so an operator running a wide survey can switch it off and accept name/address only.
    GOOGLE_MAPS_FETCH_DETAILS: bool = True

    #: Maximum Text Search result pages to walk. Google returns 20 results per page and
    #: caps pagination at 3 pages (60 results) regardless of what is asked for.
    GOOGLE_MAPS_MAX_PAGES: int = 3

    # ---------------------------------------------------------------------------------
    # Instagram lead collection (Instagram Graph API — Business Discovery)
    # ---------------------------------------------------------------------------------
    # Credentials for the `instagram` lead provider. Business Discovery is the only
    # sanctioned way to read another business's public profile, and it needs BOTH a
    # long-lived access token AND the caller's own IG Business account id — the API is
    # shaped as "my account asks about that username", not as an anonymous lookup. Neither
    # has a default: an unset credential makes the provider report itself unavailable and
    # refuse with a clear message, rather than failing mid-run with an opaque 190 from Meta.
    INSTAGRAM_ACCESS_TOKEN: str = ""

    #: The IG Business/Creator account id that Business Discovery queries are issued *as*.
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = ""

    #: Base URL of the Graph API. Configurable so a test or proxy can point the provider at
    #: a stub server without patching the adapter.
    INSTAGRAM_GRAPH_BASE_URL: str = "https://graph.facebook.com"

    #: Graph API version. Meta versions its API and retires versions on a schedule, so this
    #: is configurable to allow an upgrade without a code change.
    INSTAGRAM_GRAPH_API_VERSION: str = "v21.0"

    #: Per-request timeout, in seconds, for a single call to the Graph API.
    INSTAGRAM_TIMEOUT_SECONDS: float = 15.0

    #: Number of Business Discovery lookups in flight at once. Bounded so a wide run does
    #: not open dozens of concurrent sockets to Meta and trip its per-app rate limit.
    INSTAGRAM_CONCURRENCY: int = 5

    #: How many hashtag result pages to walk while discovering candidate usernames. Each
    #: page is a billed/rate-limited call, so this bounds the discovery half of a run.
    INSTAGRAM_MAX_PAGES: int = 3

    #: Whether to drop profiles that expose no phone number. Business Discovery returns a
    #: phone only for accounts that publish one; a lead without a phone is rejected by
    #: `NormalizedLead.is_valid()` anyway, so this defaults on to keep the failed-record
    #: count meaningful. Switch it off to survey what exists and accept mass failures.
    INSTAGRAM_REQUIRE_CONTACT: bool = True

    #: Minimum follower count for a discovered profile to be worth importing. Filters out
    #: dormant and hobbyist accounts before they consume a lookup. 0 disables the filter.
    INSTAGRAM_MIN_FOLLOWERS: int = 0

    # ---------------------------------------------------------------------------------
    # OpenStreetMap / Overpass lead collection (free replacement for Google Places)
    # ---------------------------------------------------------------------------------
    # The `overpass` provider needs no credential at all — OpenStreetMap data is open and
    # the public Overpass endpoints are unauthenticated. That is the entire reason this
    # adapter exists: Google Places bills per Place Details call, and this one costs
    # nothing. Consequently `is_available` is unconditionally True; there is no key whose
    # absence could disable it.
    #
    # What replaces the credential as the scarce resource is *politeness*. The public
    # instances are donated capacity governed by a usage policy, not a paid quota, and the
    # way to lose access is to hammer them. Every knob below exists to keep this adapter a
    # well-behaved client.

    #: Overpass QL endpoint. Configurable so an operator running their own instance — the
    #: usage policy's own recommendation for heavy use — can point at it without a code
    #: change, and so tests can aim at a stub.
    OVERPASS_BASE_URL: str = "https://overpass-api.de/api/interpreter"

    #: Nominatim geocoding endpoint, used to turn a city name into the lat/lon that anchors
    #: the Overpass radius query.
    NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org/search"

    #: Per-request timeout, in seconds. Generous compared with the Google adapter's 15s
    #: because an Overpass query is executed server-side against a planet-wide database and
    #: a wide radius genuinely takes tens of seconds — a short timeout here produces a
    #: retry storm against a server that was going to answer.
    OVERPASS_TIMEOUT_SECONDS: float = 60.0

    #: The `[timeout:N]` value embedded in the Overpass QL query itself, telling the *server*
    #: how long it may spend. Kept below the transport timeout so the server aborts and says
    #: so, rather than the client hanging up on work still in progress.
    OVERPASS_QUERY_TIMEOUT_SECONDS: int = 50

    #: Default search radius, in kilometres, when a request does not specify `radius_km`.
    OVERPASS_DEFAULT_RADIUS_KM: float = 10.0

    #: Hard ceiling on the radius. A radius large enough to cover a state turns one import
    #: into a multi-minute query on shared donated infrastructure, which is precisely the
    #: behaviour the usage policy asks clients not to exhibit.
    OVERPASS_MAX_RADIUS_KM: float = 50.0

    #: Minimum seconds between two outbound calls to the same host. The usage policy asks
    #: for roughly one query at a time from a given client rather than a burst, so calls are
    #: serialised and spaced by this interval.
    OVERPASS_MIN_REQUEST_INTERVAL_SECONDS: float = 1.0

    #: How many times a failed request is retried before the run is failed. Overpass answers
    #: 429 (rate limited) and 504 (server overloaded) under load, and both are ordinarily
    #: transient — retrying is the documented correct response, giving up immediately is not.
    OVERPASS_MAX_RETRIES: int = 3

    #: First backoff delay, in seconds. Doubles per attempt (see `_request_with_retry`).
    OVERPASS_BACKOFF_BASE_SECONDS: float = 2.0

    #: Ceiling on a single backoff delay, so exponential growth cannot park an import for
    #: minutes on the fourth attempt.
    OVERPASS_BACKOFF_MAX_SECONDS: float = 30.0

    #: Contact identity sent as the User-Agent. The Overpass and Nominatim usage policies
    #: both *require* a client to identify itself, and an anonymous or spoofed agent is the
    #: fastest route to being blocked. Override this with a real contact address in
    #: production.
    OVERPASS_USER_AGENT: str = "ColourLabsCRM/1.0 (lead-collection; contact: admin@colourlabs.example)"

    # ---------------------------------------------------------------------------------
    # WhatsApp Cloud API (Meta) — outbound campaign messaging
    # ---------------------------------------------------------------------------------
    # Credentials for the `whatsapp_cloud` provider adapter. Meta's Cloud API needs three
    # distinct identifiers and they are not interchangeable:
    #   * the access token authenticates the caller,
    #   * the phone number id is the *sender* the message goes out from,
    #   * the business account id (WABA) owns the templates and is only needed to read the
    #     template catalogue.
    # None has a default. An unset credential makes the adapter report itself misconfigured
    # through `validate_configuration()` and refuse every send with a clear message, rather
    # than failing per recipient with an opaque 190 from Meta halfway through a 5,000-lead
    # campaign.
    #: Which outbound adapter `get_whatsapp_provider()` returns when no name is passed:
    #: 'noop' (simulated sends, fully visible in the recipient rows) or 'whatsapp_cloud'
    #: (Meta). Defaults to 'noop' so adding this module to an existing deployment cannot
    #: start sending real messages until someone opts in.
    WHATSAPP_PROVIDER: str = "noop"

    WHATSAPP_ACCESS_TOKEN: str = ""

    #: The Cloud API phone number id that messages are sent *from*. This is Meta's numeric
    #: id for the registered sender, not the phone number itself.
    WHATSAPP_PHONE_NUMBER_ID: str = ""

    #: The WhatsApp Business Account (WABA) id that owns the message templates. Required
    #: only for template-catalogue reads; sending works without it.
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""

    #: Shared secret echoed back during Meta's GET webhook handshake. Meta sends it as
    #: `hub.verify_token`; the endpoint must return `hub.challenge` only when it matches.
    WHATSAPP_VERIFY_TOKEN: str = ""

    #: The Meta *app secret*, used to verify the `X-Hub-Signature-256` HMAC on inbound
    #: webhook POSTs. This is a different credential from the access token and is the only
    #: thing standing between the webhook and anyone on the internet rewriting lead
    #: statuses — see `WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE`.
    WHATSAPP_APP_SECRET: str = ""

    #: Whether an inbound webhook POST with a missing or invalid signature is rejected.
    #: Defaults to True and should never be False in production; it exists so a developer
    #: can replay a captured payload locally with curl without computing an HMAC.
    WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE: bool = True

    #: Base URL of the Graph API. Configurable so a test or proxy can point the adapter at
    #: a stub server without patching it.
    WHATSAPP_GRAPH_BASE_URL: str = "https://graph.facebook.com"

    #: Graph API version. Meta versions its API and retires versions on a schedule, so this
    #: is configurable to allow an upgrade without a code change.
    GRAPH_API_VERSION: str = "v21.0"

    #: Per-request timeout, in seconds, for one call to the Graph API. Deliberately short:
    #: a campaign dispatches sequentially inside a request, so a long hang on one recipient
    #: delays every recipient behind it.
    WHATSAPP_TIMEOUT_SECONDS: float = 15.0

    #: How many times a send is retried after a retryable fault (429 rate limit, 5xx,
    #: network timeout). 0 disables retrying. Bounded low because the campaign loop has
    #: thousands of messages behind this one.
    WHATSAPP_MAX_RETRIES: int = 2

    #: Base delay, in seconds, for the exponential backoff between retries. The adapter
    #: prefers Meta's own `Retry-After` header when one is supplied.
    WHATSAPP_RETRY_BACKOFF_SECONDS: float = 1.0

    #: Default country calling code (digits only, no '+') prepended to a stored number that
    #: has no country code. Meta requires E.164 without the '+'; the CRM's leads are Indian
    #: and are routinely stored as 10-digit numbers, so without this every send would be
    #: rejected as an invalid recipient.
    WHATSAPP_DEFAULT_COUNTRY_CODE: str = "91"

    #: Whether campaign sends go out as pre-registered Meta templates rather than as free
    #: text. Meta only permits free-form text inside a 24-hour customer service window, and
    #: a cold outreach campaign is by definition outside it, so this defaults on. Switch it
    #: off only for messaging that answers an existing conversation.
    WHATSAPP_USE_TEMPLATES: bool = True

    # ---------------------------------------------------------------------------------
    # Website discovery (lead enrichment)
    # ---------------------------------------------------------------------------------
    # Web search (pluggable backend for website discovery)
    # ---------------------------------------------------------------------------------
    # Settings for the `SearchBackend` port in `app/services/lead_providers/web_search/`.
    # Nothing here is a credential, because the default backend deliberately needs none —
    # website discovery works on a fresh checkout with an empty .env.

    #: Which registered `SearchBackend` to use. `duckduckgo` is the zero-credential default.
    #: Adding a keyed engine (Google CSE, Brave, Serper) means a new backend class plus its
    #: `@register_search_backend` decorator, then setting this. An unknown value falls back to
    #: the default with a warning rather than breaking an import run — discovery writes
    #: nothing on its own, so degrading is strictly safer than failing.
    WEB_SEARCH_BACKEND: str = "duckduckgo"

    #: DuckDuckGo's no-JavaScript HTML endpoint. Configurable so a test can aim at a stub and
    #: an operator can point at a mirror without a code change.
    WEB_SEARCH_DDG_URL: str = "https://html.duckduckgo.com/html/"

    #: Per-attempt timeout, in seconds. Short: a SERP that has not answered in ten seconds is
    #: not going to, and enrichment must never be the reason an import feels hung.
    WEB_SEARCH_TIMEOUT_SECONDS: float = 10.0

    #: Region/locale hint sent with the query. The CRM's market is India, and the bias keeps a
    #: studio name from resolving to a same-named business abroad.
    WEB_SEARCH_REGION: str = "in-en"

    #: Contact identity sent as the User-Agent. An absent or obviously-scripted agent earns a
    #: challenge page instead of results. Set a real contact address in production.
    WEB_SEARCH_USER_AGENT: str = (
        "ColourLabsCRM/1.0 (lead-enrichment; contact: admin@colourlabs.example)"
    )

    #: Minimum seconds between two outbound searches. The default backend is an unmetered
    #: public endpoint, so the failure mode for bursting is being blocked, not being billed —
    #: the same reasoning as `OVERPASS_MIN_REQUEST_INTERVAL_SECONDS`.
    WEB_SEARCH_MIN_REQUEST_INTERVAL_SECONDS: float = 1.5

    #: Total attempts per search, including the first. Retries apply only to faults a retry
    #: can fix (timeouts, connection errors, 429, 5xx); a 403 is a decision about this client
    #: and retrying it only hastens a block.
    WEB_SEARCH_MAX_ATTEMPTS: int = 3

    #: Base for the exponential backoff between attempts: `base * 2**(attempt-1)`, plus
    #: jitter so concurrent imports that failed on one upstream blip do not retry in lockstep.
    WEB_SEARCH_RETRY_BACKOFF_SECONDS: float = 1.0

    #: Ceiling on a single backoff wait, so a long retry schedule cannot outlast the import
    #: request that triggered it.
    WEB_SEARCH_RETRY_BACKOFF_MAX_SECONDS: float = 8.0

    #: Redirect budget for both search and validation requests. Bounded rather than unlimited
    #: so a redirect loop or a chain into a consent wall terminates instead of consuming the
    #: whole timeout.
    WEB_SEARCH_MAX_REDIRECTS: int = 5

    #: Whether to fetch and honour robots.txt before searching. On by default: this is an
    #: unmetered endpoint we are a guest on, and "it is only a few requests" is exactly the
    #: reasoning that gets a source blocked for everyone.
    WEB_SEARCH_RESPECT_ROBOTS: bool = True

    # ---------------------------------------------------------------------------------
    # Website discovery (scoring and validation)
    # ---------------------------------------------------------------------------------
    # Settings for `WebsiteDiscoveryService`, which turns search results into at most one
    # attributed website per lead. Separate from the WEB_SEARCH_* block above because the
    # search backend is swappable while this scoring is not.

    #: How many search results to consider per lead. Beyond roughly five, results are no
    #: longer plausibly the business's own site, so a larger number buys noise, not recall.
    WEBSITE_DISCOVERY_MAX_RESULTS: int = 5

    #: How many leads `discover_many` resolves at once. Low by default because the default
    #: backend serialises behind its own limiter anyway; it exists to bound a keyed backend.
    WEBSITE_DISCOVERY_CONCURRENCY: int = 3

    #: Confidence a candidate must reach before its domain is attached to a lead. A wrong
    #: website looks like data while an empty one visibly reads as a gap, so this is set where
    #: declining to guess is the default outcome for weak evidence.
    WEBSITE_DISCOVERY_MIN_CONFIDENCE: float = 0.5

    #: Whether to confirm a discovered URL actually resolves before attaching it. On by
    #: default: a domain that scored well but does not serve anything is a dead link written
    #: onto a lead, which is the failure mode this whole service is built to avoid.
    WEBSITE_DISCOVERY_VALIDATE_URL: bool = True

    #: Timeout for that reachability check. Deliberately shorter than the search timeout —
    #: it runs once per discovered lead and is the last thing standing between a completed
    #: search and a returned result.
    WEBSITE_DISCOVERY_VALIDATE_TIMEOUT_SECONDS: float = 5.0

    # ---------------------------------------------------------------------------------
    # Contact extraction (lead enrichment)
    # ---------------------------------------------------------------------------------
    # Settings for `ContactExtractorService`, which visits a lead's website and extracts the
    # contact details published on it. Like website discovery, nothing here has a credential:
    # the service reads public pages that any browser would.

    #: Per-request timeout, in seconds. Short, for the same reason discovery's is: a small
    #: studio's site that has not answered in ten seconds is not going to, and enrichment must
    #: never be the reason an import feels hung.
    CONTACT_EXTRACTION_TIMEOUT_SECONDS: float = 10.0

    #: Contact identity sent as the User-Agent and matched against `robots.txt` rules. This is
    #: the string a site owner sees in their logs and writes a Disallow against, so it must
    #: stay honest — set a real contact address in production.
    CONTACT_EXTRACTION_USER_AGENT: str = (
        "ColourLabsCRM/1.0 (lead-enrichment; contact: admin@colourlabs.example)"
    )

    #: Whether `robots.txt` is honoured. Left True in production. It exists as a switch only
    #: because a test would otherwise have to stub a robots.txt for every fixture site; there
    #: is no legitimate operational reason to turn it off.
    CONTACT_EXTRACTION_RESPECT_ROBOTS: bool = True

    #: Cap on second-level pages fetched per lead (the contact/about pages linked from the
    #: home page). Crawl depth itself is fixed at one level and is deliberately NOT
    #: configurable — it is a structural property of `extract()`, not a tunable.
    CONTACT_EXTRACTION_MAX_SUBPAGES: int = 4

    #: How many leads `extract_many` visits at once. This fans out across *different* sites;
    #: requests to any single host are serialised by the per-host limiter regardless.
    CONTACT_EXTRACTION_CONCURRENCY: int = 3

    #: Minimum seconds between two requests to the *same host*. The obligation is owed per
    #: server, so unrelated domains never queue behind each other.
    CONTACT_EXTRACTION_MIN_REQUEST_INTERVAL_SECONDS: float = 1.0

    #: Cap on a single response body, in bytes. A page larger than this is truncated rather
    #: than rejected: header and footer are near the top, so a truncated parse still finds
    #: them, and one pathological page cannot exhaust memory mid-import.
    CONTACT_EXTRACTION_MAX_PAGE_BYTES: int = 2_000_000

    #: Cap on redirects followed for a single page fetch. Bounded because a redirect loop, or
    #: a chain that walks us off the business's own domain onto a parking page, is the one
    #: fetch failure mode that costs unbounded time rather than returning an error.
    CONTACT_EXTRACTION_MAX_REDIRECTS: int = 5

    #: Default region for parsing bare national numbers with libphonenumber. Indian sites
    #: overwhelmingly print "9876543210" with no country code; without a region that string
    #: is unparseable. A number that carries its own "+<cc>" is unaffected by this.
    CONTACT_EXTRACTION_PHONE_REGION: str = "IN"

    #: Minimum relevance score at or above which a site is considered to *belong* to the lead
    #: (see `ContactExtractorService._score_relevance`). This is advisory only: a low score is
    #: reported to the caller, never used to discard a website or drop extracted contacts.
    CONTACT_EXTRACTION_MIN_RELEVANCE: float = 0.3

    # ---------------------------------------------------------------------------------------
    # The lead-collection brief names these five knobs with a WEBSITE_ prefix. The canonical
    # settings are the CONTACT_EXTRACTION_* ones above — they were named for the service that
    # reads them and are what the code uses. These aliases exist so that an operator who sets
    # the documented WEBSITE_* name in `.env` gets the behaviour they expect instead of a
    # silently ignored variable. Each resolves to its canonical value unless explicitly set.
    # ---------------------------------------------------------------------------------------

    WEBSITE_CONTACT_TIMEOUT: float | None = None
    WEBSITE_MAX_PAGES_PER_LEAD: int | None = None
    WEBSITE_MAX_RESPONSE_BYTES: int | None = None
    WEBSITE_MAX_REDIRECTS: int | None = None
    WEBSITE_MAX_CONCURRENT_REQUESTS: int | None = None

    @model_validator(mode="after")
    def _apply_website_aliases(self) -> "Settings":
        """
        Lets the brief's `WEBSITE_*` names override the canonical `CONTACT_EXTRACTION_*` ones.

        Runs after parsing so that an alias set in the environment wins, while an unset alias
        (None) leaves the canonical default alone. Done here rather than with a validation
        alias because `WEBSITE_MAX_PAGES_PER_LEAD` counts *total* pages per lead while
        `CONTACT_EXTRACTION_MAX_SUBPAGES` counts the second-level ones — the home page is
        always fetched — so the two differ by one and cannot simply share a field.
        """
        if self.WEBSITE_CONTACT_TIMEOUT is not None:
            self.CONTACT_EXTRACTION_TIMEOUT_SECONDS = self.WEBSITE_CONTACT_TIMEOUT
        if self.WEBSITE_MAX_PAGES_PER_LEAD is not None:
            # Total pages includes the home page, which is not optional.
            self.CONTACT_EXTRACTION_MAX_SUBPAGES = max(0, self.WEBSITE_MAX_PAGES_PER_LEAD - 1)
        if self.WEBSITE_MAX_RESPONSE_BYTES is not None:
            self.CONTACT_EXTRACTION_MAX_PAGE_BYTES = self.WEBSITE_MAX_RESPONSE_BYTES
        if self.WEBSITE_MAX_REDIRECTS is not None:
            self.CONTACT_EXTRACTION_MAX_REDIRECTS = self.WEBSITE_MAX_REDIRECTS
        if self.WEBSITE_MAX_CONCURRENT_REQUESTS is not None:
            self.CONTACT_EXTRACTION_CONCURRENCY = self.WEBSITE_MAX_CONCURRENT_REQUESTS
        return self

    # PostgreSQL Database Credentials
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        """
        Generates the asynchronous database connection URI (uses asyncpg driver).
        Example: postgresql+asyncpg://postgres:postgres@localhost:5432/colourlabs_crm
        """
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def SYNC_DATABASE_URI(self) -> str:
        """
        Generates the synchronous database connection URI (uses default postgresql driver).
        Required for Alembic migrations, which are traditionally run synchronously.
        Example: postgresql://postgres:postgres@localhost:5432/colourlabs_crm
        """
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


# Instantiate a singleton config object to be imported across the application
settings = Settings()
