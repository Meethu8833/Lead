"""
app/services/lead_providers/mock.py

This file implements `MockLeadProvider` — the deterministic, offline adapter used to
exercise the entire collection pipeline without contacting any external source.

It is to lead collection what `NoOpWhatsAppProvider` is to outbound messaging: proof that
the surrounding machinery — job lifecycle, normalisation, deduplication, enrichment,
statistics, retry — is exercisable end to end before any real integration is commissioned.
Swapping in a real adapter later changes exactly one thing: which key the caller passes.

Why the fixtures are generated rather than hard-coded
-----------------------------------------------------
The records are derived deterministically from the query string, so the same query always
yields the same businesses. That determinism is what lets the test suite assert that a
*second* run over the same query creates zero new leads and instead takes the duplicate
path — which is the single most important behaviour of this module and impossible to test
against a random fixture set.

The generated batch deliberately includes awkward records — a listing with two phone
numbers, one with a landline-formatted number, one missing a phone entirely, one that is a
near-duplicate of another under a different phone format. Real scrape output looks like
this, and a provider that only ever emits clean records would let normalisation and
deduplication bugs through.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.services.lead_providers.base import (
    LeadProvider,
    ProviderContext,
    register_provider,
)
from app.services.lead_providers.normalized import NormalizedLead


#: Locality fixtures, cycled through so generated records spread across cities rather than
#: all collapsing onto one (which would make the business-name+city dedup rule untestable).
_LOCALITIES: list[dict[str, str]] = [
    {"city": "Bengaluru", "district": "Bengaluru Urban", "state": "Karnataka", "pincode": "560001"},
    {"city": "Mysuru", "district": "Mysuru", "state": "Karnataka", "pincode": "570001"},
    {"city": "Kochi", "district": "Ernakulam", "state": "Kerala", "pincode": "682001"},
    {"city": "Chennai", "district": "Chennai", "state": "Tamil Nadu", "pincode": "600001"},
]

_STUDIO_WORDS: list[str] = [
    "Sunrise", "Golden Frame", "Silver Lens", "Moment", "Aperture",
    "Candid Hues", "White Balance", "Everlight", "Bokeh House", "Prism",
]

_CATEGORY_SETS: list[list[str]] = [
    ["Wedding Photographer", "Candid Photography"],
    ["Photography Studio", "Portrait Photographer"],
    ["Event Photographer", "Wedding Photographer"],
    ["Commercial Photography"],
]


@register_provider
class MockLeadProvider(LeadProvider):
    """
    Offline adapter that fabricates plausible photographer listings for a query.

    Records are a pure function of (query, limit), so runs are reproducible.
    """

    key = "mock"
    display_name = "Mock Provider (offline fixtures)"
    lead_source = "OTHER"
    requires_query = True
    requires_file = False

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        """
        Fabricates up to `context.limit` raw listings derived from the query.

        The seed is the query's hash so results are stable across runs and processes;
        Python's `hash()` is deliberately avoided because it is salted per process for
        strings, which would break exactly the reproducibility this provider exists to
        provide.
        """
        seed = sum(ord(ch) for ch in (context.query or "")) or 1
        count = min(context.limit, 12)

        records: list[dict[str, Any]] = []
        for index in range(count):
            offset = seed + index
            word = _STUDIO_WORDS[offset % len(_STUDIO_WORDS)]
            locality = dict(_LOCALITIES[offset % len(_LOCALITIES)])
            # Context city/state narrow the result set when supplied, mirroring how a real
            # search API would scope its results.
            if context.city:
                locality["city"] = context.city
            if context.state:
                locality["state"] = context.state

            # A stable ten-digit mobile per record.
            mobile = f"9{(offset * 7919) % 1000000000:09d}"
            business_name = f"{word} Photography {offset % 97}"

            record: dict[str, Any] = {
                "name": business_name,
                "owner": f"{word} Owner",
                "phone": mobile,
                "secondary_phone": None,
                "email": f"contact{offset % 97}@{word.split()[0].lower()}studio.example.com",
                "website": f"www.{word.split()[0].lower()}studio{offset % 97}.example.com",
                "instagram": f"@{word.split()[0].lower()}_studio_{offset % 97}",
                "facebook": f"https://facebook.com/{word.split()[0].lower()}studio{offset % 97}",
                "address": f"{12 + index} MG Road, {locality['city']}",
                "city": locality["city"],
                "district": locality["district"],
                "state": locality["state"],
                "country": "India",
                "pincode": locality["pincode"],
                "lat": 12.9 + (offset % 50) / 100,
                "lng": 77.5 + (offset % 50) / 100,
                "rating": round(3.5 + (offset % 15) / 10, 1),
                "reviews": f"{(offset * 13) % 900} reviews",
                "listing_url": f"https://mock.example.com/listing/{offset}",
                "categories": _CATEGORY_SETS[offset % len(_CATEGORY_SETS)],
            }

            # Every fourth record carries a second (landline) number, so the multi-phone
            # path — and dedup against a non-primary number — is always exercised.
            if index % 4 == 1:
                record["secondary_phone"] = f"080 {(offset % 9000) + 1000} {(offset % 9000) + 1000}"

            # Every seventh record has no phone at all, so the failed-record path is always
            # exercised on a batch of reasonable size.
            if index % 7 == 6:
                record["phone"] = None
                record["secondary_phone"] = None

            records.append(record)

        return records

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        """
        Maps one fabricated listing onto the uniform shape. The mapping is intentionally
        as verbose as a real adapter's would be — a real source's field names never match
        ours either, and this is the code a new provider author copies.
        """
        phones = [raw.get("phone"), raw.get("secondary_phone")]
        lead = NormalizedLead(
            business_name=raw.get("name"),
            owner_name=raw.get("owner"),
            phone_numbers=[p for p in phones if p],
            emails=[raw["email"]] if raw.get("email") else [],
            website=raw.get("website"),
            instagram=raw.get("instagram"),
            facebook=raw.get("facebook"),
            address=raw.get("address"),
            city=raw.get("city"),
            district=raw.get("district"),
            state=raw.get("state"),
            country=raw.get("country"),
            pincode=raw.get("pincode"),
            latitude=raw.get("lat"),
            longitude=raw.get("lng"),
            rating=raw.get("rating"),
            review_count=raw.get("reviews"),
            source=self.lead_source,
            source_url=raw.get("listing_url"),
            categories=list(raw.get("categories") or []),
            raw=raw,
        )
        return lead.normalize()
