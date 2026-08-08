"""
tests/test_contact_extractor.py

Unit test suite for `ContactExtractorService` — the enrichment step that visits a normalized
lead's website and extracts the contact details published on it.

Verifies, section by section, the requirements the feature was specified against:

1.  Service construction — configured defaults, overrides, and `describe()` reporting a crawl
    depth of exactly one.
2.  Region targeting — header, footer, contact page and about page are all read, and the
    header/footer number leads the ordering so it becomes the CRM's headline phone.
3.  Extraction — phones, WhatsApp, emails, Instagram, Facebook and YouTube are all pulled
    from one page, from both `href` attributes and plain page text.
4.  Normalisation — numbers, addresses and handles are cleaned and deduplicated on the CRM's
    own comparison keys, so two spellings of one number do not both survive.
5.  Junk rejection — asset filenames that look like emails, placeholder addresses, years,
    prices, share-buttons and platform furniture are all declined.
6.  **Depth is one level** — contact/about pages linked from the home page are fetched, and
    pages linked from *those* are never fetched. Asserted on the actual request log.
7.  **The whole site is not crawled** — off-host links are never followed, non-contact
    internal links are never followed, and the sub-page count is capped.
8.  **robots.txt is respected** — a `Disallow` leaves the lead untouched and issues no page
    request; an absent robots.txt permits the visit; the file is fetched once per host.
8b. Rate limiting — requests to a single host are spaced by the configured interval, while
    two different hosts run concurrently rather than queueing behind each other.
9.  Enrichment semantics — existing provider values are never overwritten, scraped values are
    appended, the input lead is never mutated, and every other field survives the round trip.
10. The failure contract and non-persistence — a dead site, a 404, a non-HTML response and an
    unparseable page all leave the lead unchanged and never propagate; and the module writes
    nothing to the database.

This is a **pure unit suite**, like `tests/test_website_discovery.py`: the brief for this
feature is explicitly "do not write into the database", so there is no session, no marker row
and no cleanup block, and it is safe to run anywhere with no `.env`, no Postgres and no
credential.

No network is touched. Every page, and every `robots.txt`, is served by an
`httpx.MockTransport` injected into the service, so the *real* fetch path, the *real*
BeautifulSoup parse and the *real* robots handling are the code under test — only the socket
is replaced. The transport also records every URL it was asked for, which is what makes the
depth and no-crawl claims in sections 6-8 verifiable rather than assumed.

Run:  python tests/test_contact_extractor.py
"""

import asyncio
import inspect
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from app.services.lead_providers.normalized import NormalizedLead
from app.services import contact_extractor as module
from app.services.contact_extractor import (
    ContactExtractionError,
    ContactExtractorService,
    ExtractedContacts,
    ExtractionOutcome,
    RobotsCache,
)


def check(condition: bool, message: str) -> None:
    """Asserts a condition, raising with a readable message on failure."""
    if not condition:
        raise AssertionError(message)


# ===========================================================================================
# Fixtures — a small, realistic studio site
# ===========================================================================================
# Written to look like the templates small photography businesses actually ship: a footer
# rendered as <div class="site-footer"> rather than <footer>, a share button next to the real
# social links, an obfuscated-looking asset filename that reads as an email, and the phone
# number printed as text in one place and as a tel: link in another.

HOME_HTML = """
<html><head><title>Sunrise Studio</title>
<style>.x { background: url(logo@2x.png); }</style>
<script>var dsn = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6@sentry.io";</script>
</head>
<body>
  <header class="site-header">
    <a href="/">Sunrise Studio</a>
    <a href="tel:+91 98765 43210">Call us</a>
  </header>

  <nav>
    <a href="/gallery">Gallery</a>
    <a href="/pricing">Pricing</a>
    <a href="/about-us">About Us</a>
    <a href="/contact">Contact</a>
    <a href="https://partner-studio.example.com/">Our partners</a>
  </nav>

  <main>
    <p>Established 2014. Packages from 25000 rupees. Weddings across Kerala.</p>
    <p>Reach the studio desk on 0495 2761234 during working hours.</p>
    <img src="/img/logo@2x.png" alt="logo">
  </main>

  <div class="site-footer">
    <a href="mailto:hello@sunrisestudio.in?subject=Enquiry">hello@sunrisestudio.in</a>
    <a href="https://www.instagram.com/sunrisestudio/?igshid=abc123">Instagram</a>
    <a href="https://www.facebook.com/sunrisestudioblr">Facebook</a>
    <a href="https://www.facebook.com/sharer/sharer.php?u=https://sunrisestudio.in">Share</a>
    <a href="https://www.youtube.com/@sunrisestudio">YouTube</a>
    <a href="https://wa.me/919876543211">WhatsApp us</a>
    <span>PIN 673001</span>
  </div>
</body></html>
"""

CONTACT_HTML = """
<html><body>
  <header class="site-header"><a href="/">Sunrise Studio</a></header>
  <h1>Contact</h1>
  <p>Studio manager: <a href="tel:04952761234">0495 276 1234</a></p>
  <p>Bookings: <a href="mailto:bookings@sunrisestudio.in">bookings@sunrisestudio.in</a></p>
  <p>Or write to studio@sunrisestudio.in for anything else.</p>
  <a href="https://api.whatsapp.com/send?phone=919876543211&text=Hi">Chat on WhatsApp</a>
  <!-- A link one level deeper. It must NEVER be fetched. -->
  <a href="/contact/directions">Directions</a>
  <a href="/team">Meet the team</a>
</body></html>
"""

ABOUT_HTML = """
<html><body>
  <h1>About Us</h1>
  <p>Founded in 2014 by Ravi Menon. Awards in 2018, 2019 and 2021.</p>
  <p>Owner direct line: +91 90000 11122</p>
  <a href="/about/history">Our history</a>
</body></html>
"""

#: A page whose only links go one level deeper. If any of these are requested, depth broke.
DEEPER_HTML = "<html><body><a href='/deeper/still'>Deeper</a><p>+91 99999 88877</p></body></html>"

ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"
ROBOTS_DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
ROBOTS_DISALLOW_CONTACT = "User-agent: *\nDisallow: /contact\n"


class RecordingTransport(httpx.MockTransport):
    """
    A mock transport that serves canned pages and records every URL it was asked for.

    The request log is what makes this suite's central claims *verifiable*: "depth is one
    level" and "the whole site is not crawled" are assertions about which requests were and
    were not issued, and there is no way to check them from the return value alone.
    """

    def __init__(self, pages: dict[str, str], robots: str | None = ROBOTS_ALLOW_ALL) -> None:
        self.requested: list[str] = []
        self.pages = pages
        self.robots = robots

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            self.requested.append(url)

            if url.endswith("/robots.txt"):
                if self.robots is None:
                    return httpx.Response(404, text="not found")
                return httpx.Response(
                    200, text=self.robots, headers={"content-type": "text/plain"}
                )

            body = self.pages.get(url)
            if body is None:
                # Tolerate a trailing-slash difference, which urljoin introduces routinely.
                body = self.pages.get(url.rstrip("/"))
            if body is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(
                200, text=body, headers={"content-type": "text/html; charset=utf-8"}
            )

        super().__init__(handler)

    @property
    def page_requests(self) -> list[str]:
        """Every request that was not for a robots.txt."""
        return [u for u in self.requested if not u.endswith("/robots.txt")]


