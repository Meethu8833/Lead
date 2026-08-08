"""
tests/test_lead_deduplication.py

Unit test suite for `LeadDeduplicationService` — the five-rule duplicate detector and
fill-the-blanks merge layer for incoming lead records.

Verifies, section by section, the requirements the feature was specified against:

1.  Rule 1, phone — the highest-confidence rule; matched across formatting variants and
    against both the `phone` and `whatsapp` columns.
2.  Rule 2, website — matched on the registrable host, so scheme, `www.`, port, path and
    query differences do not hide a match.
3.  Rule 3, email — matched case- and whitespace-insensitively.
4.  Rule 4, coordinates — matched inside the distance tolerance and declined outside it.
5.  Rule 5, business-name similarity + city — fuzzy name matching scoped to one city, with
    generic trade words discounted so unrelated studios do not collapse together.
6.  **Rule priority** — the headline requirement. When several rules fire for *different*
    leads, the highest-priority rule decides, phone > website > email > coordinates >
    name+city.
7.  **Merge fills only missing information** — every populated field is proven untouched,
    including falsy-but-real values (`0.0` latitude) that a naive emptiness check would
    clobber.
8.  Return shape — new / merged / duplicate, with the three buckets proven to account for
    every record handed in.
9.  Within-batch reconciliation — the same rules applied to records against each other, so
    one scrape returning a studio twice yields one lead.
10. **No database writes and no UI changes** — asserted structurally: the service module
    holds no `commit`, and no frontend file references the service.

This is a **pure unit suite**: the repository is replaced by an in-memory fake, so there is
no session, no network, no fixtures and no cleanup block. It is safe to run anywhere with no
`.env`, no Postgres and no credential.

Run:  python tests/test_lead_deduplication.py
"""

import ast
import asyncio
import os
import subprocess
import sys
import uuid

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.lead import Lead
from app.services import lead_deduplication as module
from app.services.lead_deduplication import (
    RULE_COORDINATES,
    RULE_EMAIL,
    RULE_NAME_CITY,
    RULE_PHONE,
    RULE_WEBSITE,
    LeadDeduplicationService,
    business_name_similarity,
    coordinate_distance_metres,
    normalize_website_key,
)
from app.services.lead_providers.normalized import NormalizedLead


# ===========================================================================================
# Fakes
# ===========================================================================================

class FakeLeadRepository:
    """
    In-memory stand-in for `LeadRepository`.

    Reimplements only the two candidate queries the service calls, in Python. It is
    deliberately *over-inclusive* — it returns every stored lead as a candidate rather than
    mirroring the SQL predicates — because the point of these tests is the service's rule
    ladder and merge behaviour, and a fake that re-encoded the SQL filters could hide a
    service bug behind an identical mistake in the fake.
    """

    def __init__(self, leads=None):
        self.leads = list(leads or [])

    async def find_duplicate_candidates(
        self, db, phone_keys=(), email_keys=(), business_key=None, include_deleted=None
    ):
        return [lead for lead in self.leads if not lead.is_deleted]

    async def find_proximity_candidates(
        self, db, latitude=None, longitude=None, lat_delta=None,
        lon_delta=None, city=None, limit=200, include_deleted=None,
    ):
        return [lead for lead in self.leads if not lead.is_deleted]


def make_lead(**kwargs) -> Lead:
    """Builds a transient Lead with sensible blanks, for use as a stored row."""
    lead = Lead()
    lead.id = kwargs.pop("id", uuid.uuid4())
    defaults = {
        "business_name": None, "contact_person": None, "phone": None, "whatsapp": None,
        "email": None, "instagram": None, "facebook": None, "website": None,
        "address": None, "city": None, "district": None, "state": None, "country": None,
        "latitude": None, "longitude": None, "is_deleted": False,
    }
    defaults.update(kwargs)
    for key, value in defaults.items():
        setattr(lead, key, value)
    return lead


