"""
app/services/lead_deduplication.py

This file implements `LeadDeduplicationService` — the single place that decides whether an
incoming lead record is a new business or one the CRM already holds, and what may be
written onto it if it is.

Under Clean Architecture this is the Application Business Rules layer. It depends on the
`LeadRepository` port and on the pure comparison-key helpers in
`app/services/lead_providers/normalized.py`; it knows nothing about where a record came
from (scrape, CSV, manual entry) and nothing about HTTP. `LeadImportService` previously
carried an inline version of three of these rules; this service generalises that logic to
the full five-rule ladder and makes it reusable by any caller that has records to reconcile.

The five duplicate rules, in priority order
-------------------------------------------
    1. phone       — the record's numbers against the lead's `phone` and `whatsapp`
    2. website     — registrable host, compared after stripping scheme/www/path
    3. email       — trimmed and lowercased
    4. coordinates — within `COORDINATE_TOLERANCE_METRES` of the stored point
    5. name + city — fuzzy business-name similarity, scoped to the same city

The ordering is a confidence ranking, and it is load-bearing: when several rules fire for
different leads, the highest-priority rule picks the winner. Phone ranks first because it
is the CRM's unique key and the channel the business is actually contacted on. Website
ranks above email because a domain identifies an organisation while an email address may be
a shared inbox at a provider (`info@gmail.com` is not an identity). Coordinates rank low
because two studios can share a building, and name+city ranks last because it is the only
rule that can match two genuinely different businesses — a chain with two branches in one
city — so it must never override a contact-level match.

Rules 4 and 5 are the reason this service ranks in Python rather than in SQL. Proximity and
fuzzy similarity are not equality, so they cannot be expressed as an indexed `IN` lookup the
way the first three can. The repository is therefore asked for a *candidate set* using the
indexable rules plus a cheap geographic/city prefilter, and the full ladder is evaluated
against that bounded set here. This keeps the query planner on indexes instead of pushing
the table through a similarity function on every import.

Merge semantics: fill blanks, never overwrite
----------------------------------------------
When a record matches, the lead is *enriched*: a field is written only if it is currently
empty on the lead and non-empty on the record. A collected record never replaces data
already in the CRM, because the existing value may have been typed by a human who phoned
the business, and a scraped listing is not evidence strong enough to discard that. Fields
that are CRM workflow state (`status`, `is_converted`, `assigned_employee_id`) are never
written by this service at all, and neither is `phone` — it is the unique key the match was
frequently made on, so rewriting it could collide with another lead's number.

A match that carries nothing new produces no write. That is what distinguishes a *merged*
result from a plain *duplicate*, and it is what makes re-running the same import a genuine
no-op rather than version-number churn on every row.

Within-batch reconciliation
---------------------------
Records are also matched against records seen earlier in the same batch, not only against
the stored table. A single scrape routinely returns the same studio twice under two phone
formats; without this, the second occurrence would be inserted and immediately violate the
`phone` unique constraint — or worse, slip through under a different number and create the
duplicate this service exists to prevent.

This service does not write to the database. It returns a plan — new, merged, duplicate —
and leaves persistence to the caller, so that the rules can be unit-tested without a
session and so the caller keeps control of its own transaction shape.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.repositories.lead import LeadRepository
from app.services.lead_providers.normalized import (
    NormalizedLead,
    normalize_business_key,
    normalize_email,
    normalize_phone,
)

logger = logging.getLogger(__name__)


# ===========================================================================================
# Rule identity and ranking
# ===========================================================================================

#: Rule names, in the priority order given by the specification. Exposed as constants
#: because they are written into import logs and read by operators, so they must be stable
#: strings rather than incidental literals.
RULE_PHONE = "phone"
RULE_WEBSITE = "website"
RULE_EMAIL = "email"
RULE_COORDINATES = "coordinates"
RULE_NAME_CITY = "business_name_city"

#: Confidence ranking. Higher wins when several rules fire; see the module docstring for
#: why phone outranks website outranks email outranks coordinates outranks name+city.
MATCH_RULE_RANK: dict[str, int] = {
    RULE_NAME_CITY: 1,
    RULE_COORDINATES: 2,
    RULE_EMAIL: 3,
    RULE_WEBSITE: 4,
    RULE_PHONE: 5,
}

#: Rules ordered strongest-first, for callers that want to present or iterate them.
RULE_PRIORITY: tuple[str, ...] = (
    RULE_PHONE,
    RULE_WEBSITE,
    RULE_EMAIL,
    RULE_COORDINATES,
    RULE_NAME_CITY,
)


# ===========================================================================================
# Rule tuning
# ===========================================================================================

#: How close two points must be to be treated as the same premises. Fifty metres is wider
#: than consumer GPS error and wider than the disagreement between two geocoders given the
#: same street address, but narrower than a city block — so it merges two scrapes of one
#: studio without merging its neighbour. Coordinates alone are never conclusive, which is
#: why this rule ranks fourth rather than first.
COORDINATE_TOLERANCE_METRES: float = 50.0

#: Similarity at or above which two business names are considered the same name. 0.87 is
#: deliberately strict: it accepts "Sunrise Photography" vs "Sunrise Photography Studio"
#: and spelling/spacing drift between sources, while rejecting "Sunrise Photography" vs
#: "Sunset Photography", which differ by one word that changes the business entirely.
NAME_SIMILARITY_THRESHOLD: float = 0.87

#: Mean radius of the Earth in metres, for the haversine distance used by the coordinate
#: rule.
_EARTH_RADIUS_METRES: float = 6_371_000.0

#: Latitude degrees per metre, used to size the bounding box handed to the repository as a
#: coordinate prefilter. Longitude is scaled by latitude at the point of use.
_DEGREES_PER_METRE: float = 1.0 / 111_320.0

#: Words that carry no distinguishing information in an Indian photography-business name
#: and are dropped before similarity is measured. Without this, every studio in the table
#: scores highly against every other simply for sharing the word "photography".
_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "photography", "photographs", "photograph", "photos", "photo", "photographer",
        "photographers", "studio", "studios", "digital", "colour", "color", "lab", "labs",
        "the", "and", "co", "company", "creations", "creation", "productions", "production",
        "films", "film", "media", "arts", "art", "pvt", "private", "ltd", "limited", "llp",
        "inc", "enterprises", "enterprise",
    }
)

#: Host prefixes discarded when reducing a website URL to its identity.
_HOST_NOISE_PREFIX = re.compile(r"^(?:www|www\d|m|mobile)\.", re.IGNORECASE)

#: Fields this service may fill on a matched lead. `phone` is absent on purpose: it is the
#: CRM's unique key and usually the thing the match was made on, so rewriting it could
#: collide with another lead's number. `status`, `is_converted` and `assigned_employee_id`
#: are absent because they are CRM workflow state that no external source may touch.
MERGEABLE_FIELDS: tuple[str, ...] = (
    "contact_person",
    "whatsapp",
    "email",
    "instagram",
    "facebook",
    "youtube",
    "website",
    "address",
    "city",
    "district",
    "state",
    "country",
    "latitude",
    "longitude",
)


# ===========================================================================================
# Comparison keys
# ===========================================================================================

def normalize_website_key(value: str | None) -> str | None:
    """
    Reduces a website URL to its comparison key: the bare host, lowercased, with scheme,
    `www.`/`m.` prefix, port, path, query and fragment removed.

    Two sources describing one business routinely disagree on every one of those parts
    ("http://studio.example.com/", "https://www.studio.example.com/contact?ref=maps"), so
    comparing raw URLs would miss the match this rule exists to catch. The registrable host
    is what identifies the organisation.

    Returns None when no host can be recovered, or when the host has no dot — a bare token
    is not a domain, and matching on it would collapse unrelated leads.
    """
    if not value:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    # Drop scheme, then any credentials, then everything from the first path separator on.
    cleaned = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", cleaned)
    cleaned = cleaned.split("@")[-1]
    host = re.split(r"[/?#]", cleaned, maxsplit=1)[0]
    host = host.split(":")[0]
    host = _HOST_NOISE_PREFIX.sub("", host)
    host = host.strip(".")
    if not host or "." not in host:
        return None
    if not re.match(r"^[a-z0-9.\-]+$", host):
        return None
    return host


def normalize_name_tokens(business_name: str | None) -> tuple[str, ...]:
    """
    Reduces a business name to the ordered tokens that actually distinguish it: lowercased,
    punctuation removed, generic trade words dropped (see `_NAME_STOPWORDS`).

    Returns an empty tuple when nothing distinguishing survives — a business called exactly
    "Photo Studio" has no identity of its own, and the caller must decline to match on it
    rather than match it against every other generic name in the city.
    """
    if not business_name:
        return ()
    lowered = str(business_name).strip().lower()
    raw_tokens = [t for t in re.split(r"[^a-z0-9]+", lowered) if t]
    tokens = [t for t in raw_tokens if t not in _NAME_STOPWORDS]
    return tuple(tokens)


def normalize_city_key(city: str | None) -> str | None:
    """
    Reduces a city to its comparison key: lowercased with non-alphanumerics removed, so
    "New Delhi", "new-delhi" and "NEWDELHI" agree. Mirrors the city half of
    `normalize_business_key`.
    """
    if not city:
        return None
    key = re.sub(r"[^a-z0-9]+", "", str(city).strip().lower())
    return key or None


def business_name_similarity(left: str | None, right: str | None) -> float:
    """
    Scores how alike two business names are, in [0.0, 1.0].

    Compares the distinguishing tokens (see `normalize_name_tokens`) two ways and keeps the
    better score:

    - **Token containment** — when one name's tokens are a subset of the other's, the names
      are treated as the same business. This is the "Sunrise Photography" vs "Sunrise
      Photography Studio Kochi" case, where one source carries a longer legal or branch
      name; character-level similarity underrates it badly.
    - **Character similarity** on the joined tokens, which catches transliteration and
      spelling drift ("Krishnaa" vs "Krishna") that token comparison alone would miss.

    Returns 0.0 when either name reduces to nothing distinguishing, so a generic name never
    scores as a match.
    """
    left_tokens = normalize_name_tokens(left)
    right_tokens = normalize_name_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    left_set, right_set = set(left_tokens), set(right_tokens)
    if left_set == right_set:
        return 1.0

    containment = 0.0
    if left_set <= right_set or right_set <= left_set:
        # Subset match. Scale by how much of the longer name is shared so that a
        # single shared token out of five is not treated as a confident match.
        containment = len(left_set & right_set) / max(len(left_set), len(right_set))
        containment = max(containment, NAME_SIMILARITY_THRESHOLD)

    character = SequenceMatcher(
        None, "".join(left_tokens), "".join(right_tokens)
    ).ratio()

    return max(containment, character)


def coordinate_distance_metres(
    lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None
) -> float | None:
    """
    Great-circle distance between two points in metres, or None when either point is
    incomplete.

    Haversine rather than a flat-earth approximation: the cost is irrelevant at the scale
    this runs (a bounded candidate set, not a table scan) and it stays correct regardless of
    latitude, which a naive degree-delta does not.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METRES * math.asin(min(1.0, math.sqrt(a)))


