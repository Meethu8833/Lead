"""
app/schemas/import_job.py

This file defines the Pydantic schemas for the Lead Collection Engine.
Under Clean Architecture, schemas act as Data Transfer Objects (DTOs) in the Interface
Adapters layer: they validate client inputs and structure client outputs.

Note that `NormalizedLead` (app/services/lead_providers/normalized.py) is deliberately NOT
one of these. It is an internal contract between providers and the import service, built by
our own adapter code rather than parsed from client JSON; `NormalizedLeadPreview` below is
its read-only projection for API responses.
"""

import uuid
from datetime import datetime
from typing import Any, List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.import_job import ImportJobStatus


class ImportRunRequest(BaseModel):
    """
    Schema for validating a request to run a collection import.

    Used for query-driven providers. CSV imports arrive as multipart form data instead
    (see the `/leads/import/csv` endpoint), because a JSON body cannot carry a file.

    `provider` is a free string validated against the live registry at the service boundary
    rather than an enum here, so that registering a new provider does not require editing
    this schema — the same reasoning as the `ImportJob.provider` column.
    """
    provider: str = Field(
        ...,
        description="Registry key of the provider to run (e.g. 'mock', 'google_maps')",
        min_length=1,
        max_length=50,
    )
    query: str | None = Field(
        None,
        description="Search query for the provider. Required by query-driven providers.",
        max_length=500,
    )
    limit: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum number of records to collect in this run",
    )
    city: str | None = Field(None, max_length=100, description="Optional city to scope the search")
    state: str | None = Field(None, max_length=100, description="Optional state to scope the search")
    options: dict[str, Any] | None = Field(
        None,
        description="Free-form provider-specific extras, passed through to the adapter",
    )

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, v: str) -> str:
        """
        Lowercases and trims the provider key so 'Google_Maps' and 'google_maps' resolve to
        the same adapter and are recorded identically on the job.
        """
        cleaned = v.strip().lower()
        if not cleaned:
            raise ValueError("Provider key cannot be empty or contain only whitespace.")
        return cleaned

    @field_validator("query", "city", "state")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        """Treats a whitespace-only value as absent, so it fails the provider's own check."""
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class ImportJobResponse(BaseModel):
    """
    Schema for serializing an ImportJob record into an API response.

    `logs` is excluded from this shape and served only by the job-detail endpoint: a run
    over a thousand records carries a thousand log entries, and returning them inside every
    row of a paginated history listing would dwarf the rest of the payload.
    """
    id: uuid.UUID
    provider: str
    query: str | None
    status: ImportJobStatus
    started_at: datetime | None
    completed_at: datetime | None
    total_found: int
    new_leads: int
    updated_leads: int
    duplicate_leads: int
    failed_records: int
    error_message: str | None
    source_filename: str | None
    retry_of_job_id: uuid.UUID | None
    created_by: uuid.UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ImportJobDetailResponse(ImportJobResponse):
    """
    Schema for a single import job, including its full diagnostic log array.
    """
    logs: List[dict[str, Any]] | None = Field(
        None,
        description="Structured per-record diagnostics accumulated during the run",
    )

    class Config:
        from_attributes = True


class ImportJobListResponse(BaseModel):
    """
    Schema for a paginated list of import jobs.
    """
    items: List[ImportJobResponse]
    total: int = Field(..., description="Total number of jobs matching the query (ignoring skip/limit)")
    skip: int
    limit: int


class ProviderInfo(BaseModel):
    """
    Schema describing one registered provider's capabilities.

    `is_available` is what distinguishes an implemented adapter from a declared-but-planned
    source; a client should present unavailable providers as coming-soon rather than hiding
    them, since the set is the module's roadmap.
    """
    key: str = Field(..., description="Registry key used in an import request")
    display_name: str = Field(..., description="Human-readable provider name")
    lead_source: str = Field(..., description="LeadSource value that imported leads are tagged with")
    requires_query: bool = Field(..., description="Whether a search query is mandatory")
    requires_file: bool = Field(..., description="Whether a file upload is mandatory")
    is_available: bool = Field(..., description="Whether the provider is implemented and runnable")


class ProviderListResponse(BaseModel):
    """
    Schema for the list of registered providers.
    """
    items: List[ProviderInfo]
    total: int


class ImportStatisticsResponse(BaseModel):
    """
    Schema for lifetime aggregate statistics across every import run.
    """
    total_jobs: int = Field(..., description="Number of import runs recorded")
    total_found: int = Field(..., description="Total records collected across all runs")
    new_leads: int = Field(..., description="Total leads created across all runs")
    updated_leads: int = Field(..., description="Total existing leads enriched across all runs")
    duplicate_leads: int = Field(..., description="Total records that were duplicates carrying nothing new")
    failed_records: int = Field(..., description="Total records that could not be imported")
    jobs_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Count of jobs per lifecycle status",
    )


