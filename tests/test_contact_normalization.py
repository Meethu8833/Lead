"""
tests/test_contact_normalization.py

Unit test suite for `ContactNormalizationService` — the canonical-form layer for a lead's
phone numbers, email addresses, Instagram URLs, Facebook URLs and websites.

Verifies, section by section, the requirements the feature was specified against:

1.  Phone normalisation — the three forms named in the brief ("9876543210",
    "+91 9876543210", "00919876543210") all render as "+919876543210", plus the trunk-zero,
    country-code-leading and separator variants the CRM's sources actually produce.
2.  Phone rejection — years, prices, repeated digits, fragments and over-length values are
    declined rather than guessed at, because a wrong phone number is worse than a missing
    one in a CRM that deduplicates on it.
3.  Email normalisation — "Info@ABC.com" renders as "info@abc.com", with `mailto:` schemes
    and subject parameters stripped; malformed addresses are declined.
4.  Instagram URLs — handles, @-handles and profile URLs all render as one canonical URL;
    posts, reels and platform furniture are declined.
5.  Facebook URLs — mobile, regional, short and legacy-page hosts all collapse to one
    canonical page URL; share buttons and dialogs are declined.
6.  Website URLs — scheme added, `www.` and trailing slash removed, http upgraded to https,
    tracking parameters dropped; social profiles are not websites.
7.  **Duplicate removal** — the brief's headline requirement. Verified on each field
    independently and across mixed spellings, with first-seen ordering preserved so the
    provider's primary contact stays the headline value.
8.  Whole-record normalisation — `normalize_lead` canonicalises a `NormalizedLead` without
    mutating the input and without discarding fields it does not recognise.
9.  **No database changes** — asserted structurally: the module imports no model, no
    repository and no session, and holds no `commit`.
10. Coexistence with the comparison-key layer — `canonical_phone` and `normalize_phone`
    deliberately disagree, and the dedup key that `LeadRepository.find_duplicates` mirrors
    in SQL is proven unchanged by this feature.

This is a **pure unit suite**: no session, no network, no fixtures and no cleanup block. It
is safe to run anywhere with no `.env`, no Postgres and no credential.

Run:  python tests/test_contact_normalization.py
"""

import ast
import inspect
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import contact_normalization as module
from app.services.contact_normalization import (
    ContactNormalizationService,
    NormalizedContacts,
    canonical_email,
    canonical_facebook,
    canonical_instagram,
    canonical_instagram_handle,
    canonical_phone,
    canonical_website,
)
from app.services.lead_providers.normalized import NormalizedLead, normalize_phone


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


SERVICE = ContactNormalizationService()


# ===========================================================================================
# 1. Phone normalisation
# ===========================================================================================

def test_phone_normalisation() -> None:
    print("\n[1] Phone numbers render in E.164")

    # The three forms named explicitly in the brief.
    brief_cases = ["9876543210", "+91 9876543210", "00919876543210"]
    for raw in brief_cases:
        got = SERVICE.phone(raw)
        check(got == "+919876543210",
              f"canonical_phone({raw!r}) = {got!r}, want '+919876543210'")
    print("  ✓ 9876543210 / +91 9876543210 / 00919876543210 -> +919876543210")

    # The variants the CRM's own sources produce alongside them.
    variants = {
        "+919876543210": "+919876543210",      # already canonical
        "09876543210": "+919876543210",        # national trunk prefix
        "919876543210": "+919876543210",       # bare, country code leading
        "98765 43210": "+919876543210",        # spaced
        "+91-98765-43210": "+919876543210",    # hyphenated
        "(0495) 276-1234": "+914952761234",    # parenthesised STD code
        "+91 98765 43210 ext 12": "+919876543210",   # trailing extension
        "  +91 9876543210  ": "+919876543210",  # surrounding whitespace
    }
    for raw, expected in variants.items():
        got = SERVICE.phone(raw)
        check(got == expected, f"canonical_phone({raw!r}) = {got!r}, want {expected!r}")
    print("  ✓ trunk zero, bare country code, separators and extensions all canonicalise")

    # A non-default country code must survive rather than being re-coded to +91.
    check(canonical_phone("+1 415 555 2671") == "+14155552671",
          "An explicit +1 number must keep its own country code.")
    check(canonical_phone("+44 20 7946 0958") == "+442079460958",
          "An explicit +44 number must keep its own country code.")
    print("  ✓ explicitly international numbers keep their own country code")

    # The default is configurable, so the module is not silently India-only.
    us = ContactNormalizationService(default_country_code="1")
    check(us.phone("4155552671") == "+14155552671",
          f"A US-configured service should apply +1, got {us.phone('4155552671')!r}")
    check(us.phone("+91 9876543210") == "+919876543210",
          "An explicit country code must override the service default.")
    print("  ✓ default_country_code is configurable and never overrides an explicit code")


