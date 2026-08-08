"""
app/services/contact_normalization.py

This file implements `ContactNormalizationService` — the canonical-form layer for the
contact details a lead carries: phone numbers, email addresses, Instagram URLs, Facebook
URLs and websites.

Where it sits
-------------
It is an Application-layer *service* in the same mould as `ContactExtractorService` and
`WebsiteDiscoveryService`: pure, synchronous, and **read-only with respect to the
database**. It imports no model, no repository and no session. Callers hand it strings (or
a `NormalizedLead`) and get canonicalised strings back; persistence stays exactly where it
already is, in `LeadImportService`.

Why this is not an extension of `lead_providers/normalized.py`
--------------------------------------------------------------
That module already has `normalize_phone`, `normalize_email`, `normalize_instagram` and
`normalize_url` — but they compute **comparison keys**, which is a different job with a
conflicting definition of "correct":

    normalize_phone("+91 98765 43210")  ->  "9876543210"      (match key: last 10 digits)
    canonical_phone("+91 98765 43210")  ->  "+919876543210"   (E.164: dialable)

The match key deliberately *discards* the country code so that a business first captured as
"9876543210" and later re-scraped as "+919876543210" collapses onto one lead. That
behaviour is load-bearing and is mirrored in SQL in `LeadRepository.find_duplicates`
(`right(regexp_replace(phone,'\\D','','g'), 10)`), which compares against numbers **already
stored** in the `leads` table. Redefining `normalize_phone` to return E.164 would make every
new key fail to match every stored row — a silent, total loss of phone deduplication.

So the two layers coexist and answer different questions:

    canonical form   (this module)      "what should we store / display / dial?"
    comparison key   (normalized.py)    "is this the same business we already have?"

This module *delegates* to the comparison-key functions where the two agree — canonical
email and the match key are both "trimmed and lowercased", so `canonical_email` is defined
in terms of `normalize_email` rather than re-implementing the validation. That keeps a
single source of truth for the email shape.

Phone canonicalisation and the default region
---------------------------------------------
E.164 requires a country code, and a bare "9876543210" does not carry one. The service takes
a `default_country_code` (defaulting to India's `91`, this CRM's market) and applies it only
to numbers that plainly lack one. The rules, in order:

    +91 9876543210   ->  already E.164, normalised            ->  +919876543210
    00919876543210   ->  "00" is the international prefix      ->  +919876543210
    919876543210     ->  12 digits, leads with the country code->  +919876543210
    09876543210      ->  national trunk "0" stripped           ->  +919876543210
    9876543210       ->  10 national digits, code applied      ->  +919876543210

A number that cannot be resolved to a plausible E.164 form returns None rather than a
guess. A wrong phone number is worse than a missing one here: it is the field the CRM
deduplicates on, so a bogus value can collapse two unrelated businesses onto one lead.

No `phonenumbers` dependency
----------------------------
Full libphonenumber-grade parsing would need the `phonenumbers` package, which is not in
`requirements.txt`. The rules above cover the formats this CRM's sources actually produce
(Indian directories, scraped studio sites, operator spreadsheets) without adding a
dependency. `_MIN_SUBSCRIBER_DIGITS`/`_MAX_E164_DIGITS` keep the output inside the E.164
length limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Iterable
from urllib.parse import unquote, urlparse, urlunparse

from app.services.lead_providers.normalized import (
    NormalizedLead,
    normalize_email,
)


# ===========================================================================================
# Phone constants
# ===========================================================================================
#: The default country calling code applied to numbers that carry none. India, this CRM's
#: market. Overridable per-service so the module is not silently India-only.
_DEFAULT_COUNTRY_CODE = "91"

#: E.164 permits at most 15 digits including the country code.
_MAX_E164_DIGITS = 15

#: Below this many digits after the country code we are looking at an extension or a
#: fragment, not a subscriber number.
_MIN_SUBSCRIBER_DIGITS = 6

#: Total digit floor for a bare, code-less number before we are willing to prepend a country
#: code. Guards against turning a 4-digit year into a phone number.
_MIN_NATIONAL_DIGITS = 8

#: Country codes we can recognise at the head of a code-carrying number. Kept to the codes
#: this CRM's sources actually produce; the list only matters for disambiguating a bare
#: "919876543210"-style string, and an unknown code still works when written "+<code>...".
_KNOWN_COUNTRY_CODES: tuple[str, ...] = ("91", "1", "44", "61", "65", "971", "966", "60")

#: Digit-shaped strings that are never phone numbers.
_PHONE_REJECT_EXACT: frozenset[str] = frozenset({
    "1234567890", "0000000000", "1111111111", "9999999999", "1234567891",
    "0123456789", "12345678901",
})


# ===========================================================================================
# URL / social constants
# ===========================================================================================
#: Tracking and session parameters that identify the *visit*, not the *page*. Dropped so two
#: links to one profile canonicalise to one value.
_TRACKING_PARAMS: frozenset[str] = frozenset({
    "igshid", "igsh", "fbclid", "gclid", "mibextid", "utm_source", "utm_medium",
    "utm_campaign", "utm_term", "utm_content", "ref", "ref_src", "ref_url", "_ga",
    "mc_cid", "mc_eid", "hl", "locale", "rdid", "share_url",
})

#: Instagram path segments that are the platform's own furniture, never a profile.
_INSTAGRAM_NOISE: frozenset[str] = frozenset({
    "p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv",
    "about", "developer", "legal", "privacy", "terms", "help", "web",
})

#: Facebook path segments that are the platform's own furniture, never a page.
_FACEBOOK_NOISE: frozenset[str] = frozenset({
    "sharer", "sharer.php", "share", "share.php", "dialog", "plugins", "tr", "login",
    "login.php", "signup", "home.php", "watch", "groups", "events", "marketplace",
    "privacy", "policies", "terms", "help", "hashtag", "search", "photo.php", "story.php",
})

#: A legal Instagram username: letters, digits, underscore and dot, up to 30 characters.
#: Mirrors `LeadBase.validate_instagram_handle`, which the stored value must satisfy.
_INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]{1,30}$")

#: A legal Facebook page slug, or the numeric-id form used by `profile.php?id=`.
_FACEBOOK_SLUG_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")

_INSTAGRAM_HOST_RE = re.compile(r"^(?:[a-z0-9-]+\.)?instagram\.com$", re.IGNORECASE)
_FACEBOOK_HOST_RE = re.compile(
    r"^(?:[a-z0-9-]+\.)?(?:facebook\.com|fb\.com|fb\.me)$", re.IGNORECASE
)

#: Hosts that are a social profile, not a website. A studio that lists its Facebook page as
#: its "website" should not have that stored in the website column.
_NON_WEBSITE_HOSTS_RE = re.compile(
    r"^(?:[a-z0-9-]+\.)?(?:instagram\.com|facebook\.com|fb\.com|fb\.me|wa\.me|"
    r"whatsapp\.com|youtube\.com|youtu\.be|twitter\.com|x\.com|linkedin\.com|"
    r"t\.me|linktr\.ee|pinterest\.com)$",
    re.IGNORECASE,
)

#: A host must have a dot and a plausible TLD to be a website.
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9\-._]*[a-z0-9])?\.[a-z]{2,}$", re.IGNORECASE)


class ContactNormalizationError(ValueError):
    """
    Raised only by the strict `require_*` helpers. The ordinary `canonical_*` functions are
    total and return None on bad input, because normalising a batch of scraped records must
    not abort the batch over one malformed value.
    """


# ===========================================================================================
# Phone numbers
# ===========================================================================================

def _strip_extension(value: str) -> str:
    """
    Removes a trailing extension ("...ext 12", "x401") so it is not absorbed into the
    subscriber digits, which would push a valid number over the E.164 length limit.
    """
    return re.sub(
        r"(?:[,;]|\b(?:ext|extn|x)\b\.?)\s*\d{1,6}\s*$", "", value, flags=re.IGNORECASE
    )


def canonical_phone(
    value: str | None,
    default_country_code: str = _DEFAULT_COUNTRY_CODE,
) -> str | None:
    """
    Renders a phone number in E.164: a leading `+`, then country code and subscriber digits
    with no spaces or punctuation.

        "9876543210"      -> "+919876543210"
        "+91 9876543210"  -> "+919876543210"
        "00919876543210"  -> "+919876543210"

    Returns None when the value cannot be resolved to a plausible number, so callers can
    skip falsy results rather than guard against a fabricated one.

    This is the *canonical storage/display* form. It is NOT the deduplication key — use
    `app.services.lead_providers.normalize_phone` for that, and see this module's docstring
    for why the two must stay different.
    """
    if not value:
        return None

    text = _strip_extension(str(value).strip())
    if not text:
        return None

    # A `+` is only meaningful at the very front. Remember whether the caller supplied one
    # before discarding punctuation, because it proves a country code is already present.
    had_plus = text.lstrip().startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None

    code = re.sub(r"\D", "", default_country_code or "") or _DEFAULT_COUNTRY_CODE

    if had_plus:
        # Already international: trust the caller's country code, whatever it is.
        national = _after_country_code(digits)
        if national is None:
            return None
        return _assemble(digits)

    if digits.startswith("00"):
        # "00" is the ITU international access prefix — the rest is already E.164 digits.
        rest = digits[2:]
        if not rest:
            return None
        return _assemble(rest)

    if digits.startswith("0"):
        # National trunk prefix. Strip it and treat the rest as a national number.
        rest = digits.lstrip("0")
        if len(rest) < _MIN_NATIONAL_DIGITS:
            return None
        return _assemble(code + rest)

    # No prefix of any kind. Either the number already leads with its country code
    # ("919876543210") or it is purely national ("9876543210").
    if digits.startswith(code) and len(digits) > len(code) + _MIN_NATIONAL_DIGITS - 1:
        return _assemble(digits)

    for known in _KNOWN_COUNTRY_CODES:
        if known == code:
            continue
        if digits.startswith(known) and len(digits) - len(known) >= 10:
            return _assemble(digits)

    if len(digits) < _MIN_NATIONAL_DIGITS:
        return None
    return _assemble(code + digits)


def _after_country_code(digits: str) -> str | None:
    """
    Returns the subscriber portion of an international number, or None if no recognised
    country code leads it. Used to sanity-check a `+`-prefixed value.
    """
    for known in sorted(_KNOWN_COUNTRY_CODES, key=len, reverse=True):
        if digits.startswith(known):
            return digits[len(known):]
    # An unrecognised country code is not necessarily wrong — the world has ~200 of them and
    # `_KNOWN_COUNTRY_CODES` lists eight. Fall back to the length check in `_assemble`.
    return digits


def _assemble(digits: str) -> str | None:
    """
    Applies the final E.164 validity gates and renders `+<digits>`. Centralised so every
    branch of `canonical_phone` is held to the same standard.
    """
    digits = digits.lstrip("0")
    if not digits:
        return None
    if len(digits) > _MAX_E164_DIGITS:
        return None
    subscriber = _after_country_code(digits) or ""
    if len(subscriber) < _MIN_SUBSCRIBER_DIGITS:
        return None
    # Placeholders are checked against BOTH the full E.164 digits and the subscriber
    # portion. Checking only the former would miss every placeholder that reached us bare:
    # "1234567890" becomes "911234567890" once the country code is applied, which is not in
    # the blacklist even though the number plainly is.
    if digits in _PHONE_REJECT_EXACT or subscriber in _PHONE_REJECT_EXACT:
        return None
    # A single repeated digit is placeholder markup, never a real number.
    if len(set(subscriber)) <= 1:
        return None
    return f"+{digits}"


# ===========================================================================================
# Email addresses
# ===========================================================================================

def canonical_email(value: str | None) -> str | None:
    """
    Renders an email address in canonical form: trimmed and lowercased, with a `mailto:`
    scheme and any subject/query parameters stripped.

        "Info@ABC.com"                  -> "info@abc.com"
        "mailto:Info@ABC.com?subject=Hi"-> "info@abc.com"

    Delegates the shape validation to `normalize_email`, so the canonical form and the
    comparison key can never disagree about what counts as a valid address.

    Note that the local part is lowercased too. RFC 5321 makes it case-*sensitive*, but no
    mail provider this CRM's leads use treats it that way, and operators type "Info@" and
    "info@" for one inbox. Preserving the case would defeat the deduplication this exists
    to serve.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith("mailto:"):
        text = text[len("mailto:"):]
    # Drop `?subject=...&body=...` and any fragment.
    text = text.split("?")[0].split("#")[0]
    text = unquote(text).strip().strip("<>").strip()
    return normalize_email(text)