class NormalizedLeadPreview(BaseModel):
    """
    Read-only projection of a `NormalizedLead`, for endpoints that show what a provider
    would produce without writing anything.
    """
    business_name: str | None = None
    owner_name: str | None = None
    phone_numbers: List[str] = Field(default_factory=list)
    emails: List[str] = Field(default_factory=list)
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
    categories: List[str] = Field(default_factory=list)


class DiscoveryRunRequest(BaseModel):
    """
    Schema for validating a request to run the lead discovery pipeline.

    Distinct from `ImportRunRequest` above, and deliberately so. An import names a
    *provider* and hands it a free-text query; discovery names a *place* and runs the fixed
    city -> Overpass -> website -> contacts -> dedup pipeline that `LeadDiscoveryService`
    owns. Exposing `provider` here would invite callers to point the pipeline at a source
    whose first stage cannot geocode a city, which is the one input the pipeline requires.

    `radius_km` is validated loosely here (positive, sane upper bound) and authoritatively
    by the Overpass adapter, which clamps it to `settings.OVERPASS_MAX_RADIUS_KM`. The
    duplication is intentional: this bound rejects an obviously wrong value at the edge with
    a 422 naming the field, while the adapter's clamp remains the single source of truth for
    how far the public endpoint is willing to be asked to look.
    """

    city: str = Field(
        ...,
        description="City to discover leads in. Geocoded by the provider (e.g. 'Calicut').",
        min_length=1,
        max_length=100,
    )
    category: str | None = Field(
        "photographer",
        description=(
            "Business category to search for. Recorded on every collected record and "
            "surfaced as a lead category tag."
        ),
        max_length=100,
    )
    radius_km: float | None = Field(
        None,
        gt=0,
        le=100,
        description=(
            "Search radius in kilometres around the city centre. Defaults to the "
            "provider's own default and is clamped to its configured ceiling."
        ),
    )
    limit: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum number of records to collect in this run",
    )
    state: str | None = Field(
        None, max_length=100, description="Optional state, to disambiguate the city"
    )
    discover_websites: bool = Field(
        True,
        description=(
            "Run the website-discovery stage. Disable to skip its network cost on a city "
            "that has already been enriched."
        ),
    )
    extract_contacts: bool = Field(
        True,
        description=(
            "Run the contact-extraction stage, which visits discovered websites. Disable "
            "for map data alone."
        ),
    )

    @field_validator("city")
    @classmethod
    def city_must_not_be_blank(cls, v: str) -> str:
        """
        Trims the city and rejects a whitespace-only one.

        Kept separate from the optional fields below because they must behave differently.
        `min_length=1` accepts `"   "`, so folding `city` into the blank-to-None validator
        would quietly hand the pipeline a `None` city — which the Overpass adapter would
        then refuse with a 400 about a missing city, blaming the source for a request the
        edge should never have accepted. Rejecting here produces a 422 naming the field.
        """
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("City cannot be empty or contain only whitespace.")
        return cleaned

    @field_validator("category", "state")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        """
        Treats a whitespace-only value as absent, so it falls back to the pipeline's own
        default rather than narrowing the search to an empty string.
        """
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class DiscoveryRecord(BaseModel):
    """
    One lead a discovery run touched, identified well enough to show in a results table.

    Deliberately not `LeadResponse`. The discovery screen lists what a run did; it does not
    need the full lead aggregate, and binding this response to that schema would couple the
    run summary to every future change in the lead model. The `id` is here so the UI can
    link through to the real lead record for anything beyond these fields.
    """

    id: uuid.UUID = Field(..., description="Id of the lead created or enriched")
    business_name: str | None = Field(None, description="Business name as stored")
    phone: str | None = Field(None, description="Primary phone, canonicalised")
    email: str | None = Field(None, description="Primary email, if one was found")
    city: str | None = Field(None, description="City the lead was discovered in")
    website: str | None = Field(None, description="Website, if discovered or already known")

    #: The remaining contact channels, so the results table can column them without
    #: re-fetching each lead. Every one is the value that was *stored*, not the value the
    #: run proposed — a merge that declined to overwrite reports the kept value.
    whatsapp: str | None = Field(
        None, description="WhatsApp number, only when a source identified it as one"
    )
    instagram: str | None = Field(None, description="Instagram handle, if collected")
    facebook: str | None = Field(None, description="Facebook page URL, if collected")
    youtube: str | None = Field(None, description="YouTube channel URL, if collected")
    source: str | None = Field(None, description="LeadSource the stored lead is tagged with")

    #: Derived, never stored. See `DiscoveredLeadRecord.is_whatsapp_ready` / `.contact_quality`.
    is_whatsapp_ready: bool = Field(
        False,
        description=(
            "Whether this lead has a number known to be on WhatsApp. An ordinary phone "
            "number does not qualify."
        ),
    )
    contact_quality: str = Field(
        "NONE",
        description="Outreach priority band derived from stored fields: HIGH/MEDIUM/LOW/NONE",
    )

    #: Which previously-empty fields this run filled in. Empty for a newly created lead —
    #: every field is new — and populated for a merge, which is the whole reason a merge is
    #: reported separately from a duplicate.
    enriched_fields: list[str] = Field(
        default_factory=list,
        description="Names of the fields this run filled in on an existing lead",
    )

    model_config = ConfigDict(from_attributes=True)


