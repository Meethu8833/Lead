"""
app/services/lead_providers/planned.py

This file declares the lead sources that are part of the collection plan but have no
implementation behind them yet: Justdial, Facebook, IndiaMART and wedding directories.

Google Maps and Instagram used to be declared here and no longer are: they now have real
implementations in `google_maps.py` (official Places API) and `instagram.py` (Instagram Graph
API business discovery). Those two migrations are the evidence for point 3 below —
implementing a planned source meant deleting a class from this file and adding a sibling
module, with no change to `LeadImportService`, the endpoints, the schemas or the database.

Why declare them at all
-----------------------
Each is a `PlannedProvider` subclass — registered, discoverable and listed by
`GET /leads/import/providers`, but refusing to run. That gives three things a bare TODO
comment would not:

1. The API validates `provider` against the full planned set, so a client naming
   "justdial" gets an explicit "declared but not yet implemented" 400 rather than an
   "unknown provider" 400 that reads like a typo.
2. The `LeadSource` attribution for each source is decided and recorded in one place now,
   so leads imported later are tagged consistently with leads a human entered by hand.
3. Implementing one is provably a closed change: replace the class body with `collect()`
   and `normalize()`, drop `is_available = False`. Nothing in the service, the endpoints,
   the schemas or the database is touched — which is the extensibility property this
   module was asked to demonstrate.

No scraping is implemented here, deliberately. Each of these sources is governed by terms
of service and, in several cases, an official API with its own credentials and quota; the
right implementation is an authorised API client (Google Places API, Meta Graph API,
IndiaMART's lead API) or a licensed data feed, configured with real credentials. That is a
commissioning decision, not something to be guessed at in the collection engine.
"""

from __future__ import annotations

from app.services.lead_providers.base import PlannedProvider, register_provider


@register_provider
class JustdialLeadProvider(PlannedProvider):
    """
    Justdial business listings.

    Intended implementation: Justdial's partner/API feed. Justdial commonly proxies contact
    numbers, so a real adapter must resolve the actual business number where the feed
    permits and otherwise record the listing without a phone — which this engine already
    counts as a failed record rather than storing an unusable proxy number as a lead.
    """
    key = "justdial"
    display_name = "Justdial"
    lead_source = "JUSTDIAL"
    requires_query = True


@register_provider
class FacebookLeadProvider(PlannedProvider):
    """
    Facebook Pages for photography businesses.

    Intended implementation: Meta Graph API Page search with a business-verified app.
    Contact fields are only exposed for Pages that publish them, so expect a lower
    phone-coverage rate than a directory source and a correspondingly higher failed-record
    count.
    """
    key = "facebook"
    display_name = "Facebook"
    lead_source = "FACEBOOK"
    requires_query = True


@register_provider
class IndiaMartLeadProvider(PlannedProvider):
    """
    IndiaMART supplier listings.

    Intended implementation: IndiaMART's seller/lead API with a supplier account. Listings
    are company-shaped rather than studio-shaped, so the adapter should map the company as
    `business_name` and the listed contact as `owner_name`.
    """
    key = "indiamart"
    display_name = "IndiaMART"
    lead_source = "OTHER"
    requires_query = True


@register_provider
class WeddingDirectoryLeadProvider(PlannedProvider):
    """
    Wedding vendor directories (WedMeGood, ShaadiSaga, WeddingWire and similar).

    Intended implementation: one licensed feed or partner API per directory, selected via
    `options["directory"]` so the several directories share this single adapter rather than
    multiplying near-identical classes. They are the highest-intent source for this
    business — every listing is a photographer actively selling wedding work — which is why
    the source is declared here rather than left to the generic CSV path.
    """
    key = "wedding_directory"
    display_name = "Wedding Directories"
    lead_source = "OTHER"
    requires_query = True
