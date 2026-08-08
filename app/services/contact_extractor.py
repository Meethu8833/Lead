"""
app/services/contact_extractor.py

This file implements `ContactExtractorService` — the enrichment step that visits a normalized
lead's website and extracts the contact details published on it.

Where it sits
-------------
It is the natural successor to `WebsiteDiscoveryService`, and deliberately the same shape: an
Application-layer *service*, not a `LeadProvider`. Discovery answers "given a business, what
is its website"; this answers "given a website, how do I contact this business". They compose
in that order, and `walkthrough.md` names this step as the highest-value improvement available
after discovery — a studio's own site is the most authoritative contact source there is, and
far better evidence than a directory listing.

It is **read-only with respect to the database**: it imports no model, no repository and no
session, takes `NormalizedLead` objects and returns `NormalizedLead` objects. Persistence
stays exactly where it already is, in `LeadImportService`. This is asserted structurally in
the test suite, the same way it is for discovery.

The pipeline, per lead
----------------------
    no website ──────────────▶ returned untouched (nothing to visit)
    website present ─────────▶ robots.txt ──▶ disallowed ──▶ returned untouched
                             ──▶ allowed ──▶ fetch home page
                                          ──▶ extract from header + footer + whole page
                                          ──▶ pick <=N contact/about links (SAME HOST ONLY)
                                          ──▶ fetch each (depth 1 — they are never followed)
                                          ──▶ merge, normalize, dedupe ──▶ enriched lead

Why depth is capped at one, structurally
----------------------------------------
The brief says one level, and "do not crawl the entire website". That is enforced by the
*shape* of `extract()`, not by a counter that a later edit could increment: there is exactly
one call to `_fetch_page` for the home page and exactly one `_fetch_page` per selected link,
and the links harvested from those second-level pages are never themselves visited. There is
no recursion and no work queue in this module, so there is no way for it to become a crawler
without being restructured. `CONTACT_EXTRACTION_MAX_SUBPAGES` then bounds the second level to a few pages
whose *link text or path* says "contact" or "about" — we do not fetch a page merely because it
exists.

Why robots.txt is honoured even though we fetch so little
---------------------------------------------------------
Visiting a handful of pages on a small business's site is unremarkable traffic, but the
operator of that site is entitled to say no, and the cost of asking is one cached request per
host. `urllib.robotparser` is in the standard library and implements the grammar we need. A
robots.txt that cannot be fetched is treated as *allowing* — that is the documented convention
(an absent robots.txt permits everything), and treating a 500 as a prohibition would make the
feature fail closed against sites that never intended to restrict anything. A robots.txt that
is fetched and *does* disallow us is final: the lead is returned unchanged.

Why every extraction is additive and never overwrites
-----------------------------------------------------
A lead reaching this service already carries whatever its provider found, and a provider that
read a Google Places record has better-attributed data than a regex over HTML. So scraped
values are *appended* to `phone_numbers` and `emails` (deduplicated by the same comparison
keys `NormalizedLead` uses), and single-valued fields — `instagram`, `facebook`, `website` —
are filled **only when empty**. `youtube` and `whatsapp` have no column on `NormalizedLead`;
rather than widen a DTO shared by every provider, they are returned on the
`ExtractionOutcome` and mirrored into `lead.raw["contact_extraction"]`, which is the field
that exists precisely to carry provider-specific detail to the operator.

Failure is always "return the lead unchanged"
---------------------------------------------
`extract()` never raises for an ordinary miss. A dead domain, a TLS error, a timeout, a
robots.txt prohibition, a 404, a page of JavaScript with no markup — all resolve to the input
lead, because this is enrichment: an import of two hundred leads must not fail because one
site was down.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.robotparser
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence
from urllib.parse import urljoin, urlparse, unquote

from app.core.config import settings
from app.services.lead_providers.normalized import (
    NormalizedLead,
    normalize_email,
    normalize_instagram,
    normalize_phone,
    normalize_url,
)
# Reused rather than reimplemented: the relevance signal below compares a page against a lead
# using exactly the tokenisation and domain rules discovery already uses to compare a search
# result against a lead. Two different notions of "the name matched" would be a bug waiting
# to happen. `website_discovery` does not import this module, so there is no cycle.
from app.services.website_discovery import _significant_tokens, registrable_domain

logger = logging.getLogger(__name__)


# ===========================================================================================
# Page selection — what "one level" means
# ===========================================================================================
# A second-level page is fetched only if its link text or its URL path matches one of these.
# We are looking for the pages a human would click to find a phone number, and nothing else:
# fetching every internal link is the crawl this service is specified not to perform.
_CONTACT_HINTS: tuple[str, ...] = (
    "contact", "contact-us", "contactus", "get-in-touch", "getintouch", "reach-us",
    "reachus", "enquiry", "enquire", "inquiry", "book", "booking", "connect",
)
_ABOUT_HINTS: tuple[str, ...] = (
    "about", "about-us", "aboutus", "who-we-are", "whoweare", "our-story", "ourstory",
    "profile", "team",
)
#: Extensions that are never an HTML contact page. Checked before fetching so we do not pull
#: a brochure PDF through the parser.
_NON_HTML_SUFFIXES: tuple[str, ...] = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".jpg", ".jpeg", ".png", ".gif",
    ".svg", ".webp", ".mp4", ".mp3", ".avi", ".mov", ".ico", ".css", ".js",
)

#: Elements whose text is markup noise rather than page content. Removed before the text of a
#: page is scanned for phone numbers, so a phone-shaped substring inside a script's tracking
#: payload cannot become a lead's phone number.
_NOISE_TAGS: tuple[str, ...] = ("script", "style", "noscript", "template", "svg")


# ===========================================================================================
# Social platform patterns
# ===========================================================================================
# Matched against href values. Anchored on the host so that a link to an article *about*
# Instagram does not become the business's Instagram handle.
_INSTAGRAM_RE = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?instagram\.com/([^/?#\s]+)", re.IGNORECASE
)
_FACEBOOK_RE = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?(?:facebook\.com|fb\.com|fb\.me)/([^?#\s]+)",
    re.IGNORECASE,
)
_YOUTUBE_RE = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)?(?:youtube\.com|youtu\.be)/([^?#\s]+)", re.IGNORECASE
)

#: Path segments that are the platform's own furniture rather than a business profile. A
#: footer's "share on Facebook" button points at `facebook.com/sharer/...`; attaching that as
#: the studio's page would be wrong in a way that looks right.
_SOCIAL_NOISE_SEGMENTS: frozenset[str] = frozenset({
    "sharer", "share", "share.php", "dialog", "plugins", "tr", "login", "signup",
    "home", "explore", "accounts", "p", "reel", "reels", "stories", "embed",
    "privacy", "policies", "terms", "help", "about", "watch", "results", "feed",
    "channel_redirect", "redirect", "intent", "hashtag", "profile.php",
})

#: WhatsApp link forms. `wa.me/<number>` and `api.whatsapp.com/send?phone=<number>` are the
#: two the wild actually uses; both carry the number in the URL, which is why a WhatsApp
#: number can be extracted with confidence while a bare number on a page cannot be known to
#: be WhatsApp-capable.
_WHATSAPP_RE = re.compile(
    r"^https?://(?:api\.whatsapp\.com/send|(?:web\.|chat\.)?whatsapp\.com/send|wa\.me)",
    re.IGNORECASE,
)


# ===========================================================================================
# Contact patterns
# ===========================================================================================
# Emails are taken from `mailto:` links (authoritative) and from page text (best-effort). The
# text pattern is deliberately stricter than the RFC: it exists to find addresses in prose,
# and a pattern that accepts everything legal also accepts every version string and filename.
_EMAIL_TEXT_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

#: Image and asset filenames read exactly like email addresses once you strip the path
#: ("logo@2x.png"), and obfuscated addresses often carry a sentinel. Rejected on the domain
#: part rather than the whole string so a real address at a `.photography` TLD survives.
_EMAIL_REJECT_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".js", ".json",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webm", ".pdf",
)
_EMAIL_REJECT_LOCALS: frozenset[str] = frozenset({
    "example", "sentry", "your", "youremail", "email", "name", "user", "username",
    "someone", "test", "domain", "yourname", "info@example",
})
_EMAIL_REJECT_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net", "domain.com", "yourdomain.com",
    "email.com", "sentry.io", "wixpress.com", "sentry.wixpress.com", "2x.png",
})

#: Phone numbers in page text. Requires a leading `+`/`(`/digit and 7-15 digits with the
#: separators humans actually type. Kept conservative: `tel:` links are the authoritative
#: source and this pattern is the fallback for sites that print the number as plain text.
_PHONE_TEXT_RE = re.compile(
    r"(?<![\w@.])"
    r"(?:\+?\d{1,3}[\s.\-]?)?"          # optional country code
    r"(?:\(\d{2,5}\)[\s.\-]?)?"          # optional parenthesised STD code
    r"\d{3,5}[\s.\-]?\d{3,5}(?:[\s.\-]?\d{0,4})"
    r"(?![\w@])"
)

#: Strings that are digit-shaped but never a phone number. Checked against the *digits only*
#: form, so formatting variations cannot slip past.
_PHONE_REJECT_EXACT: frozenset[str] = frozenset({
    "1234567890", "0000000000", "1111111111", "9999999999", "1234567891",
    "12345678901", "0123456789",
})

#: Years, prices, pincodes and IDs are the dominant false positives in page text. A candidate
#: whose surrounding text is a date or a currency amount is dropped; see `_looks_like_phone`.
_MIN_PHONE_DIGITS = 8
_MAX_PHONE_DIGITS = 15


class ContactExtractionError(Exception):
    """
    Raised inside the fetch layer when a page cannot be retrieved.

    Never escapes `extract()` — it is caught there and turned into an outcome — but it lets
    the fetch helpers fail loudly among themselves rather than returning a sentinel that a
    caller might forget to check.

    `status` names the outcome this failure maps to, so `extract_with_outcome` can classify a
    fetch failure by *type* rather than by matching on the message text. It defaults to the
    generic `fetch_failed`; the two subclasses below carry the more specific values.
    """

    status: str = "fetch_failed"


class RobotsBlockedError(ContactExtractionError):
    """Raised when robots.txt forbids the URL. Not a fault — the site said no, and we obey."""

    status: str = "robots_blocked"


class InvalidContentError(ContactExtractionError):
    """
    Raised when a response arrives intact but is not usable HTML — a PDF, an image, a body
    that exceeds the size cap. Distinguished from a transport failure because retrying will
    not help and because the operator reads the two very differently.
    """

    status: str = "invalid_content"


def _import_bs4() -> Any:
    """
    Imports `BeautifulSoup` lazily, converting an absent dependency into an extraction error
    rather than an import-time crash.

    Deferred for the same reason `website_discovery._import_httpx` is: this module is imported
    during startup wiring, and a hard top-level import would take the whole API down on a
    machine where the optional dependency is missing. Enrichment degrades; the CRM stays up.
    """
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415 - deferred on purpose, see docstring
    except ImportError as exc:
        raise ContactExtractionError(
            "The 'beautifulsoup4' package is required for contact extraction but is not "
            "installed. Install it with: pip install beautifulsoup4"
        ) from exc
    return BeautifulSoup


def _import_httpx() -> Any:
    """Imports `httpx` lazily, for the same reason as `_import_bs4`."""
    try:
        import httpx  # noqa: PLC0415 - deferred on purpose, see docstring
    except ImportError as exc:
        raise ContactExtractionError(
            "The 'httpx' package is required for contact extraction but is not installed. "
            "Install it with: pip install httpx"
        ) from exc
    return httpx


def _import_phonenumbers() -> Any:
    """
    Imports `phonenumbers` lazily, returning None when it is absent.

    Unlike bs4 and httpx this one *degrades* rather than raising: without a parser we cannot
    fetch a page at all, but without libphonenumber we can still fall back to the structural
    heuristics in `_looks_like_phone`. A deployment that has not yet installed the new
    dependency therefore keeps working with slightly weaker phone validation instead of
    failing every extraction.
    """
    try:
        import phonenumbers  # noqa: PLC0415 - deferred on purpose, see docstring
    except ImportError:
        logger.warning(
            "The 'phonenumbers' package is not installed; contact extraction will fall back "
            "to heuristic phone validation. Install it with: pip install phonenumbers"
        )
        return None
    return phonenumbers


def _make_soup(markup: str) -> Any:
    """
    Parses HTML with the best available parser.

    `lxml` is faster and more forgiving on the malformed markup small-business sites are built
    from, but it is a compiled dependency we do not require; `html.parser` ships with Python
    and is the guaranteed fallback. Selecting here rather than at each call site means the
    choice is made once and every parse in this module is consistent.
    """
    BeautifulSoup = _import_bs4()
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception:  # noqa: BLE001 - any lxml absence/fault falls back to the stdlib parser
        return BeautifulSoup(markup, "html.parser")


# ===========================================================================================
# Normalisation helpers
# ===========================================================================================

def _digits(value: str) -> str:
    """Returns just the digits of a string, for comparisons that ignore formatting."""
    return re.sub(r"\D", "", value or "")


def _parse_phone(candidate: str, region: str | None = None) -> Any:
    """
    Parses a scraped string with libphonenumber and returns the parsed object, or None.

    `phonenumbers` is what turns "080 12345678", "+91 98765 43210" and "0091 9876543210" into
    the same comparable object without us maintaining a table of Indian numbering-plan rules.
    Parsing is attempted against `region` (default `CONTACT_EXTRACTION_PHONE_REGION`, i.e. IN)
    so that a bare ten-digit mobile — how most Indian sites print their number — resolves at
    all; a string carrying its own `+<cc>` is parsed as written and keeps its real country.

    Returns None rather than raising on unparseable input: a page of prose yields dozens of
    digit runs, and every one of them arrives here.
    """
    phonenumbers = _import_phonenumbers()
    if phonenumbers is None:
        return None
    text = (candidate or "").strip()
    if not text:
        return None
    region = region or settings.CONTACT_EXTRACTION_PHONE_REGION
    # A leading "0091"/"00 91" is the ISO international prefix; libphonenumber understands
    # "+" far more reliably than it does a country's own exit code.
    text = re.sub(r"^\s*00(?=\d)", "+", text)
    try:
        return phonenumbers.parse(text, region)
    except Exception:  # noqa: BLE001 - NumberParseException and anything else means "not a number"
        return None


def _looks_like_phone(candidate: str) -> bool:
    """
    Reports whether a digit-bearing string is plausibly a dialable number.

    This is the guard that keeps years, prices, pincodes, GST numbers and image dimensions out
    of a lead's phone list. Text scraping produces these constantly, and a wrong phone number
    is worse than a missing one — it is the field the CRM deduplicates on, so a bogus value can
    collapse two unrelated businesses onto one lead.

    The cheap structural checks run first because they reject the bulk of the candidates for
    free; libphonenumber's `is_valid_number` — which knows that 1234567890 is not an
    assignable Indian range while 9876543210 is — is the authority that decides the rest.
    """
    digits = _digits(candidate)
    if not (_MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS):
        return False
    if digits in _PHONE_REJECT_EXACT:
        return False
    # A single repeated digit ("888888888") is placeholder markup, never a real number.
    if len(set(digits)) <= 2:
        return False
    # `normalize_phone` is what the CRM will compare on; if it declines the value, storing it
    # would create a lead whose phone can never be matched.
    if normalize_phone(candidate) is None:
        return False

    phonenumbers = _import_phonenumbers()
    if phonenumbers is None:
        # Without the library we keep the historical heuristic behaviour rather than
        # rejecting everything: the structural checks above are still meaningful.
        return True
    parsed = _parse_phone(candidate)
    if parsed is None:
        return False
    return bool(phonenumbers.is_valid_number(parsed))


def _to_e164(candidate: str) -> str | None:
    """
    Renders a validated number in E.164 (`+919876543210`), or None if it will not validate.

    E.164 is the one representation that is unambiguous to a dialler, to WhatsApp, and to a
    human comparing two records, which is why the brief asks for it. Numbers that parse but
    are not valid for their region are refused rather than emitted in a canonical-looking
    form that would lend them false authority.
    """
    phonenumbers = _import_phonenumbers()
    if phonenumbers is None:
        return None
    parsed = _parse_phone(candidate)
    if parsed is None or not phonenumbers.is_valid_number(parsed):
        return None
    try:
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:  # noqa: BLE001 - a formatting fault must not fail an import
        return None


def _clean_phone_display(value: str) -> str:
    """
    Renders a scraped phone number for storage, in E.164 where the number validates.

    E.164 is preferred because it is what the brief asks for and what makes two records of
    one business comparable: a site that prints "098765 43210" and a provider that reported
    "+91 98765 43210" should not produce two phones on one lead. When libphonenumber cannot
    validate the number — an unusual region, or the library being absent — we fall back to
    tidying what the site published rather than discarding it, since the structural checks in
    `_looks_like_phone` have already vouched for its shape.
    """
    canonical = _to_e164(value)
    if canonical:
        return canonical

    cleaned = re.sub(r"[^\d+()\-.\s]", " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -.")
    # A `+` is only meaningful at the front.
    if cleaned.count("+") > 1 or (("+" in cleaned) and not cleaned.startswith("+")):
        cleaned = cleaned.replace("+", "")
        cleaned = cleaned.strip()
    return cleaned[:50]


def _valid_email(candidate: str | None) -> str | None:
    """
    Normalises an email and rejects the asset filenames and placeholder addresses that a
    text scrape produces in volume.

    `normalize_email` already enforces the shape; this adds the domain-specific rejections
    that shape alone cannot catch ("logo@2x.png" is a perfectly well-shaped address).
    """
    cleaned = normalize_email(candidate)
    if not cleaned:
        return None
    if cleaned.endswith(_EMAIL_REJECT_SUFFIXES):
        return None
    local, _, domain = cleaned.partition("@")
    if not local or not domain:
        return None
    if local in _EMAIL_REJECT_LOCALS or domain in _EMAIL_REJECT_DOMAINS:
        return None
    # Sentry/analytics DSNs embed a long hex local part; a real address is not 32 hex chars.
    if len(local) >= 32 and re.fullmatch(r"[0-9a-f]+", local):
        return None
    return cleaned


def _social_url(raw: str, pattern: re.Pattern[str]) -> tuple[str, str] | None:
    """
    Matches a href against a platform pattern and returns `(clean_url, first_path_segment)`,
    or None if it is not a profile link.

    Query strings and fragments are dropped: a profile URL carrying `?igshid=...` is the same
    profile, and storing the tracking parameter makes two records of one page. The first path
    segment is returned so the caller can reject the platform's own furniture.
    """
    match = pattern.match(raw.strip())
    if not match:
        return None
    captured = unquote(match.group(1) or "").strip("/")
    if not captured:
        return None
    first_segment = captured.split("/")[0].lower()
    if not first_segment or first_segment in _SOCIAL_NOISE_SEGMENTS:
        return None
    # Rebuild from the matched portion so query strings and fragments are dropped.
    clean = raw.strip().split("?")[0].split("#")[0].rstrip("/")
    return clean, first_segment


def _whatsapp_number(raw: str) -> str | None:
    """
    Extracts the phone number from a WhatsApp click-to-chat link.

    `wa.me/919876543210` carries it in the path; `api.whatsapp.com/send?phone=91...` carries it
    in the query. This is the only place a number can be *known* to be WhatsApp-capable — a
    number printed in a footer might or might not be on WhatsApp, and guessing would put a
    wrong claim in front of an operator about to message it.
    """
    if not _WHATSAPP_RE.match(raw.strip()):
        return None
    parsed = urlparse(raw.strip())
    candidate = ""
    query = parsed.query or ""
    match = re.search(r"phone=([+\d\s\-]+)", query, re.IGNORECASE)
    if match:
        candidate = match.group(1)
    elif parsed.path:
        candidate = parsed.path.strip("/").split("/")[0]
    candidate = unquote(candidate).strip()
    if not candidate or not _looks_like_phone(candidate):
        return None
    return _clean_phone_display(candidate)


# ===========================================================================================
# Result types
# ===========================================================================================

@dataclass(frozen=True)
class ExtractedContacts:
    """
    The raw contact material harvested from one or more pages, before it is merged onto a
    lead.

    Ordering is preserved throughout and is meaningful: `NormalizedLead` promotes
    `phone_numbers[0]` to the CRM's `phone` column, and the home page's header/footer is
    scanned before any sub-page, so the number a business leads with stays first.
    """

    phones: tuple[str, ...] = ()
    whatsapp: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    instagram: tuple[str, ...] = ()
    facebook: tuple[str, ...] = ()
    youtube: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """True when nothing at all was found, so the caller can skip a pointless merge."""
        return not any(
            (self.phones, self.whatsapp, self.emails,
             self.instagram, self.facebook, self.youtube)
        )

    def merged_with(self, other: "ExtractedContacts") -> "ExtractedContacts":
        """
        Concatenates two harvests, preserving order and dropping exact repeats.

        Used to fold each sub-page's findings into the running total. Deduplication here is by
        literal string; the semantic deduplication (two spellings of one phone number) happens
        once at the merge boundary in `_apply`, using the CRM's own comparison keys.
        """
        def join(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
            seen: set[str] = set()
            out: list[str] = []
            for item in (*a, *b):
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            return tuple(out)

        return ExtractedContacts(
            phones=join(self.phones, other.phones),
            whatsapp=join(self.whatsapp, other.whatsapp),
            emails=join(self.emails, other.emails),
            instagram=join(self.instagram, other.instagram),
            facebook=join(self.facebook, other.facebook),
            youtube=join(self.youtube, other.youtube),
        )

    def to_dict(self) -> dict[str, list[str]]:
        """Renders the harvest as plain lists, for the lead's `raw` block and for logging."""
        return {
            "phones": list(self.phones),
            "whatsapp": list(self.whatsapp),
            "emails": list(self.emails),
            "instagram": list(self.instagram),
            "facebook": list(self.facebook),
            "youtube": list(self.youtube),
        }


