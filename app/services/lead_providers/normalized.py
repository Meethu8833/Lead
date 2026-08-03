"""
app/services/lead_providers/normalized.py

This file defines `NormalizedLead` — the single data shape every lead provider must
produce, regardless of where its records came from.

Under Clean Architecture this is a domain-facing DTO in the Application layer. It sits
between the providers (adapters onto Google Maps, Justdial, a CSV file, …) and the
`LeadImportService` (the use case that deduplicates and persists). Its whole purpose is to
be the *only* thing the import service knows about, so that the service never grows a
branch per provider.

Why this is not the Lead model and not a Pydantic schema
--------------------------------------------------------
It is not `app.models.lead.Lead` because a provider must be usable — and unit-testable —
without a database session, and because a raw scraped record legitimately carries things
the CRM row does not: several phone numbers, several emails, a star rating, a set of
category tags.

It is not a Pydantic request schema because these objects are not built from client JSON;
they are built by our own adapter code. A frozen dataclass gives us cheap construction, and
normalisation that is explicit and inspectable in `normalize()` rather than scattered across
validators.

Why phones and emails are lists
-------------------------------
This is the one place the collection domain genuinely disagrees with the CRM domain. A
Google Maps or Justdial listing routinely exposes a landline *and* a mobile *and* a
WhatsApp number. The `leads` table stores a single unique `phone` (plus one `whatsapp`), so
the extra numbers would be silently discarded if the DTO flattened early. Keeping them as
lists lets deduplication check *every* number against the CRM — which is what actually
prevents a duplicate lead when a business was first captured under its landline and later
re-scraped under its mobile. The flattening to the CRM's shape happens once, at the
persistence boundary, in `LeadImportService`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


#: Characters that are legitimately part of a human-entered phone number but carry no
#: information for comparison purposes.
_PHONE_NOISE = re.compile(r"[\s\-\(\)\.]")

#: A comparison key must retain at least this many digits to be worth matching on. Below
#: this, we are looking at an extension or a fragment, and matching on it would collapse
#: unrelated businesses onto one lead.
_MIN_PHONE_DIGITS = 7

#: The number of trailing digits used as a phone's identity. Indian mobile numbers are ten
#: digits and appear in the wild as "9876543210", "09876543210", "+91 98765 43210" and
#: "919876543210"; comparing the last ten digits treats all four as the same number without
#: needing a country-code parser. Numbers shorter than ten digits are compared whole.
_PHONE_KEY_DIGITS = 10

_EMAIL_RE = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")


def normalize_phone(value: str | None) -> str | None:
    """
    Renders a phone number into its comparison key: digits only, reduced to the last
    `_PHONE_KEY_DIGITS`.

    This key is for *matching*, not for display or dialling — the original string is what
    gets stored on the Lead. Returns None when the input has too few digits to identify
    anyone (see `_MIN_PHONE_DIGITS`), so callers can simply skip falsy keys rather than
    guarding against garbage matches.
    """
    if not value:
        return None
    digits = re.sub(r"\D", "", _PHONE_NOISE.sub("", value))
    if len(digits) < _MIN_PHONE_DIGITS:
        return None
    return digits[-_PHONE_KEY_DIGITS:] if len(digits) > _PHONE_KEY_DIGITS else digits


def normalize_email(value: str | None) -> str | None:
    """
    Renders an email address into its comparison key: trimmed and lowercased.
    Returns None if the value is empty or not shaped like an address, so that malformed
    scrape output never becomes a match key.
    """
    if not value:
        return None
    cleaned = value.strip().lower()
    if not cleaned or not _EMAIL_RE.match(cleaned):
        return None
    return cleaned


def normalize_business_key(business_name: str | None, city: str | None) -> str | None:
    """
    Renders a (business name, city) pair into its comparison key.

    Case, punctuation and internal whitespace are discarded because the same studio is
    written "Sunrise Photography", "Sunrise Photography." and "SUNRISE  PHOTOGRAPHY"
    across three different sources. City is included because two unrelated studios sharing
    a common name in different cities are genuinely two leads.

    Returns None unless BOTH parts are present: matching on a bare business name with no
    city is exactly the case that produces false merges, so we decline to produce a key at
    all rather than let the caller match on half of one.
    """
    if not business_name or not city:
        return None
    name_key = re.sub(r"[^a-z0-9]+", "", business_name.strip().lower())
    city_key = re.sub(r"[^a-z0-9]+", "", city.strip().lower())
    if not name_key or not city_key:
        return None
    return f"{name_key}|{city_key}"


def normalize_instagram(value: str | None) -> str | None:
    """
    Reduces an Instagram reference to a bare handle.

    Accepts a full profile URL, an @-prefixed handle, or a bare handle, because all three
    turn up in scraped data and in operator-maintained spreadsheets. Returns None if what
    remains is not a legal Instagram username, so that the value we hand to the CRM always
    satisfies `LeadBase.validate_instagram_handle`.
    """
    if not value:
        return None
    handle = value.strip()
    if not handle:
        return None
    # Strip a profile URL down to its first path segment.
    match = re.match(r"^https?://(?:www\.)?instagram\.com/([^/?#]+)", handle, re.IGNORECASE)
    if match:
        handle = match.group(1)
    handle = handle.lstrip("@").rstrip("/")
    if not re.match(r"^[a-zA-Z0-9_\.]{1,30}$", handle):
        return None
    return handle


def normalize_url(value: str | None) -> str | None:
    """
    Ensures a URL carries a scheme, since scraped sites are frequently written bare
    ("studio.example.com"). Returns None for empty input. A value that is already absolute
    is returned trimmed but otherwise untouched — we do not attempt to canonicalise hosts
    or strip tracking parameters, because a provider's `source_url` must remain the exact
    link an operator can click to verify the record.
    """
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
        cleaned = f"https://{cleaned}"
    # Reject anything that still cannot pass the CRM's URL validator rather than storing a
    # value the Lead schema would refuse.
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", cleaned, re.IGNORECASE):
        return None
    return cleaned


def _clean_text(value: Any, limit: int | None = None) -> str | None:
    """
    Collapses any scalar into a trimmed string, or None when it carries no content.
    Optionally truncates to `limit` so a provider cannot hand us a value that will be
    rejected by the corresponding column's length constraint.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    if limit is not None and len(text) > limit:
        text = text[:limit]
    return text


