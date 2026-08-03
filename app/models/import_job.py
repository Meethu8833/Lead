"""
app/models/import_job.py

This file defines the SQLAlchemy database model for the ImportJob entity and its supporting
enums. Under Clean Architecture, this file belongs to the Enterprise Domain Model layer.

An `ImportJob` is the audit record of one run of the Lead Collection Engine: one provider,
one query (or one uploaded CSV), and the statistics of what that run did to the `leads`
table. It exists so that a bulk import is never a fire-and-forget mutation of the CRM —
every lead that appears in the pipeline can be traced back to the run that created it, and
every run can be inspected, diagnosed, and retried.

Why the counters are stored rather than derived
-----------------------------------------------
`total_found` / `new_leads` / `updated_leads` / `failed_records` cannot be recomputed from
the `leads` table after the fact. A lead updated by a run is indistinguishable afterwards
from a lead updated by a human, and a record that failed to import leaves no row at all.
The counters are therefore the only durable record of what happened, and the service layer
writes them as it goes.

Why `logs` is JSONB
-------------------
A run produces a variable number of per-record diagnostics (which record failed and why,
which existing lead a duplicate merged into). Storing them as a JSONB array keeps them
queryable (`logs @> ...`) without a second table, and matches the `variables` column on
`WhatsAppTemplate`. This model deliberately does NOT reference any concrete provider: the
`provider` column holds the provider's registry key as a plain string, so adding a new
provider never requires a migration.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    Text,
    Enum,
    Integer,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class ImportJobStatus(str, enum.Enum):
    """
    Enum representing the lifecycle state of one import run.

    Legal transitions (enforced in `LeadImportService`, not by the database):
        PENDING   -> RUNNING | CANCELLED
        RUNNING   -> COMPLETED | PARTIAL | FAILED
        COMPLETED -> (terminal)
        PARTIAL   -> (terminal, but retryable)
        FAILED    -> (terminal, but retryable)
        CANCELLED -> (terminal)

    PARTIAL is distinct from both COMPLETED and FAILED on purpose. A collection run over a
    hundred scraped records where three records were malformed is neither a success nor a
    failure: the ninety-seven good leads are already in the CRM and must not be re-imported
    wholesale, but an operator still needs the run flagged for attention. Retrying a PARTIAL
    run is safe precisely because deduplication makes re-importing the ninety-seven a no-op.
    """
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Statuses from which a job may be retried. A run still in flight must not be retried
#: (it would double-count into the same counters), and a COMPLETED run has nothing to redo.
RETRYABLE_STATUSES: frozenset[ImportJobStatus] = frozenset(
    {ImportJobStatus.FAILED, ImportJobStatus.PARTIAL, ImportJobStatus.CANCELLED}
)

#: Statuses that mean the run is over, one way or another.
TERMINAL_STATUSES: frozenset[ImportJobStatus] = frozenset(
    {
        ImportJobStatus.COMPLETED,
        ImportJobStatus.PARTIAL,
        ImportJobStatus.FAILED,
        ImportJobStatus.CANCELLED,
    }
)


class ImportJob(Base):
    """
    ImportJob database model — one execution of one lead-collection provider.

    Design Decisions:
    - Primary Key ID: UUIDv4, consistent with every other entity in this system.
    - `provider` is a plain string holding the provider registry key (e.g. "google_maps",
      "csv", "mock") rather than an enum. An enum would force a migration and an
      `ALTER TYPE` every time a provider is added, which directly contradicts the
      extensibility requirement this module exists to satisfy. The set of valid values is
      owned by `app/services/lead_providers/`, and validated at the service boundary.
    - `query` is nullable because the CSV provider has no search query; its input is the
      uploaded file, described by `source_filename` instead.
    - The four counters are denormalized statistics maintained by the service layer as the
      run proceeds; see the module docstring for why they cannot be derived later.
    - `retry_of_job_id` is a self-referential FK, so a retried run is a NEW row pointing at
      the run it re-attempts. Overwriting the original would destroy the audit trail of the
      first failure, which is the main thing an operator wants to see when diagnosing why
      an import needed retrying in the first place.
    - Soft delete + optimistic locking, matching the Lead reference model.
    """
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier for the import job (UUIDv4)"
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc=(
            "Registry key of the lead provider that ran (e.g. 'google_maps', 'csv'). "
            "A string rather than an enum so new providers need no migration."
        )
    )

    query: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Search query submitted to the provider. Null for file-based providers (CSV)."
    )

    status: Mapped[ImportJobStatus] = mapped_column(
        Enum(ImportJobStatus, name="import_job_status"),
        default=ImportJobStatus.PENDING,
        server_default=ImportJobStatus.PENDING.value,
        nullable=False,
        index=True,
        doc="Current lifecycle state of the run"
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Timestamp when the run began executing (set on PENDING -> RUNNING)"
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the run reached a terminal status"
    )

    total_found: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Number of raw records the provider returned for this run"
    )

    new_leads: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Number of records that resulted in a newly created Lead row"
    )

    updated_leads: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Number of records that matched an existing Lead and enriched it"
    )

    duplicate_leads: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc=(
            "Number of records that matched an existing Lead but carried nothing new, so "
            "no write occurred. Tracked separately from updated_leads so that "
            "found = new + updated + duplicates + failed always reconciles."
        )
    )

    failed_records: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Number of records that could not be imported (malformed, unusable, or errored)"
    )

    logs: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        doc=(
            "JSON array of structured per-record diagnostics accumulated during the run "
            "(level, message, and optional record identifiers). Written by the service."
        )
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Run-level failure reason, populated when the run itself aborted (status FAILED)"
    )

    source_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Original filename of the uploaded file, for file-based providers (CSV)"
    )

    retry_of_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The job this run re-attempts, if it was created via the retry endpoint"
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Employee who triggered the run (optional; null for system/scheduled runs)"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Soft delete flag"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the job was soft-deleted"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Optimistic locking version number"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the job record was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the job record was last updated"
    )

    __table_args__ = (
        # The import history screen is "latest runs, optionally filtered by provider or
        # status", so both filters are served alongside the descending-time ordering.
        Index("ix_import_jobs_provider_created", "provider", "created_at"),
        Index("ix_import_jobs_status_created", "status", "created_at"),
    )

    # SQLAlchemy mapper configuration for optimistic locking
    __mapper_args__ = {
        "version_id_col": version
    }