# ===========================================================================================
# URL helpers
# ===========================================================================================

def _split_url(value: str) -> tuple[str, str, str, str] | None:
    """
    Parses a possibly scheme-less URL into `(scheme, host, path, query)` with the host
    lowercased and a leading `www.` removed. Returns None if it is not URL-shaped.
    """
    text = str(value or "").strip()
    if not text:
        return None
    text = text.strip("<>").strip()
    # Scraped values are frequently written bare ("studio.example.com").
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", text, re.IGNORECASE):
        # A scheme-less value carrying a non-hierarchical scheme ("mailto:x@y.in",
        # "tel:+9198...") is not a bare host and must not be given one. Left unguarded,
        # `urlparse` reads the mailto local part as userinfo and yields the domain alone,
        # turning an email address into a plausible-but-wrong website.
        if re.match(r"^[a-z][a-z0-9+.\-]*:", text, re.IGNORECASE):
            return None
        if text.startswith("//"):
            text = f"https:{text}"
        else:
            text = f"https://{text}"

    try:
        parsed = urlparse(text)
    except ValueError:
        return None

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None

    # Credentials in the authority ("user@host") are not part of a site's identity and are
    # a strong signal the value is an email address, not a URL.
    if "@" in (parsed.netloc or ""):
        return None

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    if not _HOST_RE.match(host):
        return None

    return scheme, host, parsed.path or "", parsed.query or ""