# ===========================================================================================
# Result types
# ===========================================================================================

@dataclass(frozen=True)
class DuplicateMatch:
    """
    One record's match against an existing lead: which lead, which rule fired, and how
    confident that rule is.

    `score` carries the similarity for the name rule and the distance in metres for the
    coordinate rule, so an operator reading an import log can see *why* two records were
    considered the same business rather than having to trust the verdict.
    """
    lead_id: uuid.UUID | None
    rule: str
    rank: int
    score: float | None = None
    detail: str | None = None
    within_batch: bool = False


@dataclass(frozen=True)
class NewLeadResult:
    """A record that matched nothing and should be inserted as a new lead."""
    index: int
    record: NormalizedLead


@dataclass(frozen=True)
class MergedLeadResult:
    """
    A record that matched an existing lead and carries at least one field that lead is
    missing. `changes` is the fill-the-blanks update the caller should apply — it never
    contains a field that was already populated.
    """
    index: int
    record: NormalizedLead
    match: DuplicateMatch
    changes: dict[str, Any]


@dataclass(frozen=True)
class DuplicateLeadResult:
    """
    A record that matched an existing lead and adds nothing to it. Reported rather than
    silently dropped, so a run's totals reconcile and an operator can see that a source is
    returning data the CRM already holds.
    """
    index: int
    record: NormalizedLead
    match: DuplicateMatch