def make_record(**kwargs) -> NormalizedLead:
    """Builds a NormalizedLead, accepting a bare `phone`/`email` for brevity."""
    phone = kwargs.pop("phone", None)
    email = kwargs.pop("email", None)
    if phone is not None:
        kwargs.setdefault("phone_numbers", [phone] if isinstance(phone, str) else phone)
    if email is not None:
        kwargs.setdefault("emails", [email] if isinstance(email, str) else email)
    return NormalizedLead(**kwargs)


def service(leads=None, **kwargs) -> LeadDeduplicationService:
    return LeadDeduplicationService(
        lead_repository=FakeLeadRepository(leads), **kwargs
    )


def classify(record, lead, **kwargs):
    """Returns the rule name that fires for a record/lead pair, or None."""
    match = service(**kwargs).classify_match(record, lead)
    return match.rule if match else None


def run(coro):
    return asyncio.run(coro)


# ===========================================================================================
# 1. Rule 1 — phone
# ===========================================================================================

def test_rule_phone():
    print("\n[1] Rule 1 — phone")

    stored = make_lead(business_name="Sunrise Photography", phone="+91 98765 43210")

    # The same number in every format a source realistically produces.
    for variant in ["9876543210", "+919876543210", "098765 43210", "919876543210",
                    "+91-98765-43210", "(+91) 98765.43210"]:
        assert classify(make_record(phone=variant), stored) == RULE_PHONE, variant
    print("    formatting variants all match on phone .......................... PASS")

    # The record's number is checked against the lead's WhatsApp column too, since a
    # business first captured under its landline may be re-scraped under its mobile.
    whatsapp_only = make_lead(phone="0484 2345678", whatsapp="9876543210")
    assert classify(make_record(phone="+91 98765 43210"), whatsapp_only) == RULE_PHONE
    print("    record phone matches the lead's whatsapp column .................. PASS")

    # Every number a record carries participates, not just the primary.
    multi = make_record(phone_numbers=["04842345678", "9876543210"])
    assert classify(multi, stored) == RULE_PHONE
    print("    secondary numbers on the record also match ....................... PASS")

    # A different number is not a match.
    assert classify(make_record(phone="9000000001"), stored) is None
    # Too few digits to identify anyone: declined rather than guessed at.
    assert classify(make_record(phone="12345"), stored) is None
    print("    different / fragmentary numbers decline .......................... PASS")


# ===========================================================================================
# 2. Rule 2 — website
# ===========================================================================================

def test_rule_website():
    print("\n[2] Rule 2 — website")

    assert normalize_website_key("https://www.studio.example.com/contact?ref=maps") == "studio.example.com"
    assert normalize_website_key("HTTP://Studio.Example.COM:8080/") == "studio.example.com"
    assert normalize_website_key("m.studio.example.com") == "studio.example.com"
    assert normalize_website_key("studio.example.com/#about") == "studio.example.com"
    print("    scheme/www/port/path/query all reduce to the host ................ PASS")

    # A bare token is not a domain and must never become a match key.
    assert normalize_website_key("studio") is None
    assert normalize_website_key("") is None
    assert normalize_website_key(None) is None
    print("    non-domains produce no key ....................................... PASS")

    stored = make_lead(website="http://www.studio.example.com/")
    record = make_record(website="https://studio.example.com/gallery?utm_source=x")
    assert classify(record, stored) == RULE_WEBSITE
    print("    two spellings of one site match .................................. PASS")

    # Different hosts, including a subdomain difference, are different businesses.
    assert classify(make_record(website="https://other.example.com"), stored) is None
    assert classify(make_record(website="https://shop.studio.example.com"), stored) is None
    print("    different hosts decline .......................................... PASS")


# ===========================================================================================
# 3. Rule 3 — email
# ===========================================================================================

def test_rule_email():
    print("\n[3] Rule 3 — email")

    stored = make_lead(email="Info@Studio.com")
    assert classify(make_record(email="info@studio.com"), stored) == RULE_EMAIL
    assert classify(make_record(email="  INFO@STUDIO.COM  "), stored) == RULE_EMAIL
    print("    case and whitespace insensitive .................................. PASS")

    multi = make_record(emails=["hello@other.com", "info@studio.com"])
    assert classify(multi, stored) == RULE_EMAIL
    print("    any of the record's addresses matches ............................ PASS")

    assert classify(make_record(email="different@studio.com"), stored) is None
    # Malformed input never becomes a match key.
    assert classify(make_record(email="not-an-email"), stored) is None
    print("    different / malformed addresses decline .......................... PASS")