def _strip_tracking(query: str) -> str:
    """
    Removes tracking parameters while preserving meaningful ones (`profile.php?id=123` must
    survive), and sorts what remains so parameter order cannot produce two spellings of one
    URL.
    """
    if not query:
        return ""
    kept: list[str] = []
    for part in query.split("&"):
        if not part:
            continue
        name = part.split("=", 1)[0].strip().lower()
        if name in _TRACKING_PARAMS or not name:
            continue
        kept.append(part)
    return "&".join(sorted(kept))


# ===========================================================================================
# Instagram
# ===========================================================================================

def canonical_instagram(value: str | None) -> str | None:
    """
    Renders an Instagram reference as a canonical profile URL.

        "@studio_x"                                  -> "https://instagram.com/studio_x"
        "instagram.com/studio_x/"                    -> "https://instagram.com/studio_x"
        "https://www.instagram.com/studio_x/?igshid=1" -> "https://instagram.com/studio_x"

    Accepts a full URL, an @-handle or a bare handle, because all three appear in scraped
    data and operator spreadsheets. Returns None for a post, reel, story or any other piece
    of platform furniture — attaching `instagram.com/p/Cxyz` as a studio's profile would be
    wrong in a way that looks right.
    """
    handle = canonical_instagram_handle(value)
    if not handle:
        return None
    return f"https://instagram.com/{handle}"


