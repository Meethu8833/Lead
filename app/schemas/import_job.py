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
from pydantic import BaseModel, Field, field_validator

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