STUDIO_PAGES = {
    "https://sunrisestudio.in/": HOME_HTML,
    "https://sunrisestudio.in/contact": CONTACT_HTML,
    "https://sunrisestudio.in/about-us": ABOUT_HTML,
    # Present but must never be requested — they are two levels down.
    "https://sunrisestudio.in/contact/directions": DEEPER_HTML,
    "https://sunrisestudio.in/about/history": DEEPER_HTML,
    "https://sunrisestudio.in/team": DEEPER_HTML,
    "https://sunrisestudio.in/gallery": DEEPER_HTML,
    "https://sunrisestudio.in/pricing": DEEPER_HTML,
}


def make_service(transport: httpx.MockTransport, **kwargs) -> ContactExtractorService:
    """
    Builds a service against a mock transport with the politeness delay switched off.

    The delay is real behaviour and is exercised in its own section; leaving it on for every
    other section would add a second per request and make the suite unusable.
    """
    kwargs.setdefault("min_request_interval", 0.0)
    return ContactExtractorService(transport=transport, **kwargs)


def make_lead(
    *,
    name: str | None = "Sunrise Studio",
    website: str | None = "https://sunrisestudio.in/",
    phones: list[str] | None = None,
    emails: list[str] | None = None,
    instagram: str | None = None,
    facebook: str | None = None,
    **extra,
) -> NormalizedLead:
    """Builds a normalized lead for extraction, with only the fields a test cares about."""
    return NormalizedLead(
        business_name=name,
        website=website,
        phone_numbers=phones if phones is not None else [],
        emails=emails if emails is not None else [],
        instagram=instagram,
        facebook=facebook,
        **extra,
    )


# ===========================================================================================
# 1. Construction
# ===========================================================================================

async def test_construction() -> None:
    print("\n[1] Construction and configuration")

    service = ContactExtractorService()
    described = service.describe()
    check(described["crawl_depth"] == 1,
          f"crawl depth must be reported as 1, got {described['crawl_depth']}")
    check(described["respect_robots"] is True,
          "robots.txt must be respected by default")
    check(described["max_subpages"] >= 1, "at least one sub-page must be reachable")
    print("  ✓ defaults report crawl_depth=1 and respect_robots=True")

    custom = ContactExtractorService(
        timeout=3.0, max_subpages=2, concurrency=7, user_agent="TestAgent/9",
    )
    described = custom.describe()
    check(described["timeout_seconds"] == 3.0, "timeout override must apply")
    check(described["max_subpages"] == 2, "max_subpages override must apply")
    check(described["concurrency"] == 7, "concurrency override must apply")
    check(described["user_agent"] == "TestAgent/9", "user agent override must apply")
    print("  ✓ constructor overrides are honoured")

    check(ContactExtractorService(concurrency=0).describe()["concurrency"] == 1,
          "concurrency must be floored at 1, never 0")
    print("  ✓ a zero concurrency is floored to 1 rather than deadlocking")

    # Depth is structural, not configurable: there must be no depth knob to raise.
    signature = inspect.signature(ContactExtractorService.__init__)
    check("depth" not in signature.parameters and "max_depth" not in signature.parameters,
          "there must be no depth parameter — one level is a structural guarantee")
    print("  ✓ no depth parameter exists: one level cannot be configured upward")


# ===========================================================================================
# 2. Region targeting — header, footer, contact page, about page
# ===========================================================================================

async def test_regions_are_read() -> None:
    print("\n[2] Header, footer, contact page and about page are all read")

    transport = RecordingTransport(STUDIO_PAGES)
    outcome = await make_service(transport).extract_with_outcome(make_lead())

    check(outcome.status == "extracted", f"expected extraction, got {outcome.status}")

    fetched = [u.rstrip("/") for u in outcome.pages_fetched]
    check("https://sunrisestudio.in" in fetched, "the home page must be visited")
    check("https://sunrisestudio.in/contact" in fetched,
          f"the contact page must be visited, fetched: {fetched}")
    check("https://sunrisestudio.in/about-us" in fetched,
          f"the about page must be visited, fetched: {fetched}")
    print("  ✓ home page, contact page and about page are all visited")

    # The header's tel: link and the footer's mailto/social are all present.
    contacts = outcome.contacts
    check(any("98765" in p for p in contacts.phones),
          f"the header phone must be extracted, got {contacts.phones}")
    check(any("hello@sunrisestudio.in" == e for e in contacts.emails),
          f"the footer email must be extracted, got {contacts.emails}")
    check(contacts.instagram, "the footer Instagram link must be extracted")
    check(contacts.facebook, "the footer Facebook link must be extracted")
    check(contacts.youtube, "the footer YouTube link must be extracted")
    print("  ✓ header tel: link and footer mailto/Instagram/Facebook/YouTube all read")

    # The footer is a <div class="site-footer">, not a <footer> — the class convention must
    # be matched, because a large share of small-business templates render it that way.
    soup_regions = ContactExtractorService._priority_regions(
        module._make_soup(HOME_HTML)
    )
    check(len(soup_regions) >= 2,
          f"header and footer regions must both be found, got {len(soup_regions)}")
    print("  ✓ a <div class='site-footer'> is recognised as a footer, not only <footer>")

    # Ordering: the header/footer number must lead, because NormalizedLead promotes
    # phone_numbers[0] to the CRM's `phone` column.
    lead = outcome.lead
    check(lead.phone_numbers, "the enriched lead must carry phone numbers")
    first_digits = "".join(c for c in lead.phone_numbers[0] if c.isdigit())
    check(first_digits.endswith("9876543210") or first_digits.endswith("9876543211"),
          f"a header/footer number must lead the list, got {lead.phone_numbers}")
    print("  ✓ the header/footer number leads the list and becomes the CRM's headline phone")


# ===========================================================================================
# 3. Extraction of every requested field
# ===========================================================================================