def canonical_instagram_handle(value: str | None) -> str | None:
    """
    Reduces an Instagram reference to its bare handle, lowercased.

    Separated from `canonical_instagram` because the CRM's `instagram` column stores the
    handle, while link-out UI wants the URL; both must derive from one parse so they can
    never disagree.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    if "instagram.com" in text.lower():
        parts = _split_url(text)
        if not parts:
            return None
        _, host, path, _ = parts
        if not _INSTAGRAM_HOST_RE.match(host):
            return None
        segments = [s for s in unquote(path).split("/") if s]
        if not segments:
            return None
        handle = segments[0]
        if handle.lower() in _INSTAGRAM_NOISE:
            return None
        # A profile URL has exactly one path segment; deeper is a post or a tagged view.
        if len(segments) > 1 and segments[1].lower() not in ("", "reels", "tagged"):
            return None
    else:
        handle = text.lstrip("@").rstrip("/").strip()

    handle = handle.split("?")[0].split("#")[0].strip()
    if not handle or not _INSTAGRAM_HANDLE_RE.match(handle):
        return None
    if handle.lower() in _INSTAGRAM_NOISE:
        return None
    return handle.lower()


# ===========================================================================================
# Facebook
# ===========================================================================================

def canonical_facebook(value: str | None) -> str | None:
    """
    Renders a Facebook reference as a canonical page URL.

        "facebook.com/StudioX/"                    -> "https://facebook.com/StudioX"
        "https://m.facebook.com/StudioX?ref=page"  -> "https://facebook.com/StudioX"
        "fb.me/StudioX"                            -> "https://facebook.com/StudioX"
        "facebook.com/profile.php?id=100091"       -> "https://facebook.com/profile.php?id=100091"

    Mobile (`m.`), regional (`en-gb.`) and short (`fb.me`) hosts all collapse to
    `facebook.com` so one page yields one value. Share buttons, dialogs and other platform
    furniture return None.

    Unlike Instagram, case is **preserved** in the slug: Facebook vanity URLs are displayed
    with their author's capitalisation and the platform treats them case-insensitively, so
    lowercasing would degrade the value shown to an operator for no dedup benefit.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    if not re.search(r"(?:facebook\.com|fb\.com|fb\.me)", text, re.IGNORECASE):
        # A bare slug with no host is ambiguous — it could be anything. Decline rather than
        # invent a page that may not exist.
        return None

    parts = _split_url(text)
    if not parts:
        return None
    _, host, path, query = parts
    if not _FACEBOOK_HOST_RE.match(host):
        return None

    segments = [s for s in unquote(path).split("/") if s]
    if not segments:
        return None

    first = segments[0]
    lowered = first.lower()

    # `profile.php?id=<numeric>` is a real profile whose identity lives in the query string.
    if lowered in ("profile.php", "people"):
        kept = _strip_tracking(query)
        match = re.search(r"(?:^|&)id=(\d{5,})", kept)
        if lowered == "profile.php" and match:
            return f"https://facebook.com/profile.php?id={match.group(1)}"
        if lowered == "people" and len(segments) >= 3 and segments[2].isdigit():
            return f"https://facebook.com/profile.php?id={segments[2]}"
        return None

    if lowered in _FACEBOOK_NOISE:
        return None

    # `facebook.com/pages/Studio-X/12345` is the legacy page form; the id is the identity.
    if lowered == "pages" and len(segments) >= 3 and segments[-1].isdigit():
        return f"https://facebook.com/profile.php?id={segments[-1]}"

    if not _FACEBOOK_SLUG_RE.match(first):
        return None

    return f"https://facebook.com/{first}"