# ===========================================================================================
# 4. Rule 4 — coordinates
# ===========================================================================================

def test_rule_coordinates():
    print("\n[4] Rule 4 — coordinates")

    # Haversine sanity: one degree of latitude is ~111km.
    assert 110_000 < coordinate_distance_metres(0.0, 0.0, 1.0, 0.0) < 112_000
    assert coordinate_distance_metres(9.9, 76.2, 9.9, 76.2) == 0.0
    assert coordinate_distance_metres(None, 76.2, 9.9, 76.2) is None
    print("    distance is correct and declines incomplete points ............... PASS")

    stored = make_lead(latitude=9.93120, longitude=76.26730)

    # ~15m away — the same premises as far as two geocoders are concerned.
    near = make_record(latitude=9.93130, longitude=76.26740)
    assert classify(near, stored) == RULE_COORDINATES
    print("    points inside the tolerance match ................................ PASS")

    # ~1.5km away — a different business.
    far = make_record(latitude=9.94500, longitude=76.26730)
    assert classify(far, stored) is None
    print("    points outside the tolerance decline ............................. PASS")

    # The tolerance is a real boundary and is configurable.
    mid = make_record(latitude=9.93300, longitude=76.26730)   # ~200m
    assert classify(mid, stored) is None
    assert classify(mid, stored, coordinate_tolerance_metres=500.0) == RULE_COORDINATES
    print("    the tolerance is honoured and configurable ....................... PASS")

    # A lead with no coordinates cannot match on this rule.
    assert classify(near, make_lead()) is None
    print("    a lead without coordinates declines .............................. PASS")


# ===========================================================================================
# 5. Rule 5 — business name similarity + city
# ===========================================================================================

def test_rule_name_and_city():
    print("\n[5] Rule 5 — business name similarity + city")

    assert business_name_similarity("Sunrise Photography", "SUNRISE  Photography.") == 1.0
    assert business_name_similarity("Sunrise Photography", "Sunrise Photography Studio") >= 0.87
    assert business_name_similarity("Krishnaa Studio", "Krishna Studio") >= 0.87
    print("    case/punctuation/longer-name/spelling drift all score high ....... PASS")

    # A shared generic word is not a shared identity.
    assert business_name_similarity("Sunrise Photography", "Sunset Photography") < 0.87
    assert business_name_similarity("Photo Studio", "Digital Studio") < 0.87
    print("    generic trade words do not create similarity ..................... PASS")

    stored = make_lead(business_name="Sunrise Photography", city="Kochi")

    same = make_record(business_name="Sunrise Photography Studio", city="kochi")
    assert classify(same, stored) == RULE_NAME_CITY
    print("    same name, same city (normalised) matches ........................ PASS")

    # The city scope is what stops a chain's branches merging across the country.
    other_city = make_record(business_name="Sunrise Photography", city="Chennai")
    assert classify(other_city, stored) is None
    print("    same name in a different city declines ........................... PASS")

    # A missing city means no key at all, rather than a bare-name match.
    assert classify(make_record(business_name="Sunrise Photography"), stored) is None
    assert classify(same, make_lead(business_name="Sunrise Photography")) is None
    print("    a missing city on either side declines ........................... PASS")

    assert classify(make_record(business_name="Sunset Photography", city="Kochi"), stored) is None
    print("    a different name in the same city declines ....................... PASS")


# ===========================================================================================
# 6. Rule priority
# ===========================================================================================