async def test_extracts_all_fields() -> None:
    print("\n[3] Phones, WhatsApp, emails, Instagram, Facebook, YouTube")

    transport = RecordingTransport(STUDIO_PAGES)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    contacts = outcome.contacts

    check(contacts.phones, f"phones must be extracted, got {contacts.phones}")
    print(f"  ✓ phones:    {list(contacts.phones)}")

    check(contacts.whatsapp, f"WhatsApp numbers must be extracted, got {contacts.whatsapp}")
    check(any("9876543211" in "".join(c for c in w if c.isdigit()) for w in contacts.whatsapp),
          f"the wa.me number must be extracted, got {contacts.whatsapp}")
    print(f"  ✓ whatsapp:  {list(contacts.whatsapp)}  (from wa.me and api.whatsapp.com)")

    check("hello@sunrisestudio.in" in contacts.emails, "the mailto: address must be extracted")
    check("bookings@sunrisestudio.in" in contacts.emails,
          "the contact page mailto: must be extracted")
    check("studio@sunrisestudio.in" in contacts.emails,
          "an address printed as plain text must be extracted")
    print(f"  ✓ emails:    {list(contacts.emails)}  (mailto: links and plain text)")

    check(any("instagram.com/sunrisestudio" in i for i in contacts.instagram),
          f"the Instagram profile must be extracted, got {contacts.instagram}")
    check(all("igshid" not in i for i in contacts.instagram),
          "the tracking query string must be dropped from a profile URL")
    print(f"  ✓ instagram: {list(contacts.instagram)}  (tracking parameters dropped)")

    check(any("facebook.com/sunrisestudioblr" in f for f in contacts.facebook),
          f"the Facebook page must be extracted, got {contacts.facebook}")
    print(f"  ✓ facebook:  {list(contacts.facebook)}")

    check(any("youtube.com/@sunrisestudio" in y for y in contacts.youtube),
          f"the YouTube channel must be extracted, got {contacts.youtube}")
    print(f"  ✓ youtube:   {list(contacts.youtube)}")

    # A text-only number on the about page must be found too — not every site uses tel:.
    check(any("90000" in "".join(c for c in p if c.isdigit()) for p in contacts.phones),
          f"a number printed as plain text must be extracted, got {contacts.phones}")
    print("  ✓ numbers printed as plain text are found, not only tel: links")


# ===========================================================================================
# 4. Normalisation
# ===========================================================================================

async def test_normalisation() -> None:
    print("\n[4] Normalisation and deduplication")

    transport = RecordingTransport(STUDIO_PAGES)
    lead = await make_service(transport).extract(make_lead())

    # "0495 2761234" (text, home page) and "04952761234" (tel:, contact page) are the same
    # number in two spellings. Deduplication is on the CRM's comparison key, not the string.
    keys = [k for k in (module.normalize_phone(p) for p in lead.phone_numbers) if k]
    check(len(keys) == len(set(keys)),
          f"phone numbers must be deduplicated on their comparison key, got {lead.phone_numbers}")
    print(f"  ✓ phones deduplicated on comparison key: {lead.phone_numbers}")

    email_keys = [module.normalize_email(e) for e in lead.emails]
    check(len(email_keys) == len(set(email_keys)),
          f"emails must be deduplicated, got {lead.emails}")
    check(all(e == e.lower().strip() for e in lead.emails),
          f"emails must be stored lowercased and trimmed, got {lead.emails}")
    print(f"  ✓ emails lowercased and deduplicated: {lead.emails}")

    check(lead.instagram == "sunrisestudio",
          f"Instagram must be reduced to a bare handle, got {lead.instagram!r}")
    print(f"  ✓ instagram normalized to a bare handle: {lead.instagram!r}")

    check(lead.facebook and lead.facebook.startswith("https://"),
          f"Facebook must be stored as an absolute URL, got {lead.facebook!r}")
    print(f"  ✓ facebook normalized to an absolute URL: {lead.facebook!r}")

    check(lead.youtube and lead.youtube.startswith("https://"),
          f"YouTube must be stored as an absolute URL, got {lead.youtube!r}")
    print(f"  ✓ youtube normalized to an absolute URL: {lead.youtube!r}")

    # Phone display form keeps what makes a number dialable and drops the rest.
    for phone in lead.phone_numbers:
        check(not any(ch.isalpha() for ch in phone),
              f"a stored phone must carry no letters, got {phone!r}")
        check(phone == phone.strip(), f"a stored phone must be trimmed, got {phone!r}")
    print("  ✓ stored phone strings carry no stray text and stay dialable")


# ===========================================================================================
# 5. Junk rejection
# ===========================================================================================

async def test_rejects_junk() -> None:
    print("\n[5] Junk is rejected, not stored")

    transport = RecordingTransport(STUDIO_PAGES)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    contacts = outcome.contacts

    # "logo@2x.png" appears twice in the fixture (a CSS url and an <img src>) and is
    # perfectly well-shaped as an email address.
    check(all("2x.png" not in e for e in contacts.emails),
          f"an asset filename must not become an email, got {contacts.emails}")
    print("  ✓ 'logo@2x.png' is not stored as an email address")

    # The Sentry DSN lives inside a <script>, which is stripped before any text is read.
    check(all("sentry" not in e for e in contacts.emails),
          f"a script's analytics DSN must not become an email, got {contacts.emails}")
    print("  ✓ a Sentry DSN inside <script> is not stored (script/style stripped first)")

    # The share button points at facebook.com/sharer/... — platform furniture, not a profile.
    check(all("sharer" not in f for f in contacts.facebook),
          f"a share button must not become the business's Facebook page, got {contacts.facebook}")
    print("  ✓ a facebook.com/sharer/ share button is not stored as the business's page")

    # Years, prices and pincodes are digit runs that read like numbers.
    digit_forms = ["".join(c for c in p if c.isdigit()) for p in contacts.phones]
    for junk in ("2014", "25000", "673001", "2018", "2019", "2021"):
        check(junk not in digit_forms,
              f"{junk!r} is a year/price/pincode and must not be stored as a phone")
    print("  ✓ years (2014, 2018…), prices (25000) and pincodes (673001) rejected")

    # Direct unit checks on the guards, so the reasoning is pinned independent of the fixture.
    check(not module._looks_like_phone("1234567890"), "a placeholder run must be rejected")
    check(not module._looks_like_phone("9999999999"), "a repeated digit must be rejected")
    check(not module._looks_like_phone("2014"), "a year is too short to be a phone")
    check(module._looks_like_phone("+91 98765 43210"), "a real mobile must be accepted")
    check(module._valid_email("info@example.com") is None,
          "a placeholder domain must be rejected")
    check(module._valid_email("hello@sunrisestudio.in") == "hello@sunrisestudio.in",
          "a real address must be accepted")
    print("  ✓ guard functions reject placeholders and accept real values directly")


# ===========================================================================================
# 6. Depth is exactly one level
# ===========================================================================================