def _clean_float(value: Any, low: float, high: float) -> float | None:
    """
    Coerces a scalar to a float inside [low, high], or None. Out-of-range and unparseable
    values become None rather than raising, because one nonsensical latitude in a scrape of
    two hundred records should cost us that one coordinate, not the whole record.
    """
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < low or number > high:
        return None
    return number


def _clean_int(value: Any) -> int | None:
    """
    Coerces a scalar to a non-negative integer, or None. Accepts the "1,234" and "1234
    reviews" forms that appear in scraped review counts.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    return int(digits)


@dataclass
class NormalizedLead:
    """
    The uniform record every provider returns from `collect()`.

    All fields are optional at construction so a provider can build one incrementally from
    a sparse source, and `normalize()` is what turns a raw instance into a clean, storable
    one. `is_valid()` then decides whether the CRM can actually accept it.

    Attributes mirror the collection plan's normalized-lead contract; `raw` additionally
    retains the provider's untouched record so a failed or surprising import can be
    diagnosed against exactly what the source returned.
    """

    business_name: str | None = None
    owner_name: str | None = None
    phone_numbers: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    website: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    address: str | None = None
    city: str | None = None
    district: str | None = None
    state: str | None = None
    country: str | None = None
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = None
    source: str | None = None
    source_url: str | None = None
    categories: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def normalize(self) -> "NormalizedLead":
        """
        Returns a cleaned copy of this record: text trimmed and length-capped to the
        corresponding CRM column, numbers coerced and range-checked, URLs given a scheme,
        phone numbers and emails de-duplicated while preserving the provider's ordering.

        Ordering is preserved deliberately: providers list the primary contact number
        first, and `LeadImportService` promotes `phone_numbers[0]` to the CRM's single
        `phone` column. Sorting or setifying here would silently make an arbitrary landline
        the business's headline number.

        This method is total — it never raises. A record whose cleaned form is unusable is
        caught afterwards by `is_valid()`, which lets the import service count it as a
        failed record with a reason instead of aborting the run.
        """
        seen_phones: set[str] = set()
        phones: list[str] = []
        for candidate in self.phone_numbers:
            cleaned = _clean_text(candidate, limit=50)
            if not cleaned:
                continue
            key = normalize_phone(cleaned)
            if not key or key in seen_phones:
                continue
            seen_phones.add(key)
            phones.append(cleaned)

        seen_emails: set[str] = set()
        emails: list[str] = []
        for candidate in self.emails:
            cleaned = normalize_email(candidate)
            if not cleaned or cleaned in seen_emails:
                continue
            seen_emails.add(cleaned)
            emails.append(cleaned)

        seen_categories: set[str] = set()
        categories: list[str] = []
        for candidate in self.categories:
            cleaned = _clean_text(candidate, limit=100)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen_categories:
                continue
            seen_categories.add(key)
            categories.append(cleaned)

        pincode = _clean_text(self.pincode, limit=20)
        if pincode:
            # Pincodes arrive as "560001", "560 001" and occasionally "PIN: 560001".
            digits = re.sub(r"\D", "", pincode)
            pincode = digits or None

        return NormalizedLead(
            business_name=_clean_text(self.business_name, limit=255),
            owner_name=_clean_text(self.owner_name, limit=255),
            phone_numbers=phones,
            emails=emails,
            website=normalize_url(self.website),
            instagram=normalize_instagram(self.instagram),
            facebook=normalize_url(self.facebook),
            address=_clean_text(self.address, limit=500),
            city=_clean_text(self.city, limit=100),
            district=_clean_text(self.district, limit=100),
            state=_clean_text(self.state, limit=100),
            country=_clean_text(self.country, limit=100),
            pincode=pincode,
            latitude=_clean_float(self.latitude, -90, 90),
            longitude=_clean_float(self.longitude, -180, 180),
            rating=_clean_float(self.rating, 0, 5),
            review_count=_clean_int(self.review_count),
            source=_clean_text(self.source, limit=50),
            source_url=normalize_url(self.source_url),
            categories=categories,
            raw=self.raw,
        )

    def is_valid(self) -> tuple[bool, str | None]:
        """
        Reports whether this (already normalized) record can be stored as a Lead, and why
        not if it cannot.

        The CRM requires a non-null `business_name` and a non-null, unique `phone`, so a
        record missing either is unusable no matter how rich the rest of it is. These are
        the only two hard requirements — everything else is enrichment, and a listing with
        no email or no coordinates is still a perfectly good lead.

        Returns:
            (True, None) when storable, otherwise (False, reason) where the reason is
            written into the job's log array for the operator.
        """
        if not self.business_name:
            return False, "Missing business_name."
        if not self.phone_numbers:
            return False, "No usable phone number (a lead requires at least one)."
        return True, None

    @property
    def primary_phone(self) -> str | None:
        """The number promoted to the CRM's `phone` column. See `normalize()` on ordering."""
        return self.phone_numbers[0] if self.phone_numbers else None

    @property
    def secondary_phone(self) -> str | None:
        """
        The number promoted to the CRM's `whatsapp` column when the provider offered more
        than one. A second listed number is far more often a mobile than a fax, and the
        WhatsApp column is nullable and advisory, so this is a useful default rather than a
        risky guess.
        """
        return self.phone_numbers[1] if len(self.phone_numbers) > 1 else None

    @property
    def primary_email(self) -> str | None:
        """The address promoted to the CRM's single `email` column."""
        return self.emails[0] if self.emails else None

    @property
    def phone_keys(self) -> list[str]:
        """Comparison keys for every phone on this record, for duplicate detection."""
        keys = [normalize_phone(p) for p in self.phone_numbers]
        return [k for k in keys if k]

    @property
    def email_keys(self) -> list[str]:
        """Comparison keys for every email on this record, for duplicate detection."""
        keys = [normalize_email(e) for e in self.emails]
        return [k for k in keys if k]

    @property
    def business_key(self) -> str | None:
        """Comparison key for the (business name, city) pair, for duplicate detection."""
        return normalize_business_key(self.business_name, self.city)

    def to_dict(self) -> dict[str, Any]:
        """Renders the record as a plain dict, for logging and API responses."""
        return asdict(self)
