"""
app/api/v1/endpoints/lead_imports.py

This file defines the API routes for the Lead Collection Engine.
Under Clean Architecture, this file resides in the Interface Adapters layer: it parses
requests, delegates to `LeadImportService`, and returns Pydantic-shaped JSON. It holds zero
business logic — deduplication, enrichment and job lifecycle all live in the service.

Routing note
------------
This router is mounted at the root prefix and owns the literal paths `/leads/import*`,
`/leads/imports*` and `/leads/discover`. It MUST be registered before the `leads` router in
`app/api/v1/router.py`, otherwise `GET /leads/imports` is swallowed by `GET /leads/{id}`
and fails as an invalid UUID. This is the same ordering constraint already documented for
`lead_activities.py`. `/leads/discover` is a POST and `/leads/{id}` is not, so that one
route would survive the wrong order by method alone — it lives here regardless, because
splitting the lead-collection path space across two routers is how the ordering constraint
gets forgotten.

Import versus discover
----------------------
`POST /leads/import` names a *provider* and hands it a query; the caller chooses the source
and gets back an `ImportJob` row it can audit later. `POST /leads/discover` names a *city*
and runs the fixed enrichment pipeline `LeadDiscoveryService` owns (collect → find website →
read contacts → normalise → dedup → save), returning five counters and writing no job row.
They share the `leads:import` permission because they have the same blast radius: both write
leads in bulk from an outside source.

Permissions
-----------
Import routes require `leads:import`, not `leads:create`. Bulk-importing hundreds of leads
from an external source is a materially different capability from adding one lead by hand —
different blast radius, different people should hold it — which is the same argument that
kept `whatsapp:*` separate from `leads:*`. Read routes require `leads:view`, since an import
job is a read over the lead pipeline's provenance.
"""

import logging
import uuid
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_db,
    get_current_employee,
    get_lead_discovery_service,
    get_lead_import_service,
    RequirePermission,
)
from app.core.exceptions import AppException, BadRequestException
from app.models.employee import Employee
from app.models.import_job import ImportJobStatus
from app.schemas.import_job import (
    DiscoveryRunRequest,
    DiscoveryRunResponse,
    ImportJobDetailResponse,
    ImportJobListResponse,
    ImportJobResponse,
    ImportRunRequest,
    ImportStatisticsResponse,
    ProviderListResponse,
)
from app.services.lead_discovery import LeadDiscoveryService
from app.services.lead_import import LeadImportService
from app.services.lead_providers import MAX_COLLECTION_LIMIT, list_providers
from app.services.lead_providers.base import ProviderCollectionError

logger = logging.getLogger(__name__)

router = APIRouter()


#: Ceiling on an uploaded CSV, enforced before parsing. A lead CSV is a few hundred KB at
#: most; anything far larger is a mistaken upload, and reading it into memory to find that
#: out is exactly the failure mode worth avoiding.
MAX_CSV_BYTES = 10 * 1024 * 1024