class DiscoveryFailure(BaseModel):
    """
    One record the run could not store, paired with why.

    The service records these as free-text lines because the reasons come from several
    stages. Splitting the business name out lets the table show a name column and keeps the
    reason readable, and both fall back gracefully when a line cannot be split.
    """

    business_name: str | None = Field(
        None, description="Business name of the record, when it had one"
    )
    reason: str = Field(..., description="Why the record could not be stored")


class DiscoveryStage(BaseModel):
    """One pipeline stage's effect on the batch, mirroring `StageStats.to_dict()`."""

    stage: str = Field(..., description="Stage name, in pipeline order")
    records_in: int = Field(..., description="Records that entered the stage")
    records_enriched: int = Field(..., description="Records the stage added something to")


class DiscoveryEnrichmentStats(BaseModel):
    """
    Mirrors `EnrichmentStats.to_dict()` — what one run actually landed.

    The contact counters are measured over the leads the run wrote, so they describe stored
    data rather than attempted enrichment; `websites_discovered` and `contacts_extracted`
    describe stage work done. See `EnrichmentStats` for why the two are counted differently.
    """

    websites_discovered: int = Field(
        0, description="Leads that gained a website in the discovery stage"
    )
    contacts_extracted: int = Field(
        0, description="Leads whose website yielded at least one new contact detail"
    )
    emails_found: int = Field(0, description="Written leads holding an email")
    phones_found: int = Field(0, description="Written leads holding a phone number")
    whatsapp_found: int = Field(0, description="Written leads holding a WhatsApp number")
    instagram_found: int = Field(0, description="Written leads holding an Instagram handle")
    facebook_found: int = Field(0, description="Written leads holding a Facebook URL")
    youtube_found: int = Field(0, description="Written leads holding a YouTube URL")


class DiscoveryRunResponse(BaseModel):
    """
    Schema for serializing the outcome of one discovery run.

    The five counters of `DiscoverySummary.to_dict()` are the contract this service was
    specified to return, and they reconcile: `imported + merged + duplicates + failed ==
    found`. Nothing below changes that identity.

    The record-level fields (`imported_records`, `merged_records`, `failed_records`,
    `stages`) were added so the discovery screen can show *which* leads a run produced
    rather than only how many. They are additive and every one defaults to empty, so a
    caller reading just the five counters is unaffected.

    An earlier revision of this docstring argued these diagnostics should stay out of the
    response because their shape is free to change. That argument is now settled the other
    way, and the cost is real rather than hypothetical: these four fields are API, and the
    UI's results tables read them. Change them the way any response model is changed —
    additively, or with a version bump. `created_lead_ids` and `merged_lead_ids` remain
    internal to the summary; the records here supersede them for external callers.
    """

    found: int = Field(
        ..., description="Records the provider returned, before filtering. The denominator."
    )
    imported: int = Field(..., description="New leads created from this run")
    duplicates: int = Field(
        ..., description="Records that matched an existing lead and added nothing new"
    )
    merged: int = Field(
        ...,
        description="Existing leads enriched with at least one previously-empty field",
    )
    failed: int = Field(
        ...,
        description=(
            "Records that could not be stored: invalid (no business name or no phone), "
            "or a write that raised."
        ),
    )

    imported_records: list[DiscoveryRecord] = Field(
        default_factory=list,
        description="The leads this run created. Length matches `imported`.",
    )
    merged_records: list[DiscoveryRecord] = Field(
        default_factory=list,
        description=(
            "Existing leads this run enriched, each with the fields it filled in. Length "
            "matches `merged`."
        ),
    )
    failed_records: list[DiscoveryFailure] = Field(
        default_factory=list,
        description="Records that could not be stored, with the reason for each.",
    )
    stages: list[DiscoveryStage] = Field(
        default_factory=list,
        description="Per-stage effect, in pipeline order. Diagnostic; no counter derives from it.",
    )
    city: str | None = Field(
        None, description="City this run collected for, echoed back from the request."
    )
    provider: str | None = Field(
        None, description="Registry key of the provider that produced the records."
    )
    enrichment: DiscoveryEnrichmentStats = Field(
        default_factory=DiscoveryEnrichmentStats,
        description=(
            "What the run actually landed, counted over the leads it wrote. Defaults to "
            "zeroes so a run that collected nothing still answers the same shape."
        ),
    )