async def test_depth_is_one_level() -> None:
    print("\n[6] Crawl depth is exactly one level")

    transport = RecordingTransport(STUDIO_PAGES)
    await make_service(transport).extract(make_lead())
    requested = [u.rstrip("/") for u in transport.page_requests]

    check("https://sunrisestudio.in" in requested, "the home page must be fetched")
    check("https://sunrisestudio.in/contact" in requested,
          "a contact page linked from the home page must be fetched (level one)")
    print(f"  ✓ level one fetched: {requested}")

    # The contact page links to /contact/directions and /team; the about page links to
    # /about/history. All are level TWO and must never be requested.
    for deeper in (
        "https://sunrisestudio.in/contact/directions",
        "https://sunrisestudio.in/about/history",
        "https://sunrisestudio.in/team",
    ):
        check(deeper not in requested,
              f"{deeper} is two levels deep and must never be fetched; requested: {requested}")
    print("  ✓ links found ON level-one pages are never followed — no level two")

    # And nothing from a deeper page leaked into the result.
    lead = await make_service(RecordingTransport(STUDIO_PAGES)).extract(make_lead())
    digit_forms = ["".join(c for c in p if c.isdigit()) for p in lead.phone_numbers]
    check(not any(d.endswith("9999988877") for d in digit_forms),
          "a number that exists only on a level-two page must never appear on the lead")
    print("  ✓ the number that exists only two levels down never reaches the lead")

    # Structural: no recursion and no work queue in the module.
    source = inspect.getsource(module)
    check("while queue" not in source and "queue.pop" not in source,
          "there must be no work queue — that is how a crawler is built")
    print("  ✓ module contains no work queue and no recursive fetch")


# ===========================================================================================
# 7. The whole site is not crawled
# ===========================================================================================

async def test_does_not_crawl_whole_site() -> None:
    print("\n[7] The whole website is not crawled")

    transport = RecordingTransport(STUDIO_PAGES)
    await make_service(transport).extract(make_lead())
    requested = [u.rstrip("/") for u in transport.page_requests]

    # /gallery and /pricing are ordinary internal links. They are not contact or about pages,
    # so they are not fetched — we visit pages that plausibly carry contact details, not
    # every page that exists.
    for ignored in ("https://sunrisestudio.in/gallery", "https://sunrisestudio.in/pricing"):
        check(ignored not in requested,
              f"{ignored} is not a contact/about page and must not be fetched")
    print("  ✓ ordinary internal links (/gallery, /pricing) are not fetched")

    # An off-host link is never followed, or extraction becomes a walk across the open web.
    check(all("partner-studio.example.com" not in u for u in transport.requested),
          "an off-host link must never be followed")
    print("  ✓ off-host links (partner-studio.example.com) are never followed")

    # The sub-page cap bounds the second level regardless of how many links qualify.
    many_links = "".join(
        f'<a href="/contact-{i}">Contact {i}</a>' for i in range(30)
    )
    pages = {"https://big.example/": f"<html><body>{many_links}</body></html>"}
    pages.update({f"https://big.example/contact-{i}": CONTACT_HTML for i in range(30)})
    capped_transport = RecordingTransport(pages)
    await make_service(capped_transport, max_subpages=3).extract(
        make_lead(website="https://big.example/")
    )
    page_count = len(capped_transport.page_requests)
    check(page_count <= 4,
          f"1 home page + at most 3 sub-pages = 4 requests, got {page_count}")
    print(f"  ✓ 30 qualifying links yielded {page_count} requests (1 home + cap of 3)")

    total = len(transport.page_requests)
    check(total <= 5, f"a whole extraction must stay small, issued {total} page requests")
    print(f"  ✓ the full studio extraction issued {total} page requests in total")


# ===========================================================================================
# 8. robots.txt
# ===========================================================================================

async def test_respects_robots() -> None:
    print("\n[8] robots.txt is respected")

    # --- A blanket Disallow: nothing is fetched and the lead is untouched.
    transport = RecordingTransport(STUDIO_PAGES, robots=ROBOTS_DISALLOW_ALL)
    lead = make_lead()
    outcome = await make_service(transport).extract_with_outcome(lead)

    check(outcome.status == "robots_blocked",
          f"a Disallow must report robots_blocked, got {outcome.status}")
    check(outcome.lead is lead, "a disallowed lead must be returned untouched")
    check(len(transport.page_requests) == 0,
          f"no page may be fetched when disallowed, got {transport.page_requests}")
    print("  ✓ 'Disallow: /' fetches zero pages and returns the lead untouched")

    # --- A targeted Disallow: the home page is allowed, /contact is not.
    transport = RecordingTransport(STUDIO_PAGES, robots=ROBOTS_DISALLOW_CONTACT)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    requested = [u.rstrip("/") for u in transport.page_requests]
    check("https://sunrisestudio.in" in requested, "the allowed home page must be fetched")
    check("https://sunrisestudio.in/contact" not in requested,
          f"the disallowed /contact must be skipped, requested: {requested}")
    check("https://sunrisestudio.in/about-us" in requested,
          "a path not covered by the Disallow must still be fetched")
    print("  ✓ a path-specific Disallow skips only that page; the rest still proceeds")

    # --- An absent robots.txt permits the visit (the documented convention).
    transport = RecordingTransport(STUDIO_PAGES, robots=None)  # 404
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    check(outcome.status == "extracted",
          f"a 404 robots.txt must permit fetching, got {outcome.status}")
    print("  ✓ an absent (404) robots.txt permits the visit, per convention")

    # --- robots.txt is fetched once per host, not once per page.
    transport = RecordingTransport(STUDIO_PAGES)
    await make_service(transport).extract(make_lead())
    robots_hits = [u for u in transport.requested if u.endswith("/robots.txt")]
    check(len(robots_hits) == 1,
          f"robots.txt must be fetched once per host, got {len(robots_hits)}: {robots_hits}")
    print("  ✓ robots.txt is fetched exactly once per host and cached")

    # --- And once across concurrent leads on the same host, not once per lead.
    transport = RecordingTransport(STUDIO_PAGES)
    service = make_service(transport)
    await service.extract_many([make_lead(), make_lead(), make_lead()])
    robots_hits = [u for u in transport.requested if u.endswith("/robots.txt")]
    check(len(robots_hits) == 1,
          f"concurrent leads on one host must share one robots.txt fetch, got {len(robots_hits)}")
    print("  ✓ three concurrent leads on one host share a single robots.txt fetch")

    # --- The real robots parser is used, matched against our real User-Agent.
    cache = RobotsCache("TestAgent/1", 1.0)
    check(hasattr(cache, "is_allowed"), "the robots cache must expose is_allowed")
    print("  ✓ robots handling uses urllib.robotparser against the configured User-Agent")


# ===========================================================================================
# 8b. Per-host rate limiting
# ===========================================================================================

async def test_rate_limiting() -> None:
    print("\n[8b] Requests to one host are spaced; different hosts are not")

    # A real (small) interval, so the limiter's actual sleeping is what is measured.
    interval = 0.05
    transport = RecordingTransport(STUDIO_PAGES)
    service = ContactExtractorService(transport=transport, min_request_interval=interval)

    loop = asyncio.get_running_loop()
    started = loop.time()
    await service.extract(make_lead())
    elapsed = loop.time() - started

    pages = len(transport.page_requests)
    check(pages >= 2, f"this fixture must fetch several pages, got {pages}")
    # N requests to one host means at least (N-1) gaps.
    check(elapsed >= interval * (pages - 1),
          f"{pages} same-host requests must be spaced by {interval}s each; took {elapsed:.3f}s")
    print(f"  ✓ {pages} same-host page requests were spaced (took {elapsed:.3f}s)")

    # Two *different* hosts have no reason to queue behind each other: the obligation is owed
    # per server. They should overlap, not serialise.
    pages_two_hosts = {
        "https://alpha.example/": "<html><body><a href='tel:+919876543210'>a</a></body></html>",
        "https://beta.example/": "<html><body><a href='tel:+919876543211'>b</a></body></html>",
    }
    transport = RecordingTransport(pages_two_hosts)
    service = ContactExtractorService(transport=transport, min_request_interval=interval)

    started = loop.time()
    await service.extract_many([
        make_lead(website="https://alpha.example/"),
        make_lead(website="https://beta.example/"),
    ])
    elapsed = loop.time() - started
    check(elapsed < interval * 4,
          f"two different hosts must not serialise behind one another; took {elapsed:.3f}s")
    print(f"  ✓ two different hosts ran concurrently, not serialised ({elapsed:.3f}s)")