# ===========================================================================================
# 2. Phone rejection
# ===========================================================================================

def test_phone_rejection() -> None:
    print("\n[2] Implausible numbers are declined, not guessed at")

    rejected = {
        None: "None input",
        "": "empty string",
        "   ": "whitespace only",
        "2014": "a year",
        "25000": "a price",
        "1234567890": "a sequential placeholder",
        "0000000000": "an all-zero placeholder",
        "9999999999": "a repeated-digit placeholder",
        "+91 1111111111": "a repeated-digit placeholder with a country code",
        "12345678901234567890": "an over-length value",
        "abcdefgh": "a value with no digits",
        "560001": "a pincode",
    }
    for raw, description in rejected.items():
        got = SERVICE.phone(raw)
        check(got is None, f"canonical_phone({raw!r}) should decline {description}, got {got!r}")
    print(f"  ✓ {len(rejected)} implausible inputs all declined (years, prices, placeholders)")

    check(SERVICE.phone("+919876543210") is not None,
          "Rejection must not be so aggressive that a real number is lost.")
    print("  ✓ a real number is still accepted alongside the rejections")


# ===========================================================================================
# 3. Email normalisation
# ===========================================================================================

def test_email_normalisation() -> None:
    print("\n[3] Emails render lowercased and trimmed")

    # The case named explicitly in the brief.
    check(SERVICE.email("Info@ABC.com") == "info@abc.com",
          f"canonical_email('Info@ABC.com') = {SERVICE.email('Info@ABC.com')!r}")
    print("  ✓ Info@ABC.com -> info@abc.com")

    cases = {
        "  INFO@ABC.COM  ": "info@abc.com",
        "Info@ABC.com": "info@abc.com",
        "mailto:Info@ABC.com": "info@abc.com",
        "mailto:Info@ABC.com?subject=Enquiry&body=Hi": "info@abc.com",
        "<hello@sunrisestudio.in>": "hello@sunrisestudio.in",
        "Bookings@Sunrise-Studio.co.in": "bookings@sunrise-studio.co.in",
    }
    for raw, expected in cases.items():
        got = canonical_email(raw)
        check(got == expected, f"canonical_email({raw!r}) = {got!r}, want {expected!r}")
    print("  ✓ mailto: schemes, subject parameters and angle brackets are stripped")

    for raw in [None, "", "   ", "not-an-email", "@abc.com", "info@", "info@abc"]:
        check(canonical_email(raw) is None,
              f"canonical_email({raw!r}) should decline a malformed address.")
    print("  ✓ malformed addresses are declined")


# ===========================================================================================
# 4. Instagram URLs
# ===========================================================================================