def test_rule_priority():
    print("\n[6] Rule priority — phone > website > email > coordinates > name+city")

    # Each lead below is matchable by exactly one rule; the record matches all five, but
    # against five *different* leads. The strongest rule must pick the winner.
    by_phone = make_lead(business_name="A", phone="9876543210")
    by_website = make_lead(business_name="B", website="https://studio.example.com")
    by_email = make_lead(business_name="C", email="info@studio.com")
    by_coords = make_lead(business_name="D", latitude=9.93120, longitude=76.26730)
    by_name = make_lead(business_name="Sunrise Photography", city="Kochi")

    record = make_record(
        business_name="Sunrise Photography", city="Kochi",
        phone="+91 98765 43210", email="info@studio.com",
        website="https://www.studio.example.com/",
        latitude=9.93125, longitude=76.26735,
    )

    ladder = [
        ([by_phone, by_website, by_email, by_coords, by_name], by_phone, RULE_PHONE),
        ([by_website, by_email, by_coords, by_name], by_website, RULE_WEBSITE),
        ([by_email, by_coords, by_name], by_email, RULE_EMAIL),
        ([by_coords, by_name], by_coords, RULE_COORDINATES),
        ([by_name], by_name, RULE_NAME_CITY),
    ]
    for candidates, expected_lead, expected_rule in ladder:
        svc = service()
        lead, match = svc.select_best_match(record, candidates)
        assert lead is expected_lead, (expected_rule, lead.business_name if lead else None)
        assert match.rule == expected_rule, match.rule
        print(f"    with {len(candidates)} candidates -> {expected_rule:<18} wins ............ PASS")

    # Candidate order must not change the verdict.
    svc = service()
    lead, match = svc.select_best_match(record, [by_name, by_coords, by_email, by_phone])
    assert lead is by_phone and match.rule == RULE_PHONE
    print("    verdict is independent of candidate order ........................ PASS")

    # A soft-deleted lead must not absorb a record.
    deleted = make_lead(phone="9876543210", is_deleted=True)
    lead, match = svc.select_best_match(record, [deleted])
    assert lead is None and match is None
    print("    soft-deleted leads are never matched ............................. PASS")


# ===========================================================================================
# 7. Merge — fill missing information, never overwrite
# ===========================================================================================

def test_merge_never_overwrites():
    print("\n[7] Merge — fills blanks, never overwrites")

    svc = service()

    # Every listed field is already populated, and the record disagrees about all of them.
    populated = make_lead(
        business_name="Sunrise Photography", phone="9876543210",
        contact_person="Existing Person", whatsapp="9000000000",
        email="existing@studio.com", instagram="existing", facebook="https://fb.com/existing",
        website="https://existing.com", address="Existing Address", city="Kochi",
        district="Ernakulam", state="Kerala", country="India",
        latitude=9.93120, longitude=76.26730,
    )
    aggressive = make_record(
        business_name="Sunrise Photography", owner_name="New Person",
        phone_numbers=["9876543210", "9111111111"], emails=["new@studio.com"],
        instagram="new", facebook="https://fb.com/new", website="https://new.com",
        address="New Address", city="Chennai", district="Chennai", state="TN",
        country="Nepal", latitude=11.0, longitude=77.0,
    )
    assert svc.build_merge(populated, aggressive) == {}
    print("    a fully populated lead takes no changes at all ................... PASS")

    # The mirror image: everything empty, so everything is filled.
    empty = make_lead(business_name="Sunrise Photography", phone="9876543210")
    changes = svc.build_merge(empty, aggressive)
    for field_name in ("contact_person", "email", "instagram", "facebook", "website",
                       "address", "city", "district", "state", "country",
                       "latitude", "longitude"):
        assert field_name in changes, field_name
    assert changes["contact_person"] == "New Person"
    print("    an empty lead is filled from the record .......................... PASS")

    # `phone` is never written: it is the unique key the match was made on.
    assert "phone" not in changes
    print("    phone is never written by a merge ................................ PASS")

    # Partial: only the genuinely empty fields move.
    partial = make_lead(
        business_name="Sunrise Photography", phone="9876543210",
        email="existing@studio.com", city="Kochi",
    )
    changes = svc.build_merge(partial, aggressive)
    assert "email" not in changes and "city" not in changes
    assert changes["website"] == "https://new.com"
    assert changes["address"] == "New Address"
    print("    populated fields skipped, empty ones filled ...................... PASS")

    # A whitespace-only stored value is empty in substance, so it may be filled.
    blankish = make_lead(business_name="X", phone="9876543210", address="   ")
    assert svc.build_merge(blankish, aggressive)["address"] == "New Address"
    print("    whitespace-only stored values count as empty ..................... PASS")

    # THE trap: 0.0 is a real coordinate, not a blank. Overwriting it would silently
    # relocate a lead on the null island to wherever the scrape guessed.
    at_zero = make_lead(business_name="X", phone="9876543210", latitude=0.0, longitude=0.0)
    changes = svc.build_merge(at_zero, aggressive)
    assert "latitude" not in changes and "longitude" not in changes
    print("    a 0.0 coordinate is data, not a blank, and survives .............. PASS")

    # The documented exception: a second number is retained as whatsapp rather than lost.
    lead = make_lead(business_name="X", phone="9876543210")
    second = make_record(phone_numbers=["9111111111"])
    assert svc.build_merge(lead, second)["whatsapp"] == "9111111111"
    # ...but never over a whatsapp number that is already there.
    has_wa = make_lead(business_name="X", phone="9876543210", whatsapp="9222222222")
    assert "whatsapp" not in svc.build_merge(has_wa, second)
    print("    a second number becomes whatsapp only when that field is empty ... PASS")