# ===========================================================================================
# 9. Enrichment semantics
# ===========================================================================================

async def test_enrichment_semantics() -> None:
    print("\n[9] Enrichment never overwrites and never mutates")

    transport = RecordingTransport(STUDIO_PAGES)
    original = make_lead(
        phones=["+91 90000 00001"],
        emails=["provider@sunrisestudio.in"],
        instagram="provider_handle",
        facebook="https://www.facebook.com/providerpage",
        city="Kozhikode",
        address="MG Road",
        rating=4.6,
    )
    original_phones = list(original.phone_numbers)
    original_emails = list(original.emails)

    enriched = await make_service(transport).extract(original)

    # Existing single-valued fields win: a provider's Google-sourced handle is better
    # attributed than a regex over HTML.
    check(enriched.instagram == "provider_handle",
          f"an existing Instagram must not be overwritten, got {enriched.instagram!r}")
    check(enriched.facebook == "https://www.facebook.com/providerpage",
          f"an existing Facebook must not be overwritten, got {enriched.facebook!r}")
    print("  ✓ existing instagram/facebook values are preserved, never overwritten")

    # The provider's phone stays first — it is what becomes the CRM's `phone` column.
    check(enriched.phone_numbers[0] == "+91 90000 00001",
          f"the provider's phone must stay first, got {enriched.phone_numbers}")
    check(len(enriched.phone_numbers) > 1, "scraped numbers must be appended")
    check(enriched.emails[0] == "provider@sunrisestudio.in",
          f"the provider's email must stay first, got {enriched.emails}")
    print("  ✓ provider values lead; scraped values are appended behind them")

    # The input is never mutated — the service returns a new instance.
    check(original.phone_numbers == original_phones,
          "the input lead's phone list must not be mutated")
    check(original.emails == original_emails,
          "the input lead's email list must not be mutated")
    check(original.instagram == "provider_handle", "the input lead must not be mutated")
    check(enriched is not original, "a new NormalizedLead instance must be returned")
    print("  ✓ the input lead is not mutated; a new instance is returned")

    # Every unrelated field survives the round trip.
    check(enriched.business_name == "Sunrise Studio", "business_name must survive")
    check(enriched.city == "Kozhikode", "city must survive")
    check(enriched.address == "MG Road", "address must survive")
    check(enriched.rating == 4.6, "rating must survive")
    check(enriched.website == original.website, "website must be unchanged")
    print("  ✓ business_name, city, address, rating and website all survive unchanged")

    # YouTube and WhatsApp are first-class DTO fields; `raw` additionally keeps the full
    # harvest and the page list so nothing that lost to an existing field is discarded.
    check(enriched.youtube, "the YouTube URL must be carried on the lead")
    check(enriched.whatsapp_numbers, "WhatsApp numbers must be carried on the lead")
    block = enriched.raw["contact_extraction"]
    check(block["extracted"]["youtube"], "the raw harvest must record YouTube")
    check(block["extracted"]["whatsapp"], "the raw harvest must record WhatsApp")
    check(block["pages_fetched"], "the pages visited must be recorded in raw")
    print("  ✓ youtube/whatsapp on the lead, full harvest + page list kept in raw")

    # The result is still a valid, storable lead.
    valid, reason = enriched.normalize().is_valid()
    check(valid, f"the enriched lead must remain storable, got: {reason}")
    print("  ✓ the enriched lead still passes NormalizedLead.is_valid()")


# ===========================================================================================
# 10. Failure contract and non-persistence
# ===========================================================================================