def test_instagram_normalisation() -> None:
    print("\n[4] Instagram references render as one canonical profile URL")

    accepted = {
        "@studio_x": "https://instagram.com/studio_x",
        "studio_x": "https://instagram.com/studio_x",
        "instagram.com/studio_x": "https://instagram.com/studio_x",
        "instagram.com/studio_x/": "https://instagram.com/studio_x",
        "https://www.instagram.com/studio_x": "https://instagram.com/studio_x",
        "https://www.instagram.com/studio_x/?igshid=abc123": "https://instagram.com/studio_x",
        "http://instagram.com/Studio_X/": "https://instagram.com/studio_x",
        "https://m.instagram.com/studio_x/": "https://instagram.com/studio_x",
    }
    for raw, expected in accepted.items():
        got = canonical_instagram(raw)
        check(got == expected, f"canonical_instagram({raw!r}) = {got!r}, want {expected!r}")
    print("  ✓ handles, @-handles, bare and full URLs all collapse to one value")
    print("  ✓ www./m. hosts, http, trailing slash and ?igshid tracking are all normalised")

    check(canonical_instagram_handle("https://www.instagram.com/Studio_X/") == "studio_x",
          "The bare handle form must be available for the CRM's `instagram` column.")
    print("  ✓ the bare handle is exposed separately for the CRM column")

    declined = {
        "https://instagram.com/p/Cxyz123": "a post",
        "https://instagram.com/reel/Cxyz123": "a reel",
        "https://www.instagram.com/explore/tags/wedding/": "an explore page",
        "https://instagram.com/accounts/login/": "a login page",
        "not a handle!": "an illegal username",
        "": "empty input",
        None: "None input",
    }
    for raw, description in declined.items():
        got = canonical_instagram(raw)
        check(got is None, f"canonical_instagram({raw!r}) should decline {description}, got {got!r}")
    print("  ✓ posts, reels and platform furniture are declined, never stored as a profile")


# ===========================================================================================
# 5. Facebook URLs
# ===========================================================================================

def test_facebook_normalisation() -> None:
    print("\n[5] Facebook references render as one canonical page URL")

    accepted = {
        "facebook.com/StudioX": "https://facebook.com/StudioX",
        "facebook.com/StudioX/": "https://facebook.com/StudioX",
        "https://www.facebook.com/StudioX": "https://facebook.com/StudioX",
        "https://m.facebook.com/StudioX?ref=page_internal": "https://facebook.com/StudioX",
        "https://en-gb.facebook.com/StudioX/": "https://facebook.com/StudioX",
        "http://fb.me/StudioX": "https://facebook.com/StudioX",
        "https://fb.com/StudioX": "https://facebook.com/StudioX",
        "https://www.facebook.com/StudioX?mibextid=abc": "https://facebook.com/StudioX",
    }
    for raw, expected in accepted.items():
        got = canonical_facebook(raw)
        check(got == expected, f"canonical_facebook({raw!r}) = {got!r}, want {expected!r}")
    print("  ✓ www./m./regional/fb.me/fb.com hosts all collapse to facebook.com")
    print("  ✓ ?ref and ?mibextid tracking parameters are dropped")

    # Numeric-id profiles carry their identity in the query string, so it must survive.
    check(canonical_facebook("https://facebook.com/profile.php?id=100091234567")
          == "https://facebook.com/profile.php?id=100091234567",
          "A numeric profile id must survive tracking-parameter stripping.")
    check(canonical_facebook("https://www.facebook.com/pages/Studio-X/98765432")
          == "https://facebook.com/profile.php?id=98765432",
          "A legacy /pages/ URL must collapse onto its numeric identity.")
    print("  ✓ profile.php?id= and legacy /pages/ URLs keep their numeric identity")

    declined = {
        "https://www.facebook.com/sharer/sharer.php?u=https://x.in": "a share button",
        "https://www.facebook.com/dialog/share?href=x": "a share dialog",
        "https://www.facebook.com/plugins/like.php": "a plugin iframe",
        "https://www.facebook.com/login.php": "a login page",
        "StudioX": "a bare slug with no host",
        "": "empty input",
        None: "None input",
    }
    for raw, description in declined.items():
        got = canonical_facebook(raw)
        check(got is None, f"canonical_facebook({raw!r}) should decline {description}, got {got!r}")
    print("  ✓ share buttons, dialogs, plugins and bare slugs are declined")


# ===========================================================================================
# 6. Website URLs
# ===========================================================================================