@dataclass(frozen=True)
class ExtractionOutcome:
    """
    The result of one extraction, including the reasoning.

    `lead` is always populated — enriched on success, the untouched input on every failure
    path — so a caller that only wants the lead can ignore everything else.

    `status` is one of:

    ``extracted``          every page we asked for was read and contacts were found
    ``partial``            contacts were found, but at least one page failed to load
    ``no_contact_found``   pages loaded fine and published no contact details
    ``fetch_failed``       the home page could not be retrieved (timeout, DNS, 4xx, 5xx)
    ``robots_blocked``     robots.txt forbade the visit
    ``invalid_content``    the response was not usable HTML (wrong type, or over the cap)
    ``no_website``         the lead had no website to visit
    ``unavailable``        a dependency needed for extraction is not installed

    Note that `no_contact_found` is a *successful* run that found nothing, not an error —
    plenty of small sites publish only a form. Callers must not treat it as a failure.
    """

    lead: NormalizedLead
    status: str
    contacts: ExtractedContacts = field(default_factory=ExtractedContacts)
    pages_fetched: tuple[str, ...] = ()
    fields_added: tuple[str, ...] = ()
    detail: str | None = None
    #: Pages that were selected but could not be read. Non-empty is what makes an otherwise
    #: successful extraction `partial`.
    pages_failed: tuple[str, ...] = ()
    #: How strongly the fetched site looks like it belongs to *this* lead, in [0.0, 1.0].
    #: Advisory: see `relevance_status`. None when nothing was fetched to judge.
    relevance_score: float | None = None
    #: `owned` / `uncertain` / `unrelated` / None. A human-readable band over the score.
    relevance_status: str | None = None
    #: The individual signals that produced the score, so an operator can see *why*.
    relevance_signals: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        """
        Whether the visit itself worked, regardless of whether it yielded anything.

        `no_contact_found` counts as success on purpose — the brief is explicit that finding
        no contact information is not a system error.
        """
        return self.status in ("extracted", "partial", "no_contact_found")

    def to_dict(self) -> dict[str, Any]:
        """Renders the outcome for a job log or an API response."""
        return {
            "status": self.status,
            "contacts": self.contacts.to_dict(),
            "pages_fetched": list(self.pages_fetched),
            "pages_failed": list(self.pages_failed),
            "fields_added": list(self.fields_added),
            "relevance_score": self.relevance_score,
            "relevance_status": self.relevance_status,
            "relevance_signals": list(self.relevance_signals),
            "detail": self.detail,
        }