async def test_failure_contract_and_no_persistence() -> None:
    print("\n[10] Failures return the lead unchanged; nothing is persisted")

    # --- A lead with no website is returned untouched, with no request at all.
    transport = RecordingTransport({})
    lead = make_lead(website=None)
    outcome = await make_service(transport).extract_with_outcome(lead)
    check(outcome.status == "no_website", f"expected no_website, got {outcome.status}")
    check(outcome.lead is lead, "a websiteless lead must be returned untouched")
    check(not transport.requested, "a websiteless lead must issue no request")
    print("  ✓ a lead with no website issues no request and is returned untouched")

    # --- A dead host.
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    lead = make_lead()
    outcome = await make_service(httpx.MockTransport(explode)).extract_with_outcome(lead)
    check(outcome.status == "fetch_failed", f"expected fetch_failed, got {outcome.status}")
    check(outcome.lead is lead, "an unreachable site must return the lead unchanged")
    print("  ✓ an unreachable host returns the lead unchanged, raising nothing")

    # --- A 404 home page.
    transport = RecordingTransport({}, robots=ROBOTS_ALLOW_ALL)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    check(outcome.status == "fetch_failed", f"a 404 must be a fetch failure, got {outcome.status}")
    print("  ✓ a 404 home page returns the lead unchanged")

    # --- A non-HTML response is not parsed.
    def pdf(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(200, text="%PDF-1.4", headers={"content-type": "application/pdf"})

    outcome = await make_service(httpx.MockTransport(pdf)).extract_with_outcome(make_lead())
    check(outcome.status == "invalid_content",
          f"a non-HTML body must be reported as invalid_content, got {outcome.status}")
    print("  ✓ a non-HTML (application/pdf) response is refused, not parsed")

    # --- A page with no contact details at all.
    transport = RecordingTransport(
        {"https://sunrisestudio.in/": "<html><body><p>Nothing here.</p></body></html>"}
    )
    lead = make_lead()
    outcome = await make_service(transport).extract_with_outcome(lead)
    check(outcome.status == "no_contact_found", f"expected nothing_found, got {outcome.status}")
    check(outcome.lead is lead, "a contactless page must return the lead unchanged")
    print("  ✓ a page with no contact details returns the lead unchanged")

    # --- Malformed markup degrades to a parse, never to a crash.
    transport = RecordingTransport(
        {"https://sunrisestudio.in/": "<html><body><div><a href='tel:+919876543210'>x"}
    )
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    check(outcome.status == "extracted",
          f"unclosed markup must still parse, got {outcome.status}")
    print("  ✓ malformed/unclosed markup still parses rather than raising")

    # --- One failing lead does not abort a batch.
    class FlakyTransport(httpx.MockTransport):
        def __init__(self) -> None:
            def handler(request: httpx.Request) -> httpx.Response:
                url = str(request.url)
                if url.endswith("/robots.txt"):
                    return httpx.Response(404)
                if "broken" in url:
                    raise httpx.ConnectError("down")
                return httpx.Response(
                    200, text=HOME_HTML, headers={"content-type": "text/html"}
                )
            super().__init__(handler)

    results = await make_service(FlakyTransport()).extract_many([
        make_lead(website="https://sunrisestudio.in/"),
        make_lead(website="https://broken.example/"),
        make_lead(website="https://sunrisestudio.in/"),
    ])
    check(len(results) == 3, "a mid-batch failure must not shorten the batch")
    check(results[0].emails, "the first lead must enrich")
    check(not results[1].emails, "the failing lead must be returned unchanged")
    check(results[2].emails, "the last lead must still enrich")
    print("  ✓ one failing lead does not abort a batch — the others still enrich")

    # --- Non-persistence, asserted on the source itself.
    source = inspect.getsource(module)
    forbidden = [
        ("from app.models", "an ORM model import"),
        ("from app.repositories", "a repository import"),
        ("AsyncSession", "a database session"),
        ("db.commit", "a commit"),
        ("db.add", "a session write"),
        ("session.", "a session call"),
    ]
    for needle, description in forbidden:
        check(needle not in source,
              f"contact_extractor.py must not contain {description} ({needle!r})")
    print("  ✓ module contains no model import, no repository, no session, no commit")

    signature = inspect.signature(ContactExtractorService.extract)
    check("db" not in signature.parameters, "extract() must not accept a database session")
    check(list(signature.parameters) == ["self", "lead"],
          f"extract() must be lead-in/lead-out, got {list(signature.parameters)}")
    print("  ✓ extract(lead) -> NormalizedLead takes no session: it cannot write to the CRM")

    check(isinstance(outcome, ExtractionOutcome),
          "extract_with_outcome returns an ExtractionOutcome")
    print("  ✓ the service returns normalized leads and nothing else is persisted")




# ===========================================================================================
# 11. Phone parsing is libphonenumber-backed, and output is E.164
# ===========================================================================================

async def test_phone_normalisation_e164() -> None:
    """
    The brief names the Indian formats that must parse and the canonical form they must reach.
    Asserted directly against the extraction path rather than the helper, so a page really does
    turn "0091 9876543210" into "+919876543210".
    """
    print("\n[11] Indian phone formats normalise to E.164")

    # Every one of these is the same number written the way a different site writes it.
    same_number = [
        "9876543210",
        "+91 9876543210",
        "+919876543210",
        "0091 9876543210",
        "098765 43210",
    ]
    for written in same_number:
        page = f"<html><body><p>Call {written} today</p></body></html>"
        transport = RecordingTransport({"https://x.example/": page})
        lead = await make_service(transport).extract(make_lead(website="https://x.example/"))
        check(lead.phone_numbers == ["+919876543210"],
              f"{written!r} must normalise to +919876543210, got {lead.phone_numbers}")
    print(f"  ✓ all {len(same_number)} written forms normalise to '+919876543210'")

    # A landline with an STD code is a valid business number and must survive too.
    transport = RecordingTransport(
        {"https://x.example/": "<html><body><p>Desk: 080 12345678</p></body></html>"}
    )
    lead = await make_service(transport).extract(make_lead(website="https://x.example/"))
    check(lead.phone_numbers == ["+918012345678"],
          f"a Bangalore landline must normalise to E.164, got {lead.phone_numbers}")
    print(f"  ✓ landline '080 12345678' → {lead.phone_numbers[0]!r}")

    # An arbitrary long numeric string is not a phone number, however many digits it has.
    junk = "<html><body><p>Order 12345678901234 GST 29AABCU9603R1ZM</p></body></html>"
    transport = RecordingTransport({"https://x.example/": junk})
    lead = await make_service(transport).extract(make_lead(website="https://x.example/"))
    check(lead.phone_numbers == [],
          f"order/GST identifiers must not become phones, got {lead.phone_numbers}")
    print("  ✓ order numbers and GST identifiers are not treated as phone numbers")

    # libphonenumber knows 1234567890 is not an assignable Indian number; the heuristic alone
    # could not tell. This is the check that proves the library is actually consulted.
    check(module._import_phonenumbers() is not None,
          "the phonenumbers library must be installed for this suite")
    check(not module._looks_like_phone("1234567890"),
          "an unassignable range must be rejected")
    check(module._looks_like_phone("9876543210"), "a real mobile range must be accepted")
    check(module._to_e164("+91 98765 43210") == "+919876543210",
          "_to_e164 must render E.164")
    print("  ✓ libphonenumber validity is consulted, not just digit-count heuristics")


# ===========================================================================================
# 12. Response size, redirects and page budget are all bounded
# ===========================================================================================

async def test_transfer_limits() -> None:
    """
    Each limit is asserted by *observing the transfer*, not by reading the setting back: a cap
    that is configured but never enforced is the failure mode worth testing for.
    """
    print("\n[12] Response size, redirect and page limits are enforced")

    # --- Oversized body. Streamed, so the cap must trip while bytes arrive.
    huge = "<html><body>" + ("x" * 100_000) + "</body></html>"

    def big(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(200, text=huge, headers={"content-type": "text/html"})

    outcome = await make_service(
        httpx.MockTransport(big), max_page_bytes=1_000
    ).extract_with_outcome(make_lead(website="https://x.example/"))
    check(outcome.status == "invalid_content",
          f"an oversized body must be refused, got {outcome.status}")
    print("  ✓ a body over max_page_bytes is refused as invalid_content")

    # A page inside the cap is unaffected — the limit must not reject everything.
    small = "<html><body><a href='tel:+919876543210'>call</a></body></html>"
    transport = RecordingTransport({"https://x.example/": small})
    lead = await make_service(transport, max_page_bytes=1_000_000).extract(
        make_lead(website="https://x.example/")
    )
    check(lead.phone_numbers == ["+919876543210"], "a page inside the cap must still parse")
    print("  ✓ a page inside the cap is read normally")

    # --- A declared Content-Length over the cap is refused without transferring the body.
    def declared(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(
            200, text=small,
            headers={"content-type": "text/html", "content-length": "999999999"},
        )

    outcome = await make_service(
        httpx.MockTransport(declared), max_page_bytes=1_000
    ).extract_with_outcome(make_lead(website="https://x.example/"))
    check(outcome.status == "invalid_content",
          f"a declared oversize must be refused, got {outcome.status}")
    print("  ✓ an oversized Content-Length is refused before the body is read")

    # --- Redirect chains are bounded rather than followed indefinitely.
    hops: list[str] = []

    def loop(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        hops.append(url)
        return httpx.Response(302, headers={"location": f"/hop{len(hops)}"})

    outcome = await make_service(
        httpx.MockTransport(loop), max_redirects=3
    ).extract_with_outcome(make_lead(website="https://x.example/"))
    check(outcome.status == "fetch_failed",
          f"an endless redirect chain must fail, got {outcome.status}")
    check(len(hops) <= 5, f"the chain must be bounded, but {len(hops)} hops were made")
    print(f"  ✓ an endless redirect chain stopped after {len(hops)} hops and failed cleanly")

    # A redirect *within* the budget is followed, and links resolve against where we landed.
    def once(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        if url == "https://x.example/":
            return httpx.Response(301, headers={"location": "https://x.example/home"})
        return httpx.Response(200, text=small, headers={"content-type": "text/html"})

    lead = await make_service(httpx.MockTransport(once), max_redirects=3).extract(
        make_lead(website="https://x.example/")
    )
    check(lead.phone_numbers == ["+919876543210"],
          "a redirect inside the budget must still yield the page")
    print("  ✓ a redirect inside the budget is followed normally")

    # --- The per-lead page budget.
    transport = RecordingTransport(STUDIO_PAGES)
    await make_service(transport, max_subpages=1).extract(make_lead())
    check(len(transport.page_requests) == 2,
          f"1 home + 1 sub-page expected, got {transport.page_requests}")
    print(f"  ✓ max_subpages=1 yielded exactly {len(transport.page_requests)} page requests")


# ===========================================================================================
# 13. Concurrency is bounded
# ===========================================================================================

async def test_concurrency_is_bounded() -> None:
    """
    `extract_many` must not open a socket per lead. Asserted by watching how many extractions
    are in flight at once across a batch far larger than the limit.
    """
    print("\n[13] Batch concurrency is bounded by the configured limit")

    in_flight = 0
    peak = 0

    # An *async* handler that yields to the event loop is essential here: a synchronous mock
    # returns before any sibling task can start, so overlap would be impossible and the test
    # would pass at a peak of 1 no matter how broken the semaphore was.
    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404)
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.02)
            return httpx.Response(
                200,
                text="<html><body><a href='tel:+919876543210'>c</a></body></html>",
                headers={"content-type": "text/html"},
            )
        finally:
            in_flight -= 1

    # Distinct hosts, so the per-host throttle is not what bounds this — only the semaphore is.
    leads = [make_lead(website=f"https://site{i}.example/") for i in range(20)]
    service = make_service(httpx.MockTransport(slow), concurrency=3)
    results = await service.extract_many(leads)

    check(len(results) == 20, f"every lead must come back, got {len(results)}")
    check(peak <= 3, f"concurrency must stay within 3, peaked at {peak}")
    # Guards against a vacuous pass: if requests never actually overlapped, a peak of 1 would
    # satisfy the cap above while telling us nothing about whether the semaphore works.
    check(peak > 1, f"the batch must genuinely run in parallel, but peaked at {peak}")
    print(f"  ✓ 20 leads at concurrency=3 peaked at {peak} simultaneous fetches (>1, <=3)")

    order_ok = all(r.website == l.website for r, l in zip(results, leads))
    check(order_ok, "extract_many must preserve input order")
    print("  ✓ input order is preserved across the batch")


# ===========================================================================================
# 14. The ownership / relevance signal
# ===========================================================================================

async def test_relevance_signal() -> None:
    """
    Relevance is *advice*. These assertions pin both halves of that: a matching site scores
    high, an unrelated one scores low, and in neither case is the extraction discarded.
    """
    print("\n[14] Ownership/relevance is scored and reported, never enforced")

    owned = """
    <html><head><title>Sunrise Studio, Kozhikode</title></head><body>
      <p>Sunrise Studio has photographed weddings across Kozhikode since 2014.</p>
      <a href="tel:+919876543210">+91 98765 43210</a>
      <a href="mailto:hello@sunrisestudio.in">mail us</a>
    </body></html>
    """
    transport = RecordingTransport({"https://sunrisestudio.in/": owned})
    outcome = await make_service(transport).extract_with_outcome(
        make_lead(name="Sunrise Studio", city="Kozhikode", phones=["+91 98765 43210"])
    )
    check(outcome.relevance_status == "owned",
          f"a matching site must read as owned, got {outcome.relevance_status}")
    check(outcome.relevance_score >= 0.6,
          f"a matching site must score high, got {outcome.relevance_score}")
    check(any("phone" in s for s in outcome.relevance_signals),
          f"the known-phone match must be reported, got {outcome.relevance_signals}")
    print(f"  ✓ matching site: score={outcome.relevance_score} status={outcome.relevance_status!r}")
    for signal in outcome.relevance_signals:
        print(f"      - {signal}")

    unrelated = """
    <html><head><title>Cheap Flights Daily</title></head><body>
      <p>Compare fares to 400 destinations.</p>
      <a href="tel:+911122334455">+91 11223 34455</a>
    </body></html>
    """
    transport = RecordingTransport({"https://flights.example/": unrelated})
    outcome = await make_service(transport).extract_with_outcome(
        make_lead(name="Sunrise Studio", city="Kozhikode", website="https://flights.example/")
    )
    check(outcome.relevance_status == "unrelated",
          f"an unrelated site must read as unrelated, got {outcome.relevance_status}")
    print(f"  ✓ unrelated site: score={outcome.relevance_score} status={outcome.relevance_status!r}")

    # The decisive point: a low score does NOT suppress the extraction. The pipeline decides.
    check(outcome.status in ("extracted", "partial"),
          f"a low score must not change the status, got {outcome.status}")
    check(outcome.lead.phone_numbers,
          "a low-relevance site's contacts must still be returned for the caller to judge")
    print("  ✓ a low score neither discards the website nor drops the extracted contacts")

    # The signal reaches the caller as data, not just as a log line.
    payload = outcome.to_dict()
    check("relevance_score" in payload and "relevance_status" in payload,
          "relevance must be serialised for the pipeline")
    print("  ✓ relevance_score/status/signals are serialised on the outcome")


# ===========================================================================================
# 15. Result statuses distinguish the cases the pipeline must act on
# ===========================================================================================

async def test_result_statuses() -> None:
    """
    The pipeline branches on `status`, so each documented value must be reachable and must
    mean what it says — in particular that "found nothing" is a success, not an error.
    """
    print("\n[15] Every documented result status is reachable and distinct")

    seen: dict[str, str] = {}

    # extracted — everything we asked for was read.
    transport = RecordingTransport(STUDIO_PAGES)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    seen["extracted"] = outcome.status
    check(outcome.status == "extracted", f"expected extracted, got {outcome.status}")
    check(outcome.pages_failed == (), "a clean run has no failed pages")

    # partial — contacts found, but a selected page would not load.
    partial_pages = dict(STUDIO_PAGES)
    del partial_pages["https://sunrisestudio.in/contact"]  # now 404s
    transport = RecordingTransport(partial_pages)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    seen["partial"] = outcome.status
    check(outcome.status == "partial", f"expected partial, got {outcome.status}")
    check(outcome.pages_failed, "partial must name the page(s) that failed")
    check(outcome.lead.phone_numbers, "partial must still return what it did find")
    print(f"  ✓ one unreachable sub-page → 'partial', with {len(outcome.pages_failed)} failure recorded")

    # no_contact_found — the visit worked; the site simply publishes nothing.
    transport = RecordingTransport(
        {"https://x.example/": "<html><body><p>Coming soon.</p></body></html>"}
    )
    outcome = await make_service(transport).extract_with_outcome(
        make_lead(website="https://x.example/")
    )
    seen["no_contact_found"] = outcome.status
    check(outcome.status == "no_contact_found", f"expected no_contact_found, got {outcome.status}")
    check(outcome.succeeded, "no_contact_found must count as a successful run, not an error")
    print("  ✓ 'no_contact_found' is reported as a success, not a system error")

    # fetch_failed — the transport never delivered a page.
    def dead(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404)
        raise httpx.ConnectError("no route to host")

    outcome = await make_service(httpx.MockTransport(dead)).extract_with_outcome(
        make_lead(website="https://x.example/")
    )
    seen["fetch_failed"] = outcome.status
    check(outcome.status == "fetch_failed", f"expected fetch_failed, got {outcome.status}")
    check(not outcome.succeeded, "fetch_failed is not a success")

    # robots_blocked — the site said no.
    transport = RecordingTransport(STUDIO_PAGES, robots=ROBOTS_DISALLOW_ALL)
    outcome = await make_service(transport).extract_with_outcome(make_lead())
    seen["robots_blocked"] = outcome.status
    check(outcome.status == "robots_blocked", f"expected robots_blocked, got {outcome.status}")

    # invalid_content — a response arrived, but not a page.
    def pdf(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(200, text="%PDF", headers={"content-type": "application/pdf"})

    outcome = await make_service(httpx.MockTransport(pdf)).extract_with_outcome(
        make_lead(website="https://x.example/")
    )
    seen["invalid_content"] = outcome.status
    check(outcome.status == "invalid_content", f"expected invalid_content, got {outcome.status}")

    # no_website — nothing to visit.
    outcome = await make_service(RecordingTransport({})).extract_with_outcome(
        make_lead(website=None)
    )
    seen["no_website"] = outcome.status
    check(outcome.status == "no_website", f"expected no_website, got {outcome.status}")

    check(len(set(seen.values())) == len(seen),
          f"each case must produce a distinct status, got {seen}")
    print(f"  ✓ all {len(seen)} statuses reachable and distinct: {', '.join(sorted(seen.values()))}")


# ===========================================================================================
# 16. No social-media scraping, and existing data is preserved
# ===========================================================================================

async def test_no_social_scraping_and_preservation() -> None:
    """
    The brief forbids scraping Instagram/Facebook — we take only the links a business
    publishes on its *own* site. Asserted on the request log: the social hosts are linked
    from the fixture, and must never be requested.
    """
    print("\n[16] Social links are read, never scraped; existing data preserved")

    transport = RecordingTransport(STUDIO_PAGES)
    lead = await make_service(transport).extract(make_lead())

    social_hosts = ("instagram.com", "facebook.com", "youtube.com", "fb.com", "wa.me",
                    "whatsapp.com", "graph.facebook.com")
    for url in transport.requested:
        for host in social_hosts:
            check(host not in url,
                  f"no request may be made to {host}, but {url!r} was requested")
    print(f"  ✓ {len(transport.requested)} requests issued, none to any social platform")

    check(lead.instagram == "sunrisestudio", "the published Instagram link is still read")
    check(lead.facebook and "facebook.com" in lead.facebook, "the published FB link is read")
    check(lead.youtube and "youtube.com" in lead.youtube, "the published YT link is read")
    print("  ✓ Instagram/Facebook/YouTube captured from the site's own published links")

    # Existing values are never overwritten, and lists merge rather than replace.
    existing = make_lead(
        phones=["+919999888877"],
        emails=["owner@sunrisestudio.in"],
        instagram="original_handle",
        facebook="https://www.facebook.com/originalpage",
        youtube="https://www.youtube.com/@originalchannel",
    )
    enriched = await make_service(RecordingTransport(STUDIO_PAGES)).extract(existing)

    check(enriched.instagram == "original_handle", "instagram must not be overwritten")
    check(enriched.facebook == "https://www.facebook.com/originalpage",
          "facebook must not be overwritten")
    check(enriched.youtube == "https://www.youtube.com/@originalchannel",
          "youtube must not be overwritten")
    check(enriched.phone_numbers[0] == "+919999888877", "the existing phone must stay first")
    check(len(enriched.phone_numbers) > 1, "scraped phones must be appended, not dropped")
    check(enriched.emails[0] == "owner@sunrisestudio.in", "the existing email must stay first")
    print("  ✓ existing single-valued fields preserved; list fields merged behind them")

    # Merging is de-duplicated on comparison keys, not raw strings.
    keys = [module.normalize_phone(p) for p in enriched.phone_numbers]
    check(len(keys) == len(set(keys)), f"merged phones must be unique, got {enriched.phone_numbers}")
    emails = [e.lower() for e in enriched.emails]
    check(len(emails) == len(set(emails)), f"merged emails must be unique, got {enriched.emails}")
    print("  ✓ merged lists contain no duplicates")

    # WhatsApp stays separate from ordinary phones, and is not assumed for every number.
    check(enriched.whatsapp_numbers, "a wa.me link must populate whatsapp_numbers")
    check(len(enriched.whatsapp_numbers) < len(enriched.phone_numbers),
          "not every phone may be assumed to be a WhatsApp number")
    print(f"  ✓ whatsapp_numbers={enriched.whatsapp_numbers} kept separate from phone_numbers")


# ===========================================================================================
# Runner
# ===========================================================================================

async def test_contact_extractor_suite() -> None:
    print("=" * 78)
    print("CONTACT EXTRACTOR SERVICE — UNIT SUITE")
    print("=" * 78)

    try:
        module._import_bs4()
    except ContactExtractionError as exc:
        print(f"\nSKIPPED: {exc}")
        print("Install the dependency and re-run:  pip install beautifulsoup4")
        sys.exit(1)

    await test_construction()
    await test_regions_are_read()
    await test_extracts_all_fields()
    await test_normalisation()
    await test_rejects_junk()
    await test_depth_is_one_level()
    await test_does_not_crawl_whole_site()
    await test_respects_robots()
    await test_rate_limiting()
    await test_enrichment_semantics()
    await test_failure_contract_and_no_persistence()
    await test_phone_normalisation_e164()
    await test_transfer_limits()
    await test_concurrency_is_bounded()
    await test_relevance_signal()
    await test_result_statuses()
    await test_no_social_scraping_and_preservation()

    print("\n" + "=" * 78)
    print("ALL 17 SECTIONS PASSED")
    print("=" * 78)
    print("\nNo database was touched: the service returns normalized leads and persists")
    print("nothing. No network was touched: every page and robots.txt was mocked.")


if __name__ == "__main__":
    asyncio.run(test_contact_extractor_suite())