@router.get(
    "/leads/import/providers",
    response_model=ProviderListResponse,
    status_code=status.HTTP_200_OK,
    summary="List available lead collection providers",
    description=(
        "Returns every registered lead provider with its capabilities. Providers with "
        "`is_available: false` are declared sources with no implementation yet and will be "
        "refused if requested."
    ),
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_providers() -> ProviderListResponse:
    """
    GET /leads/import/providers Endpoint Flow:
    Reads the in-process provider registry. Touches no database.
    """
    items = list_providers()
    return ProviderListResponse(items=items, total=len(items))


@router.post(
    "/leads/import",
    response_model=ImportJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run a lead collection import",
    description=(
        "Runs one collection import through the named provider and returns the finished "
        "import job, including its per-record log. Collected records are deduplicated "
        "against existing leads by phone, email, and business name + city; a match enriches "
        "the existing lead's empty fields instead of creating a duplicate."
    ),
    dependencies=[Depends(RequirePermission("leads:import"))],
)
async def run_import(
    schema: ImportRunRequest,
    db: AsyncSession = Depends(get_db),
    service: LeadImportService = Depends(get_lead_import_service),
    current_employee: Employee = Depends(get_current_employee),
) -> ImportJobDetailResponse:
    """
    POST /leads/import Endpoint Flow:
    Client JSON -> validated request -> service resolves the provider, collects, dedups,
    persists -> returns the completed job.

    The run is synchronous: the caller gets the finished job with its statistics rather
    than a job id to poll. Providers are bounded by `limit` (max
    `MAX_COLLECTION_LIMIT`), so a run is short by construction. Moving collection onto a
    background worker is the natural next step once a real network-bound provider lands,
    and the ImportJob lifecycle (PENDING -> RUNNING -> terminal) is already shaped for it.
    """
    return await service.run_import(
        db=db,
        provider_key=schema.provider,
        query=schema.query,
        limit=schema.limit,
        city=schema.city,
        state=schema.state,
        options=schema.options,
        created_by=current_employee.id,
    )


@router.post(
    "/leads/import/csv",
    response_model=ImportJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import leads from an uploaded CSV file",
    description=(
        "Uploads a CSV of leads and imports it through the CSV provider. Column headers are "
        "matched case-insensitively against a set of known aliases (e.g. 'Business Name', "
        "'business_name', 'Studio'); a cell may hold several phone numbers or emails "
        "separated by comma, semicolon, pipe or slash. The same duplicate detection applies "
        "as for any other provider."
    ),
    dependencies=[Depends(RequirePermission("leads:import"))],
)
async def import_csv(
    file: UploadFile = File(..., description="CSV file containing lead rows"),
    limit: int = Form(
        MAX_COLLECTION_LIMIT,
        ge=1,
        le=MAX_COLLECTION_LIMIT,
        description="Maximum number of rows to import from the file",
    ),
    db: AsyncSession = Depends(get_db),
    service: LeadImportService = Depends(get_lead_import_service),
    current_employee: Employee = Depends(get_current_employee),
) -> ImportJobDetailResponse:
    """
    POST /leads/import/csv Endpoint Flow:
    Multipart upload -> bytes read and size-checked here -> CSV provider parses and
    normalizes -> service dedups and persists -> returns the completed job.

    The file is read fully into memory because it is bounded by `MAX_CSV_BYTES` and the CSV
    provider needs the whole text to sniff its delimiter and header row.
    """
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith((".csv", ".txt")):
        raise BadRequestException(
            f"'{filename}' is not a CSV file. Please upload a .csv file."
        )

    content = await file.read()
    if not content:
        raise BadRequestException("The uploaded file is empty.")
    if len(content) > MAX_CSV_BYTES:
        raise BadRequestException(
            f"The uploaded file is {len(content) // 1024} KB, which exceeds the "
            f"{MAX_CSV_BYTES // (1024 * 1024)} MB limit."
        )

    return await service.run_import(
        db=db,
        provider_key="csv",
        limit=limit,
        file_content=content,
        filename=filename,
        created_by=current_employee.id,
    )


@router.get(
    "/leads/imports",
    response_model=ImportJobListResponse,
    status_code=status.HTTP_200_OK,
    summary="List import jobs",
    description=(
        "Fetches a paginated history of import runs, newest first. Supports filtering by "
        "provider, status, and created date range. Per-record logs are omitted here; fetch "
        "a single job to see them."
    ),
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_import_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    provider: str | None = Query(None, description="Filter by provider key"),
    status_filter: ImportJobStatus | None = Query(None, alias="status", description="Filter by job status"),
    created_from: datetime | None = Query(None, description="Filter by created_at >= this timestamp"),
    created_to: datetime | None = Query(None, description="Filter by created_at <= this timestamp"),
    db: AsyncSession = Depends(get_db),
    service: LeadImportService = Depends(get_lead_import_service),
) -> ImportJobListResponse:
    """
    GET /leads/imports Endpoint Flow:
    Service -> Repository -> paginated, filtered job history + total count.
    """
    items, total = await service.get_all_jobs(
        db=db,
        skip=skip,
        limit=limit,
        provider=provider,
        status=status_filter,
        created_from=created_from,
        created_to=created_to,
    )
    return ImportJobListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/leads/imports/statistics",
    response_model=ImportStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Aggregate import statistics",
    description="Returns lifetime totals across every import run, plus a per-status job count.",
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_import_statistics(
    db: AsyncSession = Depends(get_db),
    service: LeadImportService = Depends(get_lead_import_service),
) -> ImportStatisticsResponse:
    """
    GET /leads/imports/statistics Endpoint Flow:
    Aggregated in SQL by the repository; registered before `/leads/imports/{id}` so the
    literal path is not parsed as a job UUID.
    """
    stats = await service.get_statistics(db=db)
    return ImportStatisticsResponse(**stats)


@router.get(
    "/leads/imports/{id}",
    response_model=ImportJobDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an import job by ID",
    description="Retrieves one import run including its full per-record diagnostic log. Raises 404 if not found.",
    dependencies=[Depends(RequirePermission("leads:view"))],
)
async def get_import_job(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: LeadImportService = Depends(get_lead_import_service),
) -> ImportJobDetailResponse:
    """
    GET /leads/imports/{id} Endpoint Flow:
    Retrieves a single job by UUID, with logs.
    """
    return await service.get_job_by_id(db=db, id=id)


@router.post(
    "/leads/imports/{id}/retry",
    response_model=ImportJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Retry a failed or partial import job",
    description=(
        "Re-runs a finished job's request as a new job linked back to the original via "
        "`retry_of_job_id`. Only FAILED, PARTIAL and CANCELLED jobs are retryable. Retrying "
        "is safe: leads the original run already imported are matched by deduplication "
        "rather than re-created. File-upload jobs cannot be retried because the uploaded "
        "bytes are not retained — re-upload the file instead."
    ),
    dependencies=[Depends(RequirePermission("leads:import"))],
)
async def retry_import_job(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: LeadImportService = Depends(get_lead_import_service),
    current_employee: Employee = Depends(get_current_employee),
) -> ImportJobDetailResponse:
    """
    POST /leads/imports/{id}/retry Endpoint Flow:
    Validates the original job is retryable -> re-runs its request as a new job -> returns
    the new job.
    """
    return await service.retry_job(db=db, id=id, created_by=current_employee.id)


@router.post(
    "/leads/discover",
    response_model=DiscoveryRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Discover and import leads for a city",
    responses={
        400: {
            "description": (
                "The request cannot be serviced: unknown city, unusable radius, or a "
                "provider that is declared but not implemented."
            )
        },
        403: {"description": "Caller lacks the `leads:import` permission."},
        422: {"description": "Request body failed validation (e.g. `radius_km` <= 0)."},
        502: {
            "description": (
                "The upstream discovery source could not be reached or returned an "
                "unusable response. Nothing was collected and nothing was written."
            )
        },
    },
    description=(
        "Runs the full lead discovery pipeline for one city and returns what it did.\n\n"
        "The pipeline collects businesses from OpenStreetMap around the geocoded city, "
        "finds the official website of those without one, reads the contacts those sites "
        "publish, canonicalises phones and emails, deduplicates the result against existing "
        "leads, and saves what is new.\n\n"
        "The five returned counters always reconcile: "
        "`imported + merged + duplicates + failed == found`. A record that matches an "
        "existing lead and fills in at least one empty field counts as `merged`, not "
        "`imported`; one that matches and adds nothing counts as `duplicates`. Records with "
        "no business name or no phone number count as `failed` — they are unusable as leads "
        "rather than lost.\n\n"
        "The run is synchronous and network-bound: it geocodes the city, queries Overpass, "
        "and may fetch one page per discovered website, so a large `limit` with both "
        "enrichment stages on takes appreciable time. Set `discover_websites` or "
        "`extract_contacts` to false to skip those stages."
    ),
    dependencies=[Depends(RequirePermission("leads:import"))],
)
async def discover_leads(
    schema: DiscoveryRunRequest,
    db: AsyncSession = Depends(get_db),
    service: LeadDiscoveryService = Depends(get_lead_discovery_service),
    current_employee: Employee = Depends(get_current_employee),
) -> DiscoveryRunResponse:
    """
    POST /leads/discover Endpoint Flow:
    Client JSON -> validated request -> LeadDiscoveryService.run() executes the six-stage
    pipeline against a real session -> the summary's five counters are returned.

    `category` and `radius_km` travel in `options`, which is the channel the provider
    contract defines for per-adapter extras; the Overpass adapter reads both from there and
    is the authority on defaulting and clamping the radius. `radius_km` is omitted from
    `options` entirely when the caller did not supply one, so the adapter applies its own
    default rather than receiving a None it would have to interpret.

    The response carries the five counters and, alongside them, the records behind three of
    them: `imported_records`, `merged_records` and `failed_records`. Those come from
    `summary.to_response_dict()`, which the service builds at its write sites — this
    function does no projection of its own, and `merged_records` in particular could not be
    rebuilt here, since the enriched-field list only exists during planning.

    `ProviderCollectionError` is translated here rather than left to propagate. It is not a
    caller error and not a bug — it means the donated public endpoint was unreachable or
    answered with something unusable — so it maps to 502 with the source named. Letting it
    reach the generic handler would report a source outage as an internal server error and
    send an operator looking in the wrong place. `BadRequestException` from the provider's
    own validation is already an `AppException` and is left to the global handler, which
    renders it as the 400 documented above.
    """
    options: dict[str, Any] = {}
    if schema.category:
        options["category"] = schema.category
    if schema.radius_km is not None:
        options["radius_km"] = schema.radius_km

    logger.info(
        "Lead discovery requested for city=%r category=%r radius_km=%s by employee %s",
        schema.city, schema.category, schema.radius_km, current_employee.id,
    )

    try:
        summary = await service.run(
            db=db,
            city=schema.city,
            query=schema.category,
            limit=schema.limit,
            state=schema.state,
            options=options,
            discover_websites=schema.discover_websites,
            extract_contacts=schema.extract_contacts,
        )
    except ProviderCollectionError as exc:
        logger.warning("Lead discovery for %r failed at the source: %s", schema.city, exc)
        raise AppException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lead discovery source unavailable: {exc}",
            error_code="DISCOVERY_SOURCE_UNAVAILABLE",
        ) from exc

    return DiscoveryRunResponse(**summary.to_response_dict())