def test_website_normalisation() -> None:
    print("\n[6] Websites render with https, no www. and no trailing slash")

    accepted = {
        "sunrisestudio.in": "https://sunrisestudio.in",
        "www.sunrisestudio.in": "https://sunrisestudio.in",
        "http://sunrisestudio.in": "https://sunrisestudio.in",
        "http://WWW.SunriseStudio.in/": "https://sunrisestudio.in",
        "https://sunrisestudio.in/": "https://sunrisestudio.in",
        "https://sunrisestudio.in/index.html": "https://sunrisestudio.in",
        "https://sunrisestudio.in/home?utm_source=google#top": "https://sunrisestudio.in/home",
        "https://sunrisestudio.in/photography/": "https://sunrisestudio.in/photography",
        "  sunrisestudio.in  ": "https://sunrisestudio.in",
    }
    for raw, expected in accepted.items():
        got = canonical_website(raw)
        check(got == expected, f"canonical_website({raw!r}) = {got!r}, want {expected!r}")
    print("  ✓ scheme added, host lowercased, www./trailing slash/index.html removed")
    print("  ✓ http upgraded to https and utm_* tracking dropped, so one site is one value")

    # A meaningful query parameter is not tracking and must survive.
    check(canonical_website("https://studio.in/gallery?album=weddings")
          == "https://studio.in/gallery?album=weddings",
          "A meaningful query parameter must not be stripped with the tracking ones.")
    print("  ✓ meaningful query parameters survive")

    declined = {
        "https://facebook.com/StudioX": "a Facebook page",
        "https://instagram.com/studio_x": "an Instagram profile",
        "https://wa.me/919876543210": "a WhatsApp link",
        "https://linktr.ee/studiox": "a link aggregator",
        "not a url": "unparseable input",
        "ftp://files.studio.in": "a non-http scheme",
        "": "empty input",
        None: "None input",
    }
    for raw, description in declined.items():
        got = canonical_website(raw)
        check(got is None, f"canonical_website({raw!r}) should decline {description}, got {got!r}")
    print("  ✓ social profiles are not websites and are declined")


# ===========================================================================================
# 7. Duplicate removal
# ===========================================================================================

def test_duplicate_removal() -> None:
    print("\n[7] Duplicates are removed on the canonical form")

    # The brief's own example: three spellings of one number, two of one address.
    contacts = SERVICE.normalize_contacts(
        phones=["9876543210", "+91 9876543210", "00919876543210"],
        emails=["Info@ABC.com", "info@abc.com", "  INFO@ABC.COM  "],
    )
    check(contacts.phones == ["+919876543210"],
          f"Three spellings of one number must collapse to one, got {contacts.phones!r}")
    check(contacts.emails == ["info@abc.com"],
          f"Three spellings of one address must collapse to one, got {contacts.emails!r}")
    print("  ✓ 3 phone spellings -> 1 number;  3 email spellings -> 1 address")

    contacts = SERVICE.normalize_contacts(
        instagram_urls=[
            "@studio_x",
            "https://www.instagram.com/studio_x/",
            "instagram.com/studio_x?igshid=zz",
            "https://instagram.com/other_studio",
        ],
        facebook_urls=[
            "facebook.com/StudioX",
            "https://m.facebook.com/StudioX/",
            "https://fb.me/StudioX",
        ],
        websites=[
            "sunrisestudio.in",
            "https://www.sunrisestudio.in/",
            "http://sunrisestudio.in",
        ],
    )
    check(contacts.instagram_urls == ["https://instagram.com/studio_x",
                                      "https://instagram.com/other_studio"],
          f"Instagram dedup failed: {contacts.instagram_urls!r}")
    check(contacts.facebook_urls == ["https://facebook.com/StudioX"],
          f"Facebook dedup failed: {contacts.facebook_urls!r}")
    check(contacts.websites == ["https://sunrisestudio.in"],
          f"Website dedup failed: {contacts.websites!r}")
    print("  ✓ 4 Instagram spellings -> 2 distinct profiles (the distinct one survives)")
    print("  ✓ 3 Facebook spellings -> 1 page;  3 website spellings -> 1 site")

    # Ordering is load-bearing: LeadImportService promotes phones[0] to the CRM's `phone`.
    ordered = SERVICE.normalize_contacts(
        phones=["+91 98765 43210", "0495 276 1234", "9876543210"],
    )
    check(ordered.phones == ["+919876543210", "+914952761234"],
          f"First-seen ordering must be preserved, got {ordered.phones!r}")
    print("  ✓ first-seen ordering preserved: the provider's primary number stays first")

    # Unusable values are reported rather than silently vanishing.
    reported = SERVICE.normalize_contacts(phones=["9876543210", "2014"], emails=["nope"])
    check(reported.phones == ["+919876543210"], "The usable number must survive.")
    check("2014" in reported.dropped and "nope" in reported.dropped,
          f"Unusable values must be reported in `dropped`, got {reported.dropped!r}")
    print("  ✓ values that cannot be canonicalised are reported in `dropped`, not hidden")

    # None entries and empty input must not blow up a batch.
    empty = SERVICE.normalize_contacts(phones=[None, "", "  "], emails=None)
    check(empty.is_empty, "An all-empty contact set should report itself empty.")
    check(isinstance(empty, NormalizedContacts), "normalize_contacts returns NormalizedContacts")
    print("  ✓ None entries and empty input are handled without raising")


