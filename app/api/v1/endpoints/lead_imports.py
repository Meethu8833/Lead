"""
app/api/v1/endpoints/lead_imports.py

This file defines the API routes for the Lead Collection Engine.
Under Clean Architecture, this file resides in the Interface Adapters layer: it parses
requests, delegates to `LeadImportService`, and returns Pydantic-shaped JSON. It holds zero
business logic — deduplication, enrichment and job lifecycle all live in the service.

Routing note
------------
This router is mounted at the root prefix and owns the literal paths `/leads/import*` and
`/leads/imports*`. It MUST be registered before the `leads` router in
`app/api/v1/router.py`, otherwise `GET /leads/imports` is swallowed by `GET /leads/{id}`
and fails as an invalid UUID. This is the same ordering constraint already documented for
`lead_activities.py`.

Permissions
-----------
Import routes require `leads:import`, not `leads:create`. Bulk-importing hundreds of leads
from an external source is a materially different capability from adding one lead by hand —
different blast radius, different people should hold it — which is the same argument that
kept `whatsapp:*` separate from `leads:*`. Read routes require `leads:view`, since an import
job is a read over the lead pipeline's provenance.
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_employee, get_lead_import_service, RequirePermission
from app.core.exceptions import BadRequestException
from app.models.employee import Employee
from app.models.import_job import ImportJobStatus
from app.schemas.import_job import (
    ImportJobDetailResponse,
    ImportJobListResponse,
    ImportJobResponse,
    ImportRunRequest,
    ImportStatisticsResponse,
    ProviderListResponse,
)
from app.services.lead_import import LeadImportService
from app.services.lead_providers import MAX_COLLECTION_LIMIT, list_providers

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