# ===========================================================================================
# 8. Return shape — new / merged / duplicates
# ===========================================================================================

def test_return_shape():
    print("\n[8] Return shape — new leads, merged leads, duplicates")

    stored_merge = make_lead(business_name="Sunrise Photography", phone="9876543210")
    stored_dup = make_lead(
        business_name="Moonlight Studio", phone="9000000002",
        email="moon@studio.com", website="https://moon.example.com",
        city="Kochi", address="Known Address", contact_person="Known Person",
    )
    svc = service([stored_merge, stored_dup])

    records = [
        # matches stored_merge on phone, and brings an email it lacks -> merged
        make_record(business_name="Sunrise Photography", phone="+91 98765 43210",
                    emails=["new@studio.com"]),
        # matches stored_dup on phone and adds nothing -> duplicate
        make_record(business_name="Moonlight Studio", phone="9000000002"),
        # matches nothing -> new
        make_record(business_name="Starlight Photography", phone="9333333333"),
    ]
    result = run(svc.deduplicate(None, records))

    assert len(result.merged_leads) == 1, result.summary()
    assert len(result.duplicates) == 1, result.summary()
    assert len(result.new_leads) == 1, result.summary()
    print("    one of each bucket, as expected .................................. PASS")

    merged = result.merged_leads[0]
    assert merged.match.rule == RULE_PHONE
    assert merged.match.lead_id == stored_merge.id
    assert merged.changes == {"email": "new@studio.com"}
    print("    merged carries the rule, the lead id and only the new fields ..... PASS")

    assert result.duplicates[0].match.lead_id == stored_dup.id
    assert result.new_leads[0].record.business_name == "Starlight Photography"
    print("    duplicate names the lead it duplicates ........................... PASS")

    # Every record is accounted for exactly once — a run's statistics must reconcile.
    assert result.total == len(records)
    assert result.summary() == {"new": 1, "merged": 1, "duplicate": 1, "total": 3}
    indices = sorted([r.index for r in result.new_leads]
                     + [r.index for r in result.merged_leads]
                     + [r.index for r in result.duplicates])
    assert indices == [0, 1, 2]
    print("    buckets partition the input; indices are preserved ............... PASS")

    # An empty batch is not an error.
    assert run(service([]).deduplicate(None, [])).summary()["total"] == 0
    print("    an empty batch yields empty buckets .............................. PASS")


# ===========================================================================================
# 9. Within-batch reconciliation
# ===========================================================================================