@dataclass
class DeduplicationResult:
    """
    The plan for a whole batch: what to insert, what to enrich, and what to ignore.

    Deliberately a plan rather than an applied change. The service performs no writes, so
    the caller keeps ownership of its transaction shape — `LeadImportService` commits per
    record so one failure cannot roll back a long run, while a bulk caller may prefer a
    single transaction. Both are expressible against this result; neither would be if this
    service committed.
    """
    new_leads: list[NewLeadResult] = field(default_factory=list)
    merged_leads: list[MergedLeadResult] = field(default_factory=list)
    duplicates: list[DuplicateLeadResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Records accounted for. Always equals the number of records handed in."""
        return len(self.new_leads) + len(self.merged_leads) + len(self.duplicates)

    def summary(self) -> dict[str, int]:
        """Counts, in the shape `ImportJob` records them."""
        return {
            "new": len(self.new_leads),
            "merged": len(self.merged_leads),
            "duplicate": len(self.duplicates),
            "total": self.total,
        }


# ===========================================================================================
# Service
# ===========================================================================================

class LeadDeduplicationService:
    """
    Decides whether incoming lead records are new, mergeable into an existing lead, or
    redundant — applying the five duplicate rules in priority order.

    Responsibilities:
    - Build comparison keys for a record and for a stored lead.
    - Fetch a bounded candidate set and rank every rule against it.
    - Compute the fill-the-blanks merge for a matched lead.
    - Reconcile records against each other within one batch.

    Performs no writes; see `DeduplicationResult`.
    """

    def __init__(
        self,
        lead_repository: LeadRepository | None = None,
        coordinate_tolerance_metres: float = COORDINATE_TOLERANCE_METRES,
        name_similarity_threshold: float = NAME_SIMILARITY_THRESHOLD,
    ) -> None:
        """
        Thresholds are constructor arguments rather than hardcoded reads of the module
        constants so a caller working a noisier source can loosen them, and so the unit
        suite can prove behaviour at a boundary without monkeypatching module state.
        """
        self.lead_repository = lead_repository or LeadRepository()
        self.coordinate_tolerance_metres = coordinate_tolerance_metres
        self.name_similarity_threshold = name_similarity_threshold

    # -----------------------------------------------------------------------------------
    # Rule evaluation
    # -----------------------------------------------------------------------------------

    def classify_match(
        self, record: NormalizedLead, candidate: Lead
    ) -> DuplicateMatch | None:
        """
        Reports the highest-priority rule under which `record` and `candidate` are the same
        business, or None if no rule fires.

        Evaluated strongest-first with an early return: once phone matches, nothing weaker
        can change the verdict, and the rule name reported is the one written into the
        import log — so it must be the rule that actually justified the merge, not merely
        one that happened to agree.
        """
        phone_keys = {k for k in record.phone_keys if k}
        if phone_keys:
            for stored in (candidate.phone, candidate.whatsapp):
                key = normalize_phone(stored)
                if key and key in phone_keys:
                    return DuplicateMatch(
                        lead_id=candidate.id, rule=RULE_PHONE,
                        rank=MATCH_RULE_RANK[RULE_PHONE], score=1.0, detail=key,
                    )

        record_site = normalize_website_key(record.website)
        if record_site:
            candidate_site = normalize_website_key(candidate.website)
            if candidate_site and candidate_site == record_site:
                return DuplicateMatch(
                    lead_id=candidate.id, rule=RULE_WEBSITE,
                    rank=MATCH_RULE_RANK[RULE_WEBSITE], score=1.0, detail=record_site,
                )

        email_keys = {k for k in record.email_keys if k}
        if email_keys:
            key = normalize_email(candidate.email)
            if key and key in email_keys:
                return DuplicateMatch(
                    lead_id=candidate.id, rule=RULE_EMAIL,
                    rank=MATCH_RULE_RANK[RULE_EMAIL], score=1.0, detail=key,
                )

        distance = coordinate_distance_metres(
            record.latitude, record.longitude, candidate.latitude, candidate.longitude
        )
        if distance is not None and distance <= self.coordinate_tolerance_metres:
            return DuplicateMatch(
                lead_id=candidate.id, rule=RULE_COORDINATES,
                rank=MATCH_RULE_RANK[RULE_COORDINATES], score=distance,
                detail=f"{distance:.1f}m",
            )

        # Name similarity is scoped to a shared city: the same name in two cities is two
        # businesses, and without the city scope this rule would merge a chain's branches
        # across the country.
        record_city = normalize_city_key(record.city)
        candidate_city = normalize_city_key(candidate.city)
        if record_city and candidate_city and record_city == candidate_city:
            similarity = business_name_similarity(
                record.business_name, candidate.business_name
            )
            if similarity >= self.name_similarity_threshold:
                return DuplicateMatch(
                    lead_id=candidate.id, rule=RULE_NAME_CITY,
                    rank=MATCH_RULE_RANK[RULE_NAME_CITY], score=similarity,
                    detail=f"{similarity:.2f} in {candidate_city}",
                )

        return None

    def select_best_match(
        self, record: NormalizedLead, candidates: Iterable[Lead]
    ) -> tuple[Lead | None, DuplicateMatch | None]:
        """
        Picks the single lead a record duplicates, out of a candidate set.

        The rules can disagree — a record's phone may match lead A while its name and city
        match lead B, typically because one studio was captured twice under two numbers.
        The highest-ranked rule wins. Ties are broken by the most recently created lead,
        matching the repository's ordering, so the outcome is deterministic when a record
        genuinely matches two leads equally well.

        Returns (None, None) when the record is new.
        """
        best_lead: Lead | None = None
        best_match: DuplicateMatch | None = None

        for candidate in candidates:
            if candidate is None or getattr(candidate, "is_deleted", False):
                continue
            match = self.classify_match(record, candidate)
            if match is None:
                continue
            if best_match is None or match.rank > best_match.rank:
                best_lead, best_match = candidate, match

        return best_lead, best_match

    # -----------------------------------------------------------------------------------
    # Merge
    # -----------------------------------------------------------------------------------

    def build_merge(self, existing: Lead, record: NormalizedLead) -> dict[str, Any]:
        """
        Computes the fill-the-blanks update for a matched lead: every mergeable field that
        is empty on the lead and non-empty on the record.

        Returns an empty dict when the record adds nothing, which is what lets the caller
        report a plain duplicate and skip the write entirely.

        The one deliberate exception to "never overwrite" is `whatsapp`, and it is still not
        an overwrite: if the lead has no WhatsApp number and the record's primary phone
        differs from the lead's stored phone, that second number is recorded as the WhatsApp
        number rather than discarded. Given the CRM stores exactly two numbers, this is the
        only way a second number collected later is retained at all.
        """
        candidate_values: dict[str, Any] = {
            "contact_person": record.owner_name,
            "whatsapp": record.secondary_phone,
            "email": record.primary_email,
            "instagram": record.instagram,
            "facebook": record.facebook,
            "youtube": record.youtube,
            "website": record.website,
            "address": record.address,
            "city": record.city,
            "district": record.district,
            "state": record.state,
            "country": record.country,
            "latitude": record.latitude,
            "longitude": record.longitude,
        }

        # See docstring: retain an otherwise-lost second number.
        if not candidate_values["whatsapp"] and record.primary_phone:
            incoming = normalize_phone(record.primary_phone)
            stored = normalize_phone(existing.phone)
            if incoming and incoming != stored:
                candidate_values["whatsapp"] = record.primary_phone

        changes: dict[str, Any] = {}
        for field_name in MERGEABLE_FIELDS:
            new_value = candidate_values.get(field_name)
            if new_value is None or new_value == "":
                continue
            current = getattr(existing, field_name, None)
            # Only a genuinely empty field may be filled. Note `0` and `0.0` are NOT empty:
            # latitude 0.0 is a real coordinate and must not be treated as a blank.
            if current is None or (isinstance(current, str) and not current.strip()):
                changes[field_name] = new_value

        return changes

    # -----------------------------------------------------------------------------------
    # Candidate retrieval
    # -----------------------------------------------------------------------------------

    async def find_candidates(
        self, db: AsyncSession, record: NormalizedLead
    ) -> list[Lead]:
        """
        Fetches the bounded set of leads that could be the same business as `record`.

        Two queries, unioned by id:

        1. The repository's indexed OR over phone, email and name|city keys — the rules
           that are exact equality and therefore cheap in SQL.
        2. A city / bounding-box prefilter for the two rules that equality cannot express.
           Coordinate proximity and fuzzy name similarity are evaluated in Python, so this
           query's job is only to bound how much comes back: a latitude/longitude box
           slightly larger than the tolerance, plus leads in the same city.

        Splitting it this way is what keeps the planner on indexes. Evaluating similarity in
        SQL for every stored lead would turn each imported record into a table scan.
        """
        candidates: dict[uuid.UUID, Lead] = {}

        rows = await self.lead_repository.find_duplicate_candidates(
            db,
            phone_keys=[k for k in record.phone_keys if k],
            email_keys=[k for k in record.email_keys if k],
            business_key=record.business_key,
        )
        for row in rows:
            candidates[row.id] = row

        for row in await self._find_fuzzy_candidates(db, record):
            candidates.setdefault(row.id, row)

        return list(candidates.values())

    async def _find_fuzzy_candidates(
        self, db: AsyncSession, record: NormalizedLead
    ) -> Sequence[Lead]:
        """
        Fetches leads that could satisfy the coordinate or name-similarity rules.

        Uses `LeadRepository.find_proximity_candidates` when the repository provides it,
        and otherwise returns nothing rather than falling back to loading the table. A
        missing prefilter must degrade to "these two rules see fewer candidates", never to
        "every import scans every lead" — the second is an outage, the first is a bounded
        loss of recall on the two weakest rules.
        """
        finder = getattr(self.lead_repository, "find_proximity_candidates", None)
        if finder is None:
            return []

        latitude, longitude = record.latitude, record.longitude
        lat_delta = lon_delta = None
        if latitude is not None and longitude is not None:
            lat_delta = self.coordinate_tolerance_metres * _DEGREES_PER_METRE
            # Longitude degrees shrink towards the poles; widen the box accordingly so the
            # prefilter never excludes a point the haversine check would have accepted.
            cos_lat = max(math.cos(math.radians(float(latitude))), 1e-6)
            lon_delta = lat_delta / cos_lat

        try:
            return await finder(
                db,
                latitude=latitude,
                longitude=longitude,
                lat_delta=lat_delta,
                lon_delta=lon_delta,
                city=record.city,
            )
        except Exception:  # pragma: no cover - defensive
            # A failure to widen the candidate set must not fail the import; the exact
            # rules above have already run.
            logger.exception(
                "Proximity candidate lookup failed; continuing with exact-rule candidates"
            )
            return []

    # -----------------------------------------------------------------------------------
    # Orchestration
    # -----------------------------------------------------------------------------------

    async def deduplicate(
        self,
        db: AsyncSession,
        records: Sequence[NormalizedLead],
    ) -> DeduplicationResult:
        """
        Classifies a batch of records into new leads, merged leads and duplicates.

        Records are processed in order, and each is matched against both the stored table
        and the records already classified in this batch (see the module docstring on
        within-batch reconciliation). A record matching an earlier *new* record in the same
        batch is reported as a duplicate of it rather than as a second new lead, because
        inserting both would violate the `phone` unique constraint.

        The result is a plan; nothing is written. `result.total` always equals
        `len(records)`, so a caller's statistics reconcile.
        """
        result = DeduplicationResult()

        # Records classified so far in this batch, so later records match against them.
        # A batch-local record has no lead id yet, hence the index-keyed identity.
        batch_records: list[tuple[int, NormalizedLead]] = []

        for index, record in enumerate(records):
            normalized = record.normalize() if hasattr(record, "normalize") else record

            candidates = await self.find_candidates(db, normalized)
            existing, match = self.select_best_match(normalized, candidates)

            if existing is not None and match is not None:
                changes = self.build_merge(existing, normalized)
                if changes:
                    result.merged_leads.append(
                        MergedLeadResult(
                            index=index, record=normalized, match=match, changes=changes
                        )
                    )
                else:
                    result.duplicates.append(
                        DuplicateLeadResult(
                            index=index, record=normalized, match=match
                        )
                    )
                batch_records.append((index, normalized))
                continue

            batch_match = self._match_within_batch(normalized, batch_records)
            if batch_match is not None:
                result.duplicates.append(
                    DuplicateLeadResult(
                        index=index, record=normalized, match=batch_match
                    )
                )
                batch_records.append((index, normalized))
                continue

            result.new_leads.append(NewLeadResult(index=index, record=normalized))
            batch_records.append((index, normalized))

        logger.info(
            "Deduplicated %d records: %d new, %d merged, %d duplicate",
            result.total,
            len(result.new_leads),
            len(result.merged_leads),
            len(result.duplicates),
        )
        return result

    def _match_within_batch(
        self,
        record: NormalizedLead,
        batch_records: Sequence[tuple[int, NormalizedLead]],
    ) -> DuplicateMatch | None:
        """
        Reports whether `record` duplicates one already seen in this batch, applying the
        same five rules and the same priority order as the database match.

        Compares record-to-record by projecting the earlier record onto a transient `Lead`
        so exactly one implementation of the rules exists. A second copy of the ladder for
        the in-memory case is precisely the kind of drift that lets a rule silently apply
        to stored leads but not to same-batch ones.

        Later records win ties by scanning in reverse, mirroring the repository's
        most-recent-first ordering.
        """
        best: DuplicateMatch | None = None

        for index, earlier in reversed(list(batch_records)):
            projected = self._project_record(earlier)
            match = self.classify_match(record, projected)
            if match is None:
                continue
            if best is None or match.rank > best.rank:
                best = DuplicateMatch(
                    lead_id=None,
                    rule=match.rule,
                    rank=match.rank,
                    score=match.score,
                    detail=f"record #{index}"
                    + (f" ({match.detail})" if match.detail else ""),
                    within_batch=True,
                )

        return best

    @staticmethod
    def _project_record(record: NormalizedLead) -> Lead:
        """
        Builds a transient, unpersisted `Lead` carrying a record's comparison-relevant
        fields, so batch-local records can be run through the same `classify_match` as
        stored rows.

        Never added to a session: it exists only as an argument. Constructing it field by
        field rather than via the model's defaults keeps it free of any DB round trip.
        """
        projected = Lead()
        projected.id = None
        projected.business_name = record.business_name
        projected.phone = record.primary_phone
        projected.whatsapp = record.secondary_phone
        projected.email = record.primary_email
        projected.website = record.website
        projected.city = record.city
        projected.latitude = record.latitude
        projected.longitude = record.longitude
        projected.is_deleted = False
        return projected
