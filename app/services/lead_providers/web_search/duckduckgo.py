"""
app/services/lead_providers/web_search/duckduckgo.py

The default `SearchBackend`: DuckDuckGo's no-JavaScript HTML endpoint.

Why this is the default
-----------------------
It needs **no credential**, so website discovery works on a fresh checkout with nothing
configured — the same reason `OverpassLeadProvider` is the default lead source alongside the
billed Google adapter. An operator who later wants a contractual SLA adds a keyed backend and
flips `WEB_SEARCH_BACKEND`; nothing in `WebsiteDiscoveryService` changes.

The trade, stated plainly
-------------------------
The response is an **HTML SERP, not a documented API**. There is no version guarantee and no
support channel: a markup change silently breaks the parse. Everything below is shaped by
that, and the whole of the HTML-specific mess is confined to this file, per the brief.

The parse is therefore *defensive rather than clever*. An unrecognised page yields **zero
results** — the lead is returned unchanged — never an exception and never a garbage URL. This
is the right failure direction: a missing website is a visible gap, a wrong one looks like
data. `_parse` skips anything it does not recognise instead of guessing.

Being a guest on someone else's unmetered endpoint
--------------------------------------------------
This is not a paid API with a quota that entitles us to burst. Four constraints, all here:

  * **robots.txt is fetched and honoured** (`_robots_allows`), cached for the process
    lifetime. Skipping this because "it is only a few requests" is exactly the reasoning that
    gets a source blocked for everyone.
  * **Requests are serialised behind a lock** and spaced by `WEB_SEARCH_MIN_REQUEST_INTERVAL_SECONDS`,
    so concurrent discoveries queue rather than burst.
  * **Retries use exponential backoff with jitter**, and only for faults a retry can fix
    (timeouts, connection errors, 429, 5xx). Retrying a 403 just gets blocked faster.
  * **Timeouts are short** — a SERP that has not answered in ten seconds is not going to, and
    enrichment must never be why an import feels hung.
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from app.core.config import settings
from app.services.lead_providers.web_search.base import (
    SearchBackend,
    SearchBackendError,
    SearchResult,
    register_search_backend,
)

logger = logging.getLogger(__name__)


def _import_httpx() -> Any:
    """
    Imports `httpx` lazily, turning an absent dependency into a `SearchBackendError` rather
    than an import-time crash.

    Deferred for the same reason as in `google_maps.py` and `overpass.py`: this module is
    imported during startup wiring, and a hard top-level import would take the whole API down
    on a machine where the optional dependency is missing. Here that would mean an unrelated
    enrichment dependency breaking login.
    """
    try:
        import httpx  # noqa: PLC0415 - deferred on purpose, see docstring
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SearchBackendError(
            "The 'httpx' package is required for web search but is not installed. "
            "Install it with: pip install httpx"
        ) from exc
    return httpx


#: HTTP statuses worth retrying: rate limiting and transient server faults. A 4xx other than
#: 429 is a decision about *us* — retrying it wastes the budget and hastens a block.
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


@register_search_backend
class DuckDuckGoSearchBackend(SearchBackend):
    """
    Searches via DuckDuckGo's HTML endpoint. Zero credentials, HTML parsing isolated here.

    One instance holds the rate limiter, so a caller that wants requests actually serialised
    must share the instance — which `WebsiteDiscoveryService` does by constructing its
    backend once. The limiter is instance state on purpose; everything else is stateless.
    """

    key = "duckduckgo"
    display_name = "DuckDuckGo (HTML endpoint)"
    requires_credentials = False

    def __init__(
        self,
        base_url: str | None = None,
        min_request_interval: float | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        respect_robots: bool | None = None,
    ) -> None:
        """
        Args:
            base_url: Endpoint override, so a test can drive a stub and an operator can point
                at a mirror without a code change.
            min_request_interval: Politeness gap between outbound requests. Overridden in
                tests so a suite does not spend a real second per request.
            timeout_seconds: Per-attempt timeout.
            max_attempts: Total attempts including the first. 1 disables retrying.
            respect_robots: Whether to fetch and honour robots.txt. Only ever set False by
                tests, which reach no network at all.
        """
        self._base_url = (base_url or settings.WEB_SEARCH_DDG_URL).strip()
        self._min_interval = max(
            0.0,
            min_request_interval
            if min_request_interval is not None
            else settings.WEB_SEARCH_MIN_REQUEST_INTERVAL_SECONDS,
        )
        self._timeout = (
            timeout_seconds if timeout_seconds is not None
            else settings.WEB_SEARCH_TIMEOUT_SECONDS
        )
        self._max_attempts = max(
            1,
            max_attempts if max_attempts is not None
            else settings.WEB_SEARCH_MAX_ATTEMPTS,
        )
        self._respect_robots = (
            respect_robots if respect_robots is not None
            else settings.WEB_SEARCH_RESPECT_ROBOTS
        )
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None
        #: None until robots.txt has been consulted once; then the cached verdict. Cached for
        #: the process lifetime because re-fetching it per search would itself be the kind of
        #: traffic robots.txt exists to limit.
        self._robots_allowed: bool | None = None

    # -----------------------------------------------------------------------------------
    # SearchBackend
    # -----------------------------------------------------------------------------------

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        """
        Issues one search and returns up to `limit` parsed results, best-ranked first.

        POST rather than GET because `html.duckduckgo.com/html/` expects a form submission and
        answers a bare GET with a consent interstitial containing no results — a GET
        implementation looks like it works and silently returns nothing.
        """
        cleaned = (query or "").strip()
        if not cleaned or limit <= 0:
            return []

        httpx = _import_httpx()

        if self._respect_robots and not await self._robots_allows(httpx):
            raise SearchBackendError(
                f"robots.txt at {self._robots_url()} disallows fetching {self._base_url}."
            )

        body = await self._fetch_with_retries(httpx, cleaned)
        return self._parse(body, limit)

    # -----------------------------------------------------------------------------------
    # Transport: retries, backoff, rate limiting
    # -----------------------------------------------------------------------------------

    async def _fetch_with_retries(self, httpx: Any, query: str) -> str:
        """
        Performs the search request, retrying transient faults with exponential backoff.

        Backoff is `base * 2**attempt` plus jitter, capped. Jitter matters because several
        concurrent imports that all failed on the same upstream blip would otherwise retry in
        lockstep and reproduce the burst that caused it.

        Exhausting the attempts raises `SearchBackendError` — the caller turns that into "lead
        unchanged", so a persistent outage costs nothing beyond the enrichment it could not do.
        """
        last_error: str = "no attempt was made"

        for attempt in range(self._max_attempts):
            if attempt:
                delay = min(
                    settings.WEB_SEARCH_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    settings.WEB_SEARCH_RETRY_BACKOFF_MAX_SECONDS,
                )
                # Full jitter over the computed window rather than a fixed sleep.
                await asyncio.sleep(delay * (0.5 + random.random() * 0.5))
                logger.debug(
                    "Retrying DuckDuckGo search (attempt %d/%d) after: %s",
                    attempt + 1, self._max_attempts, last_error,
                )

            try:
                status, body = await self._request(httpx, query)
            except Exception as exc:  # noqa: BLE001 - classified immediately below
                if not self._is_retryable_exception(httpx, exc):
                    raise SearchBackendError(f"DuckDuckGo request failed: {exc}") from exc
                last_error = f"transport error: {exc}"
                continue

            if status < 400:
                return body
            if status in _RETRYABLE_STATUS:
                last_error = f"HTTP {status}"
                continue
            # A non-retryable status is a decision about this client; retrying makes it worse.
            raise SearchBackendError(f"DuckDuckGo returned HTTP {status}.")

        raise SearchBackendError(
            f"DuckDuckGo search failed after {self._max_attempts} attempt(s): {last_error}"
        )

    async def _request(self, httpx: Any, query: str) -> tuple[int, str]:
        """
        Issues one rate-limited POST and returns `(status_code, body)`.

        Redirects are followed but **bounded** by `WEB_SEARCH_MAX_REDIRECTS`: a redirect loop
        or a chain into a consent wall must terminate rather than consume the timeout.
        """
        await self._throttle()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers=self._headers(),
                follow_redirects=True,
                max_redirects=settings.WEB_SEARCH_MAX_REDIRECTS,
            ) as client:
                response = await client.post(
                    self._base_url,
                    data={"q": query, "kl": settings.WEB_SEARCH_REGION},
                )
            return response.status_code, response.text
        finally:
            self._mark_request_finished()

    @staticmethod
    def _headers() -> dict[str, str]:
        """
        Request headers. The User-Agent is a real, identifying string with a contact address:
        an absent or obviously-scripted agent is the fastest route to a challenge page, and an
        operator we can be contacted about is the difference between a rate limit and a ban.
        """
        return {
            "User-Agent": settings.WEB_SEARCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-IN,en;q=0.9",
        }

    @staticmethod
    def _is_retryable_exception(httpx: Any, exc: Exception) -> bool:
        """
        Whether a transport exception is worth another attempt.

        Timeouts and connection faults are transient by nature. Anything else — a malformed
        URL, a protocol violation — will fail identically on retry, so it is surfaced at once
        rather than after the full backoff schedule.
        """
        retryable = (
            getattr(httpx, "TimeoutException", ()),
            getattr(httpx, "ConnectError", ()),
            getattr(httpx, "ReadError", ()),
            getattr(httpx, "RemoteProtocolError", ()),
        )
        retryable = tuple(t for t in retryable if isinstance(t, type))
        return bool(retryable) and isinstance(exc, retryable)

    async def _throttle(self) -> None:
        """
        Waits until it is polite to issue the next request, holding the lock so concurrent
        discoveries queue rather than burst. Released by `_mark_request_finished`, which is
        why every caller wraps the request in `try/finally`.
        """
        await self._lock.acquire()
        if self._last_request_at is not None and self._min_interval > 0:
            elapsed = asyncio.get_running_loop().time() - self._last_request_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

    def _mark_request_finished(self) -> None:
        """Stamps the completion time and lets the next queued caller through."""
        try:
            self._last_request_at = asyncio.get_running_loop().time()
        except RuntimeError:  # pragma: no cover - only if released outside a loop
            self._last_request_at = None
        if self._lock.locked():
            self._lock.release()

    # -----------------------------------------------------------------------------------
    # robots.txt
    # -----------------------------------------------------------------------------------

    def _robots_url(self) -> str:
        """The robots.txt URL for the configured endpoint's origin."""
        return urljoin(self._base_url, "/robots.txt")

    async def _robots_allows(self, httpx: Any) -> bool:
        """
        Reports whether robots.txt permits fetching the search endpoint, cached per process.

        **Fetch failures resolve to allowed.** A robots.txt we could not retrieve is not a
        directive to stay away — treating an unreachable file as a prohibition would disable
        discovery entirely on any transient network fault, which is a worse outcome than
        proceeding under the same terms as a browser. An explicit `Disallow` is honoured.
        """
        if self._robots_allowed is not None:
            return self._robots_allowed

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={"User-Agent": settings.WEB_SEARCH_USER_AGENT},
                follow_redirects=True,
                max_redirects=settings.WEB_SEARCH_MAX_REDIRECTS,
            ) as client:
                response = await client.get(self._robots_url())
            if response.status_code >= 400:
                self._robots_allowed = True
            else:
                self._robots_allowed = self._robots_permits(
                    response.text, urlparse(self._base_url).path or "/"
                )
        except Exception as exc:  # noqa: BLE001 - unreachable robots.txt is not a ban
            logger.debug("robots.txt fetch failed (%s); proceeding.", exc)
            self._robots_allowed = True

        if not self._robots_allowed:
            logger.warning("robots.txt disallows %s; web search disabled.", self._base_url)
        return self._robots_allowed

    @staticmethod
    def _robots_permits(body: str, path: str) -> bool:
        """
        Minimal robots.txt evaluation for the wildcard (`User-agent: *`) group.

        Deliberately not a full RFC 9309 implementation — no `Allow` precedence rules, no
        per-agent groups beyond the wildcard, no crawl-delay parsing. It answers one question
        ("is this one path disallowed to everyone") and errs toward *not* fetching when a rule
        matches, which is the conservative direction. `urllib.robotparser` is stdlib but
        synchronous and would block the event loop on its own fetch, so the fetch stays here
        and only the matching is reimplemented.
        """
        in_wildcard_group = False
        allowed = True
        for raw_line in body.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()

            if field == "user-agent":
                in_wildcard_group = value == "*"
            elif in_wildcard_group and field == "disallow" and value:
                if path.startswith(value):
                    allowed = False
            elif in_wildcard_group and field == "allow" and value:
                # An explicit Allow for a more specific path wins, matching the common
                # convention even though full precedence rules are out of scope.
                if path.startswith(value):
                    allowed = True
        return allowed

    # -----------------------------------------------------------------------------------
    # HTML parsing — the whole DuckDuckGo-specific surface lives below this line
    # -----------------------------------------------------------------------------------

    #: Organic results are `<a class="result__a" href="...">title</a>`, optionally followed by
    #: an `<a class="result__snippet">`. Anchored on those class names because they are the
    #: most stable thing on the page; the snippet group is optional so a result without one is
    #: still captured rather than dropped.
    _RESULT_PATTERN = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        r'(?:.*?<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>)?',
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def _parse(cls, body: str, limit: int) -> list[SearchResult]:
        """
        Extracts `(url, title, snippet)` triples from a DuckDuckGo HTML SERP.

        Regex rather than an HTML parser because no parser is a dependency of this project and
        adding one for a single defensive extraction is not worth the supply-chain surface.
        Anything unrecognised is skipped, so a SERP redesign degrades this to "no candidates",
        never to wrong candidates.

        De-duplicates by URL: the same site ranking twice is one candidate, and letting it
        occupy two of the `limit` slots would crowd out a genuine alternative.
        """
        if not body:
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()

        for match in cls._RESULT_PATTERN.finditer(body):
            url = cls._unwrap(html.unescape(match.group(1).strip()))
            if not url:
                continue
            key = url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(
                SearchResult(
                    url=url,
                    title=_strip_tags(match.group(2)),
                    snippet=_strip_tags(match.group(3)),
                )
            )
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _unwrap(href: str) -> str | None:
        """
        Resolves DuckDuckGo's redirect wrapper to the real destination.

        Results are served as `//duckduckgo.com/l/?uddg=<encoded target>`. Storing that
        wrapper as a lead's website would save a tracking URL that breaks the moment the
        redirector changes, and would defeat domain scoring entirely — every candidate would
        look like duckduckgo.com. A wrapper that cannot be unwrapped is dropped, not kept.
        """
        if not href:
            return None
        candidate = href.strip()
        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        try:
            parsed = urlparse(candidate)
        except ValueError:
            return None

        if parsed.path.startswith("/l/") or "uddg=" in (parsed.query or ""):
            target = parse_qs(parsed.query).get("uddg", [None])[0]
            if not target:
                return None
            candidate = unquote(target)

        if not candidate.lower().startswith(("http://", "https://")):
            return None
        return candidate


def _strip_tags(value: str | None) -> str | None:
    """Reduces an HTML fragment to its text, for titles and snippets."""
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