# ===========================================================================================
# 8. Whole-record normalisation
# ===========================================================================================

def test_normalize_lead() -> None:
    print("\n[8] A whole provider record normalises without mutation")

    lead = NormalizedLead(
        business_name="Sunrise Studio",
        city="Kozhikode",
        phone_numbers=["9876543210", "+91 9876543210", "0495 276 1234"],
        emails=["Info@ABC.com", "info@abc.com"],
        facebook="https://m.facebook.com/SunriseStudio?ref=page_internal",
        instagram="https://www.instagram.com/sunrisestudio/?igshid=abc",
        website="http://WWW.SunriseStudio.in/",
        source="test",
        rating=4.6,
    )
    original_phones = list(lead.phone_numbers)

    result = SERVICE.normalize_lead(lead)

    check(result.phone_numbers == ["+919876543210", "+914952761234"],
          f"Lead phones not canonicalised/deduped: {result.phone_numbers!r}")
    check(result.emails == ["info@abc.com"],
          f"Lead emails not canonicalised/deduped: {result.emails!r}")
    check(result.facebook == "https://facebook.com/SunriseStudio",
          f"Lead facebook not canonicalised: {result.facebook!r}")
    check(result.instagram == "https://instagram.com/sunrisestudio",
          f"Lead instagram not canonicalised: {result.instagram!r}")
    check(result.website == "https://sunrisestudio.in",
          f"Lead website not canonicalised: {result.website!r}")
    print("  ✓ phones, emails, instagram, facebook and website all canonicalised")

    check(lead.phone_numbers == original_phones,
          "normalize_lead must not mutate its input — providers may still hold a reference.")
    print("  ✓ the input lead is not mutated")

    check(result.business_name == "Sunrise Studio" and result.city == "Kozhikode",
          "Unrelated fields must survive the round trip.")
    check(result.rating == 4.6 and result.source == "test",
          "Rating and source must survive the round trip.")
    print("  ✓ every other field survives the round trip")

    # A value these rules do not recognise must be preserved, not deleted.
    odd = NormalizedLead(business_name="X", city="Y", website="mailto:x@y.in", source="t")
    check(SERVICE.normalize_lead(odd).website == "mailto:x@y.in",
          "An unrecognised value must be preserved, not blanked.")
    print("  ✓ unrecognised values are preserved rather than deleted")


# ===========================================================================================
# 9. No database changes
# ===========================================================================================