# ===========================================================================================
# robots.txt
# ===========================================================================================

class RobotsCache:
    """
    Fetches and caches one `robots.txt` per host for the lifetime of the instance.

    Cached because a run over two hundred leads from the same directory frequently hits the
    same host repeatedly, and asking a small server for its robots.txt two hundred times is
    exactly the rudeness the file exists to prevent. Cached *per instance* rather than
    globally so a long-lived process cannot pin a stale prohibition forever.

    A host whose robots.txt cannot be fetched is recorded as "allow": an absent robots.txt
    permits everything by convention, and a transport error is indistinguishable from absence
    from out here. A file that *is* retrieved and disallows us is honoured absolutely.
    """

    def __init__(self, user_agent: str, timeout: float, transport: Any = None) -> None:
        """
        Args:
            user_agent: The identity matched against robots.txt rules. This must be the same
                string the page fetcher sends, or we would be obeying rules written for
                someone else.
            timeout: Per-request timeout for the robots.txt fetch itself.
            transport: An `httpx` transport, injected by tests so a canned robots.txt is
                served through the real fetch-and-parse path. None in production.
        """
        self._user_agent = user_agent
        self._timeout = timeout
        self._transport = transport
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def is_allowed(self, url: str) -> tuple[bool, str | None]:
        """
        Reports whether `url` may be fetched, and why not when it may not.

        Returns (True, None) when allowed — including when robots.txt is absent or
        unreachable — and (False, reason) only when a successfully-parsed file says no.
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, f"URL {url!r} has no host to check robots.txt against."
        origin = f"{parsed.scheme}://{parsed.netloc}"

        parser = await self._parser_for(origin)
        if parser is None:
            # No robots.txt, or it could not be read. Convention says that permits fetching.
            return True, None
        try:
            allowed = parser.can_fetch(self._user_agent, url)
        except Exception:  # noqa: BLE001 - a malformed file must not break enrichment
            logger.debug("robots.txt for %s could not be evaluated; allowing.", origin)
            return True, None
        if allowed:
            return True, None
        return False, f"robots.txt at {origin} disallows {self._user_agent} for {url}."

    async def _parser_for(
        self, origin: str
    ) -> urllib.robotparser.RobotFileParser | None:
        """
        Returns the cached parser for an origin, fetching robots.txt on first use.

        The per-origin lock means twenty concurrent leads on one host issue **one** robots.txt
        request between them rather than twenty; the outer guard only protects the lock
        dictionary itself, so different hosts never wait on each other.
        """
        if origin in self._parsers:
            return self._parsers[origin]

        async with self._guard:
            lock = self._locks.setdefault(origin, asyncio.Lock())

        async with lock:
            if origin in self._parsers:  # Filled while we waited for the lock.
                return self._parsers[origin]

            parser = await self._fetch(origin)
            self._parsers[origin] = parser
            return parser

    async def _fetch(self, origin: str) -> urllib.robotparser.RobotFileParser | None:
        """
        Retrieves and parses `<origin>/robots.txt`, or returns None when there is nothing
        enforceable to apply.

        A 4xx (including the overwhelmingly common 404) means no rules exist. A 5xx is
        strictly speaking "retry later", but treating a broken server as a prohibition would
        block enrichment on sites that never configured robots.txt at all, so it is also
        treated as absent — consistent with how mainstream crawlers behave for low-volume,
        non-recursive fetching like ours.
        """
        robots_url = f"{origin}/robots.txt"
        try:
            httpx = _import_httpx()
            timeout = httpx.Timeout(self._timeout)
            headers = {"User-Agent": self._user_agent}
            client_kwargs: dict[str, Any] = {"timeout": timeout, "headers": headers}
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(robots_url, follow_redirects=True)
        except ContactExtractionError:
            # httpx missing: the fetch layer will report this properly on the first page.
            return None
        except Exception as exc:  # noqa: BLE001 - unreachable robots.txt means no rules
            logger.debug("Could not fetch %s (%s); treating as allow-all.", robots_url, exc)
            return None

        if response.status_code >= 400:
            return None

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.parse(response.text.splitlines())
        except Exception:  # noqa: BLE001 - a malformed robots.txt is not a prohibition
            logger.debug("robots.txt at %s is malformed; treating as allow-all.", robots_url)
            return None
        return parser


# ===========================================================================================
# The service
# ===========================================================================================

class ContactExtractorService:
    """
    Visits a normalized lead's website and returns the lead enriched with the contact details
    published on it.

    Stateless with respect to any single lead — the lead travels through as an argument — so
    one instance is safe to reuse across concurrent imports. The robots cache and the rate
    limiter *are* shared instance state, on purpose: both exist so concurrent extractions
    cooperate rather than burst against the same host.

    Writes nothing to the database. This class imports no model, no repository and no session,
    and returns new `NormalizedLead` objects for the caller to do with as it wishes.
    """

    def __init__(
        self,
        *,
        timeout: float | None = None,
        user_agent: str | None = None,
        max_subpages: int | None = None,
        concurrency: int | None = None,
        min_request_interval: float | None = None,
        respect_robots: bool | None = None,
        max_page_bytes: int | None = None,
        max_redirects: int | None = None,
        transport: Any = None,
    ) -> None:
        """
        Args:
            timeout: Per-request timeout in seconds.
            user_agent: Identity sent on every request and matched against robots.txt.
            max_subpages: Cap on second-level pages per lead. Depth is fixed at one level and
                is **not** configurable — see the module docstring.
            concurrency: How many leads `extract_many` resolves at once.
            min_request_interval: Politeness gap between requests to the *same host*.
            respect_robots: Left at True in production. Exposed only so a test can exercise
                the extraction path without also stubbing a robots.txt for every fixture.
            max_page_bytes: Cap on a single response body, so one pathological page cannot
                exhaust memory during an import.
            max_redirects: Cap on redirects followed per fetch, so a redirect loop fails fast
                instead of costing unbounded time.
            transport: An `httpx` transport, injected by tests to serve canned pages. None in
                production, where a real client is constructed per request.
        """
        self._timeout = (
            timeout if timeout is not None else settings.CONTACT_EXTRACTION_TIMEOUT_SECONDS
        )
        self._user_agent = (
            user_agent or settings.CONTACT_EXTRACTION_USER_AGENT
        )
        self._max_subpages = max(
            0,
            max_subpages if max_subpages is not None
            else settings.CONTACT_EXTRACTION_MAX_SUBPAGES,
        )
        self._concurrency = max(
            1,
            concurrency if concurrency is not None
            else settings.CONTACT_EXTRACTION_CONCURRENCY,
        )
        self._min_interval = max(
            0.0,
            min_request_interval if min_request_interval is not None
            else settings.CONTACT_EXTRACTION_MIN_REQUEST_INTERVAL_SECONDS,
        )
        self._respect_robots = (
            respect_robots if respect_robots is not None
            else settings.CONTACT_EXTRACTION_RESPECT_ROBOTS
        )
        self._max_page_bytes = (
            max_page_bytes if max_page_bytes is not None
            else settings.CONTACT_EXTRACTION_MAX_PAGE_BYTES
        )
        self._max_redirects = max(
            0,
            max_redirects if max_redirects is not None
            else settings.CONTACT_EXTRACTION_MAX_REDIRECTS,
        )
        self._transport = transport
        self._robots = RobotsCache(self._user_agent, self._timeout, transport)
        self._host_last_request: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_guard = asyncio.Lock()

    # -----------------------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------------------

    async def extract(self, lead: NormalizedLead) -> NormalizedLead:
        """
        Returns `lead` enriched with the contacts published on its website, or `lead`
        unchanged.

        This is the method the brief describes: visit the website, look at header, footer,
        contact page and about page, extract phones/WhatsApp/emails/Instagram/Facebook/
        YouTube, normalize them, and return the enriched lead. It **never raises** — every
        failure path returns the input lead, so an enrichment pass cannot fail an import.
        """
        return (await self.extract_with_outcome(lead)).lead

    async def extract_with_outcome(self, lead: NormalizedLead) -> ExtractionOutcome:
        """
        `extract()` plus the reasoning, for callers that want to log or display what was found
        and why a lead was or was not enriched.

        Separated so the common path stays a clean lead-in/lead-out function while the
        decision remains inspectable — the same split `WebsiteDiscoveryService` makes between
        `discover()` and `discover_with_outcome()`.
        """
        website = normalize_url(lead.website)
        if not website:
            return ExtractionOutcome(
                lead=lead, status="no_website",
                detail="Lead has no website to visit.",
            )

        try:
            home_html, final_url = await self._fetch_page(website)
        except ContactExtractionError as exc:
            # Enrichment is best-effort: an unreachable site leaves the lead exactly as it was.
            # The exception's own `status` classifies it, so robots/invalid-content/transport
            # failures stay distinguishable without matching on message text.
            logger.info("Contact extraction could not fetch %s: %s", website, exc)
            return ExtractionOutcome(
                lead=lead, status=getattr(exc, "status", "fetch_failed"), detail=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - a parser bug must not fail an import
            logger.exception("Contact extraction raised for %s.", website)
            return ExtractionOutcome(
                lead=lead, status="fetch_failed",
                detail=f"Unexpected error fetching {website}: {exc}",
            )

        base_url = final_url or website
        pages_fetched: list[str] = [base_url]
        pages_failed: list[str] = []
        markup_seen: list[str] = [home_html]
        contacts = self._extract_from_html(home_html, base_url)

        # --- Level two. There is exactly one round of these, and what they link to is never
        # visited: that is what bounds this to "one level" structurally rather than by a
        # counter. See the module docstring.
        for link in self._select_subpages(home_html, base_url)[: self._max_subpages]:
            try:
                sub_html, sub_final = await self._fetch_page(link)
            except ContactExtractionError as exc:
                logger.debug("Skipping sub-page %s: %s", link, exc)
                pages_failed.append(link)
                continue
            except Exception:  # noqa: BLE001 - one bad sub-page must not lose the home page
                logger.exception("Sub-page %s raised during contact extraction.", link)
                pages_failed.append(link)
                continue
            pages_fetched.append(sub_final or link)
            markup_seen.append(sub_html)
            contacts = contacts.merged_with(
                self._extract_from_html(sub_html, sub_final or link)
            )

        # The ownership signal is computed from everything we actually read, and reported
        # whether or not contacts were found. It never gates enrichment — see
        # `_score_relevance` on why a low score is advice rather than a verdict.
        score, relevance, signals = self._score_relevance(
            lead, base_url, markup_seen, contacts
        )

        if contacts.is_empty():
            return ExtractionOutcome(
                lead=lead, status="no_contact_found",
                pages_fetched=tuple(pages_fetched), pages_failed=tuple(pages_failed),
                relevance_score=score, relevance_status=relevance,
                relevance_signals=tuple(signals),
                detail=(
                    f"Visited {len(pages_fetched)} page(s) on {base_url}; no contact details "
                    "were published in the markup."
                ),
            )

        enriched, added = self._apply(lead, contacts, pages_fetched)
        # "Partial" means we did find contacts but did not get to read everything we chose to
        # read, so the operator knows the harvest may be incomplete and a retry could add to it.
        status = "partial" if pages_failed else "extracted"
        return ExtractionOutcome(
            lead=enriched, status=status, contacts=contacts,
            pages_fetched=tuple(pages_fetched), pages_failed=tuple(pages_failed),
            fields_added=tuple(added),
            relevance_score=score, relevance_status=relevance,
            relevance_signals=tuple(signals),
            detail=(
                f"Extracted {', '.join(added) if added else 'no new fields'} from "
                f"{len(pages_fetched)} page(s) on {base_url}"
                + (f"; {len(pages_failed)} page(s) failed to load." if pages_failed else ".")
            ),
        )

    async def extract_many(self, leads: Sequence[NormalizedLead]) -> list[NormalizedLead]:
        """
        Runs `extract()` across a batch, preserving input order.

        Bounded-concurrency rather than sequential for the same reason `discover_many` is: a
        hundred sequential site visits inside one import is the difference between a fast run
        and a timeout. The per-host limiter still serialises requests to any single host, so
        raising this fans out across *different* sites, never at one server.
        """
        outcomes = await self.extract_many_with_outcomes(leads)
        return [outcome.lead for outcome in outcomes]

    async def extract_many_with_outcomes(
        self, leads: Sequence[NormalizedLead]
    ) -> list[ExtractionOutcome]:
        """
        `extract_many` plus the per-lead reasoning, preserving input order.

        This is the entry point `LeadDiscoveryService` uses: a batch that enriched nothing is
        a very different problem depending on whether the sites were unreachable, forbidden by
        robots.txt, or simply publish no contact details, and only the outcomes carry that.

        The semaphore lives here, so both batch methods share one concurrency bound.
        """
        semaphore = asyncio.Semaphore(self._concurrency)

        async def resolve(lead: NormalizedLead) -> ExtractionOutcome:
            async with semaphore:
                return await self.extract_with_outcome(lead)

        return list(await asyncio.gather(*(resolve(lead) for lead in leads)))

    def describe(self) -> dict[str, Any]:
        """Reports the service's effective configuration, for a health or debug endpoint."""
        return {
            "user_agent": self._user_agent,
            "timeout_seconds": self._timeout,
            "max_subpages": self._max_subpages,
            "crawl_depth": 1,
            "respect_robots": self._respect_robots,
            "concurrency": self._concurrency,
            "min_request_interval_seconds": self._min_interval,
            "max_page_bytes": self._max_page_bytes,
        }

    # -----------------------------------------------------------------------------------
    # Fetching
    # -----------------------------------------------------------------------------------

    async def _fetch_page(self, url: str) -> tuple[str, str]:
        """
        Fetches one page and returns `(html, final_url)`.

        Raises `ContactExtractionError` (or one of its subclasses, which carry the outcome
        status) for every non-success outcome — robots.txt prohibition, transport fault, HTTP
        error, non-HTML content type, oversized body — so the caller has a single failure
        channel to catch. The final URL is returned separately because a site that redirects
        `http://x.com` to `https://www.x.com/en/` must have its relative links resolved
        against where it actually landed, not against where we asked.

        The body is **streamed** and abandoned the moment it exceeds `max_page_bytes`. Reading
        the whole response and truncating afterwards would mean a site advertising a 2 GB
        "page" had already been pulled into memory before we noticed — the cap has to be
        enforced while the bytes are arriving, not after.
        """
        if self._respect_robots:
            allowed, reason = await self._robots.is_allowed(url)
            if not allowed:
                raise RobotsBlockedError(reason or f"robots.txt disallows {url}.")

        httpx = _import_httpx()
        timeout = httpx.Timeout(self._timeout)
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        await self._throttle(url)
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "headers": headers,
            # Bounded, not unlimited: a redirect loop is otherwise the one failure mode that
            # costs unbounded time rather than returning an error.
            "max_redirects": self._max_redirects,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream(
                    "GET", url, follow_redirects=True
                ) as response:
                    self._check_response_head(url, response)
                    body = await self._read_capped(url, response)
                    final_url = str(getattr(response, "url", "") or url)
        except ContactExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport fault is a fetch failure
            # `TooManyRedirects` lands here alongside timeouts and DNS faults. All three mean
            # "we never got a page", which is exactly what `fetch_failed` reports.
            raise ContactExtractionError(f"Request to {url} failed: {exc}") from exc

        return body, final_url

    def _check_response_head(self, url: str, response: Any) -> None:
        """
        Rejects a response on its status line and headers, before its body is read.

        Doing this against the *head* of a streamed response is the point: a 404, a PDF or a
        declared 500 MB body can all be refused without transferring the payload.
        """
        if response.status_code >= 400:
            raise ContactExtractionError(f"{url} returned HTTP {response.status_code}.")

        content_type = (response.headers.get("content-type") or "").lower()
        if content_type and "html" not in content_type and "xml" not in content_type:
            raise InvalidContentError(
                f"{url} served {content_type!r}, which is not an HTML page."
            )

        # A declared Content-Length lets us refuse an oversized page without reading a byte.
        declared = response.headers.get("content-length")
        if declared:
            try:
                if int(declared) > self._max_page_bytes:
                    raise InvalidContentError(
                        f"{url} declared {declared} bytes, over the "
                        f"{self._max_page_bytes}-byte cap."
                    )
            except ValueError:
                # A malformed Content-Length is not grounds to refuse; the streaming cap below
                # is the real enforcement and does not rely on the header being honest.
                pass

    async def _read_capped(self, url: str, response: Any) -> str:
        """
        Reads a streamed body, stopping hard at `max_page_bytes`.

        A server that lies about (or omits) Content-Length is the normal case, so this is the
        cap that actually holds. We *refuse* an oversized page rather than parsing a truncated
        prefix: half a document yields half-parsed markup, and a phone number sliced across
        the boundary is worse than no phone number.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_page_bytes:
                raise InvalidContentError(
                    f"{url} exceeded the {self._max_page_bytes}-byte response cap."
                )
            chunks.append(chunk)

        raw = b"".join(chunks)
        encoding = getattr(response, "encoding", None) or "utf-8"
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            # An unknown charset label is not a reason to lose the page.
            return raw.decode("utf-8", errors="replace")

    async def _throttle(self, url: str) -> None:
        """
        Spaces requests to the same host by `min_request_interval`.

        Per-host rather than global, because the politeness obligation is owed to each server
        individually: two leads on two unrelated domains have no reason to queue behind each
        other, while five pages on one small studio's site absolutely should.
        """
        if self._min_interval <= 0:
            return
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return

        async with self._host_guard:
            lock = self._host_locks.setdefault(host, asyncio.Lock())

        async with lock:
            loop = asyncio.get_running_loop()
            last = self._host_last_request.get(host)
            if last is not None:
                elapsed = loop.time() - last
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)
            self._host_last_request[host] = loop.time()

    # -----------------------------------------------------------------------------------
    # Link selection — the one-level boundary
    # -----------------------------------------------------------------------------------

    def _select_subpages(self, markup: str, base_url: str) -> list[str]:
        """
        Chooses the contact/about pages worth visiting, **same host only**, best-first.

        This is the method that decides what "one level" contains, and it is deliberately
        restrictive: a link qualifies only if its text or its path says contact/about. A site
        map with two hundred internal links yields at most `max_subpages` fetches, and an
        off-host link never yields any — following those would walk us onto Facebook, a CDN,
        or a client's site, which is the crawl this service must not perform.

        Contact pages are ordered ahead of about pages because they are where a number
        actually lives; an about page is the fallback for sites that fold contact details into
        their story.
        """
        try:
            soup = _make_soup(markup)
        except ContactExtractionError:
            return []
        except Exception:  # noqa: BLE001 - unparseable markup simply yields no sub-pages
            logger.debug("Could not parse %s for sub-page links.", base_url)
            return []

        base_host = (urlparse(base_url).hostname or "").lower().lstrip("www.")
        contact_links: list[str] = []
        about_links: list[str] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue

            absolute = urljoin(base_url, href).split("#")[0].rstrip("/")
            if not absolute or absolute.lower().endswith(_NON_HTML_SUFFIXES):
                continue

            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue

            # Same-host only. This is the hard boundary that keeps one level from becoming a
            # walk across the open web.
            host = (parsed.hostname or "").lower().lstrip("www.")
            if host != base_host:
                continue

            key = absolute.lower()
            if key in seen or key == base_url.lower().rstrip("/"):
                continue

            haystack = f"{parsed.path.lower()} {anchor.get_text(' ', strip=True).lower()}"
            if any(hint in haystack for hint in _CONTACT_HINTS):
                seen.add(key)
                contact_links.append(absolute)
            elif any(hint in haystack for hint in _ABOUT_HINTS):
                seen.add(key)
                about_links.append(absolute)

        return contact_links + about_links

    # -----------------------------------------------------------------------------------
    # Extraction
    # -----------------------------------------------------------------------------------

    def _extract_from_html(self, markup: str, base_url: str) -> ExtractedContacts:
        """
        Harvests every contact detail from one page.

        Header and footer are scanned **first and separately**, then the whole document. That
        ordering is the point: the brief calls out header and footer specifically because that
        is where a business puts the number it wants to be called on, and `NormalizedLead`
        promotes the first phone to the CRM's `phone` column. Scanning the document in source
        order would let a photographer's number buried in a testimonial outrank the studio's
        own switchboard.

        The whole-document pass still runs afterwards so nothing is lost — it simply lands
        behind the header/footer values.
        """
        try:
            soup = _make_soup(markup)
        except ContactExtractionError:
            raise
        except Exception:  # noqa: BLE001 - unparseable markup yields nothing, not a crash
            logger.debug("Could not parse %s for contacts.", base_url)
            return ExtractedContacts()

        # Strip script/style/etc before any text is read, so tracking payloads and CSS cannot
        # contribute phone-shaped or email-shaped noise.
        for tag in soup.find_all(_NOISE_TAGS):
            tag.decompose()

        contacts = ExtractedContacts()
        for region in self._priority_regions(soup):
            contacts = contacts.merged_with(self._scan_node(region, base_url))
        return contacts.merged_with(self._scan_node(soup, base_url))

    @staticmethod
    def _priority_regions(soup: Any) -> list[Any]:
        """
        Returns the header and footer regions of a page, in priority order.

        Matched by tag, by ARIA role and by the class/id conventions sites actually use,
        because a large share of small-business templates render their footer as
        `<div class="site-footer">` rather than `<footer>`. Footer is searched before header:
        contact blocks live in footers far more often than in navigation bars, which usually
        carry only a call-to-action.
        """
        regions: list[Any] = []
        seen: list[Any] = []

        def add(nodes: Iterable[Any]) -> None:
            for node in nodes:
                if node is None or any(node is existing for existing in seen):
                    continue
                seen.append(node)
                regions.append(node)

        add(soup.find_all("footer"))
        add(soup.find_all(attrs={"role": "contentinfo"}))
        add(soup.find_all(
            class_=re.compile(r"(site-)?footer|foot-?(er|bar)", re.IGNORECASE)
        ))
        add(soup.find_all(id=re.compile(r"footer|foot-?bar", re.IGNORECASE)))

        add(soup.find_all("header"))
        add(soup.find_all(attrs={"role": "banner"}))
        add(soup.find_all(
            class_=re.compile(r"(site-)?header|top-?bar|masthead", re.IGNORECASE)
        ))
        add(soup.find_all(id=re.compile(r"header|top-?bar|masthead", re.IGNORECASE)))

        return regions

    def _scan_node(self, node: Any, base_url: str) -> ExtractedContacts:
        """
        Extracts contacts from one soup node: its links first, then its text.

        Links are authoritative and text is inference. A `tel:` href is a number the site
        *declared* to be a phone number; a digit run in a paragraph is a guess that
        `_looks_like_phone` has to defend. Taking links first means the declared values lead
        the ordering, and the CRM's headline phone comes from markup rather than from prose.
        """
        phones: list[str] = []
        whatsapp: list[str] = []
        emails: list[str] = []
        instagram: list[str] = []
        facebook: list[str] = []
        youtube: list[str] = []

        for anchor in node.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            lowered = href.lower()
            if lowered.startswith("tel:"):
                candidate = unquote(href[4:]).strip()
                if _looks_like_phone(candidate):
                    phones.append(_clean_phone_display(candidate))
                continue

            if lowered.startswith("mailto:"):
                # A mailto can carry ?subject=...; the address is everything before it.
                address = unquote(href[7:]).split("?")[0].strip()
                valid = _valid_email(address)
                if valid:
                    emails.append(valid)
                continue

            absolute = urljoin(base_url, href) if not lowered.startswith("http") else href

            number = _whatsapp_number(absolute)
            if number:
                whatsapp.append(number)
                continue

            social = _social_url(absolute, _INSTAGRAM_RE)
            if social:
                instagram.append(social[0])
                continue

            social = _social_url(absolute, _FACEBOOK_RE)
            if social:
                facebook.append(social[0])
                continue

            social = _social_url(absolute, _YOUTUBE_RE)
            if social:
                youtube.append(social[0])
                continue

        # --- Text pass. Everything here is inference and is filtered accordingly.
        text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
        if text:
            for match in _EMAIL_TEXT_RE.finditer(text):
                valid = _valid_email(match.group(0))
                if valid:
                    emails.append(valid)

            for match in _PHONE_TEXT_RE.finditer(text):
                candidate = match.group(0)
                if _looks_like_phone(candidate):
                    phones.append(_clean_phone_display(candidate))

        return ExtractedContacts(
            phones=tuple(phones), whatsapp=tuple(whatsapp), emails=tuple(emails),
            instagram=tuple(instagram), facebook=tuple(facebook), youtube=tuple(youtube),
        )

    # -----------------------------------------------------------------------------------
    # Ownership / relevance
    # -----------------------------------------------------------------------------------

    def _score_relevance(
        self,
        lead: NormalizedLead,
        base_url: str,
        markup: Sequence[str],
        contacts: ExtractedContacts,
    ) -> tuple[float, str, list[str]]:
        """
        Judges how strongly the fetched site looks like it belongs to *this* lead.

        `WebsiteDiscoveryService` validates that a URL is reachable; reachability says nothing
        about ownership. A search backend can hand back a directory listing, a competitor, or
        a parked domain, and all three respond with a healthy 200. Once we have actually read
        the page we can do much better, because the page itself will say who it belongs to.

        Five independent signals, each worth a share of the score:

        * **name** — the lead's distinctive tokens appear in the title/markup, or in the domain
        * **city** — the lead's city appears in the page text
        * **phone** — a number we already had for this lead is published on the site
        * **email domain** — a scraped address is at the site's own domain
        * **domain** — the registrable domain echoes the business name

        The phone match is weighted highest because it is nearly conclusive: a site publishing
        the number we already hold for this business is that business. Name and domain matches
        are strong; city alone is weak, since a city name appears on every studio's site in
        that city.

        **The score never gates anything.** It is returned for `LeadDiscoveryService` to act
        on, exactly as the brief requires — a real studio whose site is an image-only splash
        page with the name in a logo scores near zero, and discarding it would lose a good
        lead. Reporting "we read this site and it does not obviously belong to this business"
        is useful; acting on that guess unilaterally is not.

        Returns:
            `(score in [0,1], band, signals)` where band is `owned` / `uncertain` /
            `unrelated`.
        """
        text = " ".join(markup).lower()
        signals: list[str] = []
        score = 0.0

        site_domain = registrable_domain(urlparse(base_url).hostname) or ""
        domain_stem = site_domain.split(".")[0] if site_domain else ""

        # --- Name. Checked against the page and against the domain separately: a site whose
        # body never spells the name out may still be `sunrisestudio.com`.
        name_tokens = _significant_tokens(lead.business_name)
        if name_tokens:
            in_text = [t for t in name_tokens if t in text]
            if len(in_text) >= max(1, len(name_tokens) // 2):
                score += 0.30
                signals.append(f"business name matched page content ({', '.join(in_text)})")
            elif in_text:
                score += 0.15
                signals.append(f"business name partially matched ({', '.join(in_text)})")

            if domain_stem and any(t in domain_stem for t in name_tokens if len(t) > 2):
                score += 0.20
                signals.append(f"business name echoed in domain '{site_domain}'")

        # --- City. Weak on its own, which is why it is worth least.
        city_tokens = _significant_tokens(lead.city)
        if city_tokens and all(t in text for t in city_tokens):
            score += 0.10
            signals.append(f"city '{lead.city}' appears on the site")

        # --- Phone. The strongest signal available: near-conclusive when it hits.
        known_keys = {k for k in lead.phone_keys if k}
        if known_keys:
            found_keys = {
                k for k in (normalize_phone(p) for p in contacts.phones) if k
            } | {
                k for k in (normalize_phone(p) for p in contacts.whatsapp) if k
            }
            if known_keys & found_keys:
                score += 0.35
                signals.append("a phone number already on the lead is published on the site")

        # --- Email domain. A contact address at the site's own domain is the business's own.
        if site_domain:
            for address in contacts.emails:
                _, _, mail_domain = address.partition("@")
                if registrable_domain(mail_domain) == site_domain:
                    score += 0.15
                    signals.append(f"contact email is at the site's own domain ({site_domain})")
                    break

        score = round(min(1.0, score), 3)
        threshold = settings.CONTACT_EXTRACTION_MIN_RELEVANCE
        if score >= max(threshold, 0.6):
            band = "owned"
        elif score >= threshold:
            band = "uncertain"
        else:
            band = "unrelated"
        if not signals:
            signals.append("no identifying signal found on the page")
        return score, band, signals

    # -----------------------------------------------------------------------------------
    # Merging onto the lead
    # -----------------------------------------------------------------------------------

    def _apply(
        self,
        lead: NormalizedLead,
        contacts: ExtractedContacts,
        pages_fetched: Sequence[str],
    ) -> tuple[NormalizedLead, list[str]]:
        """
        Folds a harvest onto a lead, returning `(enriched_lead, fields_added)`.

        Two rules, both deliberate:

        * **Existing values win.** A provider that read a Google Places record has
          better-attributed data than a regex over HTML, so `instagram`, `facebook` and
          `website` are filled only when empty, mirroring rule 6 of website discovery.
        * **Lists are appended, not replaced.** Scraped numbers and addresses go *after* the
          provider's, deduplicated on the CRM's own comparison keys (`normalize_phone` /
          `normalize_email`) rather than on raw strings, so "+91 98765 43210" and
          "9876543210" do not both survive.

        WhatsApp numbers land in `whatsapp_numbers`, which the DTO now carries as a field of
        its own, *and* are appended to `phone_numbers` when not already there — they are
        genuinely numbers this business publishes, and a lead whose only number came from a
        wa.me link must still satisfy `is_valid()`. Keeping the WhatsApp-specific list
        separate is what lets `secondary_phone` promote a *known* WhatsApp number into the
        CRM's `whatsapp` column instead of guessing at the second phone.
        """
        added: list[str] = []

        # --- Phones: the provider's first, then the numbers the page published, then any
        # WhatsApp number not already among them.
        #
        # Ordering matters: `phone_numbers[0]` becomes the CRM's headline `phone`. A number
        # printed in the header or footer is the one the business leads with, so it outranks a
        # click-to-chat link — putting WhatsApp first would make a chat-only number the
        # business's primary phone whenever the provider supplied none, and `secondary_phone`
        # would then return that same number for the `whatsapp` column.
        phones = list(lead.phone_numbers)
        seen_phone_keys = {k for k in (normalize_phone(p) for p in phones) if k}
        for candidate in (*contacts.phones, *contacts.whatsapp):
            key = normalize_phone(candidate)
            if not key or key in seen_phone_keys:
                continue
            seen_phone_keys.add(key)
            phones.append(candidate)
            if "phone_numbers" not in added:
                added.append("phone_numbers")

        # --- Emails.
        emails = list(lead.emails)
        seen_email_keys = {k for k in (normalize_email(e) for e in emails) if k}
        for candidate in contacts.emails:
            key = normalize_email(candidate)
            if not key or key in seen_email_keys:
                continue
            seen_email_keys.add(key)
            emails.append(candidate)
            if "emails" not in added:
                added.append("emails")

        # --- Single-valued social fields: filled only when empty.
        instagram = lead.instagram
        if not instagram:
            for candidate in contacts.instagram:
                handle = normalize_instagram(candidate)
                if handle:
                    instagram = handle
                    added.append("instagram")
                    break

        facebook = lead.facebook
        if not facebook:
            for candidate in contacts.facebook:
                url = normalize_url(candidate)
                if url:
                    facebook = url
                    added.append("facebook")
                    break

        # --- WhatsApp: a list of its own, appended to and never overwritten.
        whatsapp = list(lead.whatsapp_numbers)
        seen_wa_keys = {k for k in (normalize_phone(w) for w in whatsapp) if k}
        for candidate in contacts.whatsapp:
            key = normalize_phone(candidate)
            if not key or key in seen_wa_keys:
                continue
            seen_wa_keys.add(key)
            whatsapp.append(candidate)
            if "whatsapp_numbers" not in added:
                added.append("whatsapp_numbers")

        # --- YouTube: single-valued, filled only when empty, like the other social fields.
        youtube = lead.youtube
        if not youtube:
            for candidate in contacts.youtube:
                url = normalize_url(candidate)
                if url:
                    youtube = url
                    added.append("youtube")
                    break

        # `raw` keeps the full harvest and the page list regardless of what was merged, so an
        # operator can always see exactly what the site published and which pages it came
        # from — including values that lost to an existing field and are not on the DTO.
        raw = dict(lead.raw)
        raw["contact_extraction"] = {
            "pages_fetched": list(pages_fetched),
            "extracted": contacts.to_dict(),
        }

        enriched = replace(
            lead,
            phone_numbers=phones,
            whatsapp_numbers=whatsapp,
            emails=emails,
            instagram=instagram,
            facebook=facebook,
            youtube=youtube,
            raw=raw,
        )
        return enriched, added