# ===========================================================================================
# Websites
# ===========================================================================================

def canonical_website(value: str | None) -> str | None:
    """
    Renders a website URL in canonical form: `https` scheme, lowercased host with `www.`
    removed, no trailing slash, no tracking parameters, no fragment.

        "sunrisestudio.in"                     -> "https://sunrisestudio.in"
        "http://WWW.SunriseStudio.in/"         -> "https://sunrisestudio.in"
        "https://sunrisestudio.in/home?utm_source=x#top" -> "https://sunrisestudio.in/home"

    `http` is upgraded to `https` deliberately: the two are the same site for identity
    purposes, and storing both spellings would create two records of one business. The path
    is preserved (a studio's site may legitimately live at `/photography`), but a bare `/`
    is dropped so `example.com` and `example.com/` are one value.

    Returns None for a social profile URL — a Facebook page is not a website, and storing it
    in the website column would send `ContactExtractorService` off to crawl facebook.com.
    """
    parts = _split_url(value or "")
    if not parts:
        return None
    _, host, path, query = parts

    if _NON_WEBSITE_HOSTS_RE.match(host):
        return None

    path = re.sub(r"/{2,}", "/", path).rstrip("/")
    # A directory-index filename adds nothing to the identity of a home page.
    path = re.sub(r"/(?:index|home)\.(?:html?|php|aspx?)$", "", path, flags=re.IGNORECASE)

    kept = _strip_tracking(query)
    return urlunparse(("https", host, path, "", kept, ""))