def test_no_database_changes() -> None:
    print("\n[9] The feature makes no database changes")

    # Docstrings and comments are stripped first: this module documents at length *why* it
    # has no session and no commit, and a raw substring scan would match that prose rather
    # than any actual code. `ast.unparse` of the module with docstrings removed leaves only
    # real statements to scan.
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    source = ast.unparse(tree)

    forbidden = [
        ("from app.models", "an ORM model import"),
        ("from app.repositories", "a repository import"),
        ("AsyncSession", "a database session"),
        ("db.commit", "a commit"),
        ("db.add", "a session write"),
        ("session.", "a session call"),
        ("sqlalchemy", "a SQLAlchemy import"),
    ]
    for needle, description in forbidden:
        check(needle not in source,
              f"contact_normalization.py must not contain {description} ({needle!r})")
    print("  ✓ no model import, no repository, no session, no commit, no SQLAlchemy")

    for name in ("phone", "email", "instagram", "facebook", "website",
                 "normalize_contacts", "normalize_lead"):
        signature = inspect.signature(getattr(ContactNormalizationService, name))
        check("db" not in signature.parameters,
              f"{name}() must not accept a database session")
    print("  ✓ no public method accepts a database session")

    check(SERVICE.describe()["writes_to_database"] is False,
          "describe() must report that the service does not write to the database.")
    print("  ✓ the service is pure: strings in, strings out, nothing persisted")


# ===========================================================================================
# 10. Coexistence with the comparison-key layer
# ===========================================================================================

def test_coexistence_with_dedup_keys() -> None:
    print("\n[10] The existing deduplication keys are unchanged")

    # `normalize_phone` computes the MATCH KEY (last 10 digits, country code discarded).
    # `canonical_phone` computes the STORAGE FORM (E.164). They must stay different: the
    # match key is mirrored in SQL by `LeadRepository.find_duplicates` and compared against
    # numbers already stored in the `leads` table.
    for raw in ("9876543210", "+91 9876543210", "00919876543210", "+919876543210"):
        check(normalize_phone(raw) == "9876543210",
              f"normalize_phone({raw!r}) = {normalize_phone(raw)!r}; the SQL-mirrored "
              f"dedup key must remain the last 10 digits.")
    print("  ✓ normalize_phone still returns the 10-digit match key for all four forms")

    check(canonical_phone("9876543210") != normalize_phone("9876543210"),
          "The canonical form and the match key are different by design.")
    print("  ✓ canonical form (+919876543210) and match key (9876543210) stay distinct")

    # Critically: canonicalising first must not break matching afterwards. A lead stored as
    # "9876543210" and re-scraped as "+919876543210" must still be recognised as one lead.
    check(normalize_phone(canonical_phone("9876543210")) == normalize_phone("9876543210"),
          "Canonicalising a number must not change the match key it yields.")
    print("  ✓ canonicalising first leaves the match key identical: dedup still works")

    # The same must hold for email, where the two layers legitimately agree.
    from app.services.lead_providers.normalized import normalize_email
    check(canonical_email("Info@ABC.com") == normalize_email("Info@ABC.com"),
          "Canonical email and the email match key are the same value by design.")
    print("  ✓ canonical email and the email match key agree, as intended")


# ===========================================================================================
# Runner
# ===========================================================================================

def test_contact_normalization_suite() -> None:
    print("=" * 78)
    print("CONTACT NORMALIZATION SERVICE — UNIT SUITE")
    print("=" * 78)

    test_phone_normalisation()
    test_phone_rejection()
    test_email_normalisation()
    test_instagram_normalisation()
    test_facebook_normalisation()
    test_website_normalisation()
    test_duplicate_removal()
    test_normalize_lead()
    test_no_database_changes()
    test_coexistence_with_dedup_keys()

    print("\n" + "=" * 78)
    print("ALL 10 SECTIONS PASSED")
    print("=" * 78)
    print("\nNo database was touched and no migration is required: the service is pure,")
    print("and the existing dedup keys mirrored in SQL are provably unchanged.")


if __name__ == "__main__":
    test_contact_normalization_suite()