def test_within_batch():
    print("\n[9] Within-batch reconciliation")

    svc = service([])

    # The same studio twice under two phone formats — the classic scrape output. Inserting
    # both would violate the `phone` unique constraint.
    result = run(svc.deduplicate(None, [
        make_record(business_name="Sunrise Photography", phone="9876543210"),
        make_record(business_name="Sunrise Photography", phone="+91 98765 43210"),
    ]))
    assert len(result.new_leads) == 1, result.summary()
    assert len(result.duplicates) == 1, result.summary()
    assert result.duplicates[0].match.within_batch is True
    assert result.duplicates[0].match.lead_id is None
    print("    a repeated record becomes one new lead + one duplicate ........... PASS")

    # The full ladder applies within a batch too, not just the exact rules.
    result = run(svc.deduplicate(None, [
        make_record(business_name="Moonlight Studio", phone="9000000001", city="Kochi"),
        make_record(business_name="Moonlight Studio", phone="9000000002", city="Kochi"),
    ]))
    assert len(result.new_leads) == 1 and len(result.duplicates) == 1
    assert result.duplicates[0].match.rule == RULE_NAME_CITY
    print("    name+city reconciles within a batch as well ...................... PASS")

    # Genuinely distinct records stay distinct.
    result = run(svc.deduplicate(None, [
        make_record(business_name="Alpha Photography", phone="9000000001", city="Kochi"),
        make_record(business_name="Beta Photography", phone="9000000002", city="Kochi"),
    ]))
    assert len(result.new_leads) == 2, result.summary()
    print("    two different businesses remain two new leads .................... PASS")

    # A stored match takes precedence over a batch match: the record should be reported
    # against the real lead id, not against its neighbour in the batch.
    stored = make_lead(business_name="Sunrise Photography", phone="9876543210")
    result = run(service([stored]).deduplicate(None, [
        make_record(business_name="Sunrise Photography", phone="9876543210"),
        make_record(business_name="Sunrise Photography", phone="9876543210"),
    ]))
    assert len(result.new_leads) == 0, result.summary()
    assert all(d.match.lead_id == stored.id for d in result.duplicates)
    print("    a stored lead outranks a batch neighbour ......................... PASS")


# ===========================================================================================
# 10. No database writes, no UI changes
# ===========================================================================================

def test_no_writes_and_no_ui():
    print("\n[10] No database writes and no UI changes")

    source = open(module.__file__).read()
    tree = ast.parse(source)

    # The service returns a plan; persistence belongs to the caller.
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("commit", "flush", "add", "delete", "refresh"):
        assert forbidden not in called, f"service calls session.{forbidden}()"
    print("    module performs no commit/flush/add/delete/refresh ............... PASS")

    assert "db.add" not in source and "db.commit" not in source
    print("    no direct session mutation in the source ......................... PASS")

    # The feature is backend-only: nothing under src/ may reference it.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    frontend = os.path.join(root, "src")
    hits = []
    if os.path.isdir(frontend):
        found = subprocess.run(
            ["grep", "-rIl", "-e", "lead_deduplication", "-e", "LeadDeduplicationService",
             frontend],
            capture_output=True, text=True,
        )
        hits = [line for line in found.stdout.splitlines() if line.strip()]
    assert not hits, f"frontend references the service: {hits}"
    print("    no frontend file references the service .......................... PASS")


# ===========================================================================================
# Runner
# ===========================================================================================

def test_lead_deduplication_suite() -> None:
    print("=" * 78)
    print("LEAD DEDUPLICATION SERVICE — UNIT SUITE")
    print("=" * 78)

    test_rule_phone()
    test_rule_website()
    test_rule_email()
    test_rule_coordinates()
    test_rule_name_and_city()
    test_rule_priority()
    test_merge_never_overwrites()
    test_return_shape()
    test_within_batch()
    test_no_writes_and_no_ui()

    print("\n" + "=" * 78)
    print("ALL 10 SECTIONS PASSED")
    print("=" * 78)
    print("\nNo database was touched and no migration is required: the service is pure,")
    print("and the repository was replaced by an in-memory fake throughout.")


if __name__ == "__main__":
    test_lead_deduplication_suite()