# ===========================================================================================
# Result type
# ===========================================================================================

@dataclass(frozen=True)
class NormalizedContacts:
    """
    The canonical contact set for one lead: every value in canonical form, deduplicated,
    with the caller's ordering preserved.

    Ordering matters and is preserved deliberately. Providers list the primary contact
    number first, and `LeadImportService` promotes `phones[0]` to the CRM's single `phone`
    column; sorting or setifying here would silently make an arbitrary landline the
    business's headline number.

    `dropped` records every input that could not be canonicalised, so an import run can
    report *why* a number vanished instead of leaving an operator to wonder.
    """

    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    instagram_urls: list[str] = field(default_factory=list)
    facebook_urls: list[str] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when no usable contact detail survived normalisation."""
        return not (
            self.phones
            or self.emails
            or self.instagram_urls
            or self.facebook_urls
            or self.websites
        )

    def to_dict(self) -> dict[str, list[str]]:
        """Renders the set as a plain dict, for logging and API responses."""
        return {
            "phones": list(self.phones),
            "emails": list(self.emails),
            "instagram_urls": list(self.instagram_urls),
            "facebook_urls": list(self.facebook_urls),
            "websites": list(self.websites),
            "dropped": list(self.dropped),
        }


# ===========================================================================================
# The service
# ===========================================================================================

class ContactNormalizationService:
    """
    Canonicalises and deduplicates the contact details on a lead.

    Stateless and side-effect free: no session, no network, no I/O. It can be constructed
    anywhere and unit-tested with no `.env` and no Postgres.

    Typical use, at the seam between a provider and persistence::

        service = ContactNormalizationService()
        contacts = service.normalize_contacts(
            phones=["9876543210", "+91 9876543210", "00919876543210"],
            emails=["Info@ABC.com", "info@abc.com"],
        )
        contacts.phones   # ["+919876543210"]
        contacts.emails   # ["info@abc.com"]

    or over a whole provider record::

        lead = service.normalize_lead(lead)
    """

    def __init__(self, default_country_code: str = _DEFAULT_COUNTRY_CODE) -> None:
        """
        Args:
            default_country_code: Country calling code applied to numbers that carry none,
                with or without a leading `+`. Defaults to India (`91`).
        """
        cleaned = re.sub(r"\D", "", str(default_country_code or ""))
        self.default_country_code = cleaned or _DEFAULT_COUNTRY_CODE

    # -- single values ---------------------------------------------------------------------

    def phone(self, value: str | None) -> str | None:
        """Canonical E.164 phone, or None. See `canonical_phone`."""
        return canonical_phone(value, self.default_country_code)

    def email(self, value: str | None) -> str | None:
        """Canonical lowercased email, or None. See `canonical_email`."""
        return canonical_email(value)

    def instagram(self, value: str | None) -> str | None:
        """Canonical Instagram profile URL, or None. See `canonical_instagram`."""
        return canonical_instagram(value)

    def instagram_handle(self, value: str | None) -> str | None:
        """Canonical Instagram handle, or None. See `canonical_instagram_handle`."""
        return canonical_instagram_handle(value)

    def facebook(self, value: str | None) -> str | None:
        """Canonical Facebook page URL, or None. See `canonical_facebook`."""
        return canonical_facebook(value)

    def website(self, value: str | None) -> str | None:
        """Canonical website URL, or None. See `canonical_website`."""
        return canonical_website(value)

    # -- collections -----------------------------------------------------------------------

    def _dedupe(
        self,
        values: Iterable[str | None] | None,
        canonicaliser,
        dropped: list[str],
    ) -> list[str]:
        """
        Canonicalises every value, drops what cannot be canonicalised, and removes
        duplicates while preserving first-seen order.

        Deduplication is on the **canonical form**, which is the whole point: it is what
        makes "9876543210", "+91 9876543210" and "00919876543210" one number rather than
        three. Case-insensitive on the key so two spellings of one Facebook slug collapse,
        while the first-seen spelling is what survives.
        """
        seen: set[str] = set()
        out: list[str] = []
        for raw in values or []:
            if raw is None:
                continue
            canonical = canonicaliser(raw)
            if not canonical:
                text = str(raw).strip()
                if text:
                    dropped.append(text)
                continue
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(canonical)
        return out

    def phones(self, values: Iterable[str | None] | None) -> list[str]:
        """Canonical, deduplicated phone numbers in first-seen order."""
        return self._dedupe(values, self.phone, [])

    def emails(self, values: Iterable[str | None] | None) -> list[str]:
        """Canonical, deduplicated email addresses in first-seen order."""
        return self._dedupe(values, self.email, [])

    def normalize_contacts(
        self,
        phones: Iterable[str | None] | None = None,
        emails: Iterable[str | None] | None = None,
        instagram_urls: Iterable[str | None] | None = None,
        facebook_urls: Iterable[str | None] | None = None,
        websites: Iterable[str | None] | None = None,
    ) -> NormalizedContacts:
        """
        Canonicalises and deduplicates a full contact set in one call.

        Every argument is optional and may contain None entries, because callers assemble
        these lists from scraped fields that are frequently absent. The method is total: it
        never raises, and anything unusable lands in `NormalizedContacts.dropped` rather
        than aborting the record.
        """
        dropped: list[str] = []
        return NormalizedContacts(
            phones=self._dedupe(phones, self.phone, dropped),
            emails=self._dedupe(emails, self.email, dropped),
            instagram_urls=self._dedupe(instagram_urls, self.instagram, dropped),
            facebook_urls=self._dedupe(facebook_urls, self.facebook, dropped),
            websites=self._dedupe(websites, self.website, dropped),
            dropped=dropped,
        )

    # -- provider records ------------------------------------------------------------------

    def normalize_lead(self, lead: NormalizedLead) -> NormalizedLead:
        """
        Returns a copy of `lead` with its contact fields in canonical form and deduplicated.

        The input is **never mutated** — providers hand out records they may still hold a
        reference to, and the enrichment services in this package all follow the same
        copy-on-write contract.

        A field whose value cannot be canonicalised is left **as the provider supplied it**
        rather than blanked. This service's job is to canonicalise what it recognises, not
        to delete a studio's contact detail because it is written in a form these rules do
        not cover; `NormalizedLead.is_valid()` remains the arbiter of usability.
        """
        contacts = self.normalize_contacts(
            phones=lead.phone_numbers,
            emails=lead.emails,
            instagram_urls=[lead.instagram] if lead.instagram else [],
            facebook_urls=[lead.facebook] if lead.facebook else [],
            websites=[lead.website] if lead.website else [],
        )

        # WhatsApp numbers are canonicalised by the same rules as ordinary phones — they are
        # phone numbers, and `LeadImportService` promotes one of them into the CRM's
        # `whatsapp` column, so leaving them in a provider's raw spelling would put an
        # uncanonicalised value in a column the canonical ones are compared against.
        whatsapp = list(lead.whatsapp_numbers)
        if whatsapp:
            canonical_whatsapp = self.normalize_contacts(phones=whatsapp).phones
            whatsapp = canonical_whatsapp or whatsapp

        return replace(
            lead,
            phone_numbers=contacts.phones or list(lead.phone_numbers),
            whatsapp_numbers=whatsapp,
            emails=contacts.emails or list(lead.emails),
            instagram=(contacts.instagram_urls[0] if contacts.instagram_urls
                       else lead.instagram),
            facebook=(contacts.facebook_urls[0] if contacts.facebook_urls
                      else lead.facebook),
            website=contacts.websites[0] if contacts.websites else lead.website,
        )

    def describe(self) -> dict[str, object]:
        """Reports the service's configuration, for logging and diagnostics endpoints."""
        return {
            "service": "ContactNormalizationService",
            "default_country_code": f"+{self.default_country_code}",
            "phone_format": "E.164",
            "email_case": "lowercased",
            "url_scheme": "https",
            "writes_to_database": False,
        }


__all__ = [
    "ContactNormalizationError",
    "ContactNormalizationService",
    "NormalizedContacts",
    "canonical_email",
    "canonical_facebook",
    "canonical_instagram",
    "canonical_instagram_handle",
    "canonical_phone",
    "canonical_website",
]
