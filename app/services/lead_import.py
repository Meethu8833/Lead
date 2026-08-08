"""
app/services/lead_import.py

This file implements the `LeadImportService` — the use case at the centre of the Lead
Collection Engine.

Under Clean Architecture this is the Application Business Rules layer. It orchestrates a
provider (the port in `app/services/lead_providers/base.py`), the duplicate rules, the
`leads` table and the `import_jobs` audit record. It is the *only* place that knows how a
`NormalizedLead` becomes a `Lead` row, and it contains no knowledge whatsoever of any
concrete source: providers are resolved by string key through the registry, which is what
allows a new source to be added without editing this file.

The three duplicate rules
-------------------------
Before inserting, an incoming record is matched against existing leads on:
  1. phone number (any of the record's numbers, against both `phone` and `whatsapp`),
  2. email address (any of the record's addresses),
  3. business name + city.

All three are evaluated in one query (see `LeadRepository.find_duplicate_candidates`) and
ranked here by confidence: phone beats email beats name+city. Phone ranks highest because
it is the CRM's unique key and the channel the business is actually contacted on; name+city
ranks lowest because it is the only rule that can match two genuinely different businesses
(a chain with two branches in one city), so it must never override a contact-level match.

Enrichment, not overwrite
-------------------------
When a record matches an existing lead, the lead is *enriched*: only fields that are
currently empty are filled in. A collected record never overwrites data already in the CRM,
because the existing value may have been typed by a human who phoned the business, and a
scraped listing is not evidence strong enough to discard that. The one deliberate exception
is documented on `_build_enrichment`. If a match carries nothing new, no write happens at
all and the record is counted as a duplicate rather than an update — which is what makes
re-running the same import a genuine no-op instead of a version-number churn.

Within-batch deduplication
--------------------------
Records are also matched against leads created earlier *in the same run*, not just against
the pre-existing table. A single scrape routinely returns the same studio twice under two
phone formats; without this, the second occurrence would be inserted and immediately
violate the `phone` unique constraint, or worse, slip through under a different number and
create the duplicate this module exists to prevent.

Transaction shape
-----------------
Each record is committed on its own rather than the run being one big transaction. A
collection run is long and partially-successful by nature: record 150 failing must not roll
back the 149 leads already imported, because the operator's alternative is re-running the
whole scrape. This is the same reasoning as the per-recipient isolation in
`WhatsAppCampaignService`, and it is why `ImportJobStatus.PARTIAL` exists.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.import_job import (
    ImportJob,
    ImportJobStatus,
    RETRYABLE_STATUSES,
)
from app.models.lead import Lead, LeadSource, LeadStatus
from app.repositories.import_job import ImportJobRepository
from app.repositories.lead import LeadRepository
from app.services.lead_activity import LeadActivityService
from app.services.lead_providers import (
    LeadProvider,
    NormalizedLead,
    ProviderCollectionError,
    ProviderContext,
    get_provider,
)

logger = logging.getLogger(__name__)


#: Confidence ranking of the duplicate rules. Higher wins when several rules fire; see the
#: module docstring for why phone outranks name+city.
MATCH_RULE_RANK: dict[str, int] = {
    "business_name_city": 1,
    "email": 2,
    "phone": 3,
}

#: Lead columns the enrichment step may fill when they are empty. `phone` is absent on
#: purpose: it is the CRM's unique key and the thing the match was made on, so rewriting it
#: could collide with another lead's number. `status`, `is_converted` and
#: `assigned_employee_id` are absent because they are CRM workflow state that no external
#: source has any business touching.
ENRICHABLE_FIELDS: tuple[str, ...] = (
    "contact_person",
    "whatsapp",
    "email",
    "instagram",
    "facebook",
    "website",
    "address",
    "city",
    "district",
    "state",
    "country",
    "latitude",
    "longitude",
)


def _log_entry(level: str, message: str, **extra: Any) -> dict[str, Any]:
    """
    Builds one structured entry for the job's `logs` array.

    Entries are dicts rather than strings so the array stays queryable and the UI can
    render failures differently from informational lines, and every entry is timestamped
    because a long run's log is read after the fact.
    """
    entry: dict[str, Any] = {
        "level": level,
        "message": message,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    entry.update({k: v for k, v in extra.items() if v is not None})
    return entry


class LeadImportService:
    """
    Service layer orchestrating provider-based lead collection.

    Responsibilities:
    - Create and drive the `ImportJob` audit record through its lifecycle.
    - Resolve the requested provider through the registry and run it.
    - Apply the three duplicate rules, then create or enrich accordingly.
    - Maintain the run's statistics and diagnostic log.
    """

    def __init__(
        self,
        job_repository: ImportJobRepository | None = None,
        lead_repository: LeadRepository | None = None,
        activity_service: LeadActivityService | None = None,
    ) -> None:
        self.job_repository = job_repository or ImportJobRepository()
        self.lead_repository = lead_repository or LeadRepository()
        self.activity_service = activity_service or LeadActivityService()

    # -----------------------------------------------------------------------------------
    # Job lifecycle
    # -----------------------------------------------------------------------------------

    async def run_import(
        self,
        db: AsyncSession,
        provider_key: str,
        query: str | None = None,
        limit: int = 100,
        city: str | None = None,
        state: str | None = None,
        file_content: bytes | None = None,
        filename: str | None = None,
        options: dict[str, Any] | None = None,
        created_by: uuid.UUID | None = None,
        retry_of_job_id: uuid.UUID | None = None,
        provider: LeadProvider | None = None,
    ) -> ImportJob:
        """
        Executes one complete import run and returns its finished `ImportJob`.

        The provider is resolved and its request validated *before* the job row is created,
        so a bad request (unknown provider, missing query, planned-but-unimplemented source)
        raises a 400 and leaves no misleading FAILED job behind. Once a job exists, every
        subsequent failure is recorded on it rather than raised, because from that point on
        the job row is the operator's record of what happened.

        Args:
            provider: An explicit provider instance, bypassing registry resolution. Exists
                so tests can inject a double; production callers pass only `provider_key`.

        Raises:
            BadRequestException: the request cannot be serviced by the named provider.
        """
        resolved = provider or get_provider(provider_key)
        # `search()` validates and returns the run's context. Deliberately outside the job
        # row's lifetime — see above.
        context = resolved.search(
            query,
            limit=limit,
            city=city,
            state=state,
            file_content=file_content,
            filename=filename,
            options=options or {},
        )

        job = ImportJob(
            provider=resolved.key,
            query=context.query,
            status=ImportJobStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            source_filename=filename,
            retry_of_job_id=retry_of_job_id,
            created_by=created_by,
            logs=[
                _log_entry(
                    "info",
                    f"Import started via provider '{resolved.key}'.",
                    query=context.query,
                    limit=context.limit,
                    filename=filename,
                )
            ],
        )
        job = await self.job_repository.create(db, job)

        try:
            records = await resolved.collect_normalized(context)
        except ProviderCollectionError as exc:
            # A source-level fault: nothing was collected, so the run failed outright.
            return await self._finalize_failed(db, job, str(exc))
        except Exception as exc:  # noqa: BLE001 - an adapter fault must not 500 the API
            logger.exception("Provider '%s' failed during collection.", resolved.key)
            return await self._finalize_failed(
                db, job, f"Unexpected provider error: {exc}"
            )

        return await self._process_records(db, job, records, resolved)

    async def _process_records(
        self,
        db: AsyncSession,
        job: ImportJob,
        records: Sequence[NormalizedLead],
        provider: LeadProvider,
    ) -> ImportJob:
        """
        Applies deduplication and persistence to every collected record, maintaining the
        run's counters and log, then finalises the job's status.

        Each record is handled in isolation: an exception on one is caught, counted as a
        failed record with its reason logged, and the run continues. See the module
        docstring on transaction shape.
        """
        entries: list[dict[str, Any]] = []
        counts = {"new": 0, "updated": 0, "duplicate": 0, "failed": 0}

        # Leads created during this run, so later records in the same batch dedup against
        # them. Keyed by every identifier the new lead now owns.
        seen_phone_keys: dict[str, uuid.UUID] = {}
        seen_email_keys: dict[str, uuid.UUID] = {}
        seen_business_keys: dict[str, uuid.UUID] = {}

        for index, record in enumerate(records):
            position = index + 1
            row_number = (record.raw or {}).get("row_number")
            label = f"row {row_number}" if row_number else f"record {position}"

            try:
                valid, reason = record.is_valid()
                if not valid:
                    counts["failed"] += 1
                    entries.append(
                        _log_entry(
                            "error",
                            f"{label}: skipped — {reason}",
                            business_name=record.business_name,
                            row_number=row_number,
                        )
                    )
                    continue

                # 1. Within-batch match, so one run cannot create two rows for one business.
                batch_match_id = self._match_within_batch(
                    record, seen_phone_keys, seen_email_keys, seen_business_keys
                )

                # 2. Match against what is already in the CRM.
                existing, rule = await self._find_best_match(db, record)

                if batch_match_id and not existing:
                    existing = await self.lead_repository.get_by_id(db, batch_match_id)
                    rule = "batch"

                if existing:
                    enrichment = self._build_enrichment(existing, record)
                    if enrichment:
                        await self.lead_repository.update(
                            db, db_obj=existing, update_data=enrichment
                        )
                        counts["updated"] += 1
                        entries.append(
                            _log_entry(
                                "info",
                                f"{label}: matched existing lead by {rule}; enriched "
                                f"{len(enrichment)} field(s).",
                                lead_id=str(existing.id),
                                business_name=record.business_name,
                                match_rule=rule,
                                fields=sorted(enrichment),
                                row_number=row_number,
                            )
                        )
                    else:
                        counts["duplicate"] += 1
                        entries.append(
                            _log_entry(
                                "info",
                                f"{label}: duplicate of an existing lead by {rule}; "
                                f"nothing new to add.",
                                lead_id=str(existing.id),
                                business_name=record.business_name,
                                match_rule=rule,
                                row_number=row_number,
                            )
                        )
                    self._remember(
                        existing.id, record, seen_phone_keys, seen_email_keys, seen_business_keys
                    )
                    continue

                # 3. No match anywhere: create.
                lead = await self._create_lead(db, record, provider)
                counts["new"] += 1
                entries.append(
                    _log_entry(
                        "info",
                        f"{label}: created new lead.",
                        lead_id=str(lead.id),
                        business_name=record.business_name,
                        row_number=row_number,
                    )
                )
                self._remember(
                    lead.id, record, seen_phone_keys, seen_email_keys, seen_business_keys
                )

            except Exception as exc:  # noqa: BLE001 - per-record isolation, see docstring
                logger.exception("Import record %s failed.", label)
                # The failed write may have poisoned the session; clear it so the remaining
                # records still have a usable transaction.
                await db.rollback()
                counts["failed"] += 1
                entries.append(
                    _log_entry(
                        "error",
                        f"{label}: failed — {exc}",
                        business_name=record.business_name,
                        row_number=row_number,
                    )
                )

        return await self._finalize(db, job, records, counts, entries)

    async def _finalize(
        self,
        db: AsyncSession,
        job: ImportJob,
        records: Sequence[NormalizedLead],
        counts: dict[str, int],
        entries: list[dict[str, Any]],
    ) -> ImportJob:
        """
        Writes the run's final counters, status and log in a single update.

        Status is COMPLETED when nothing failed, FAILED when everything failed and there
        was something to do, and PARTIAL in between — the distinction an operator needs to
        decide whether to retry. A run that collected zero records is COMPLETED, not
        FAILED: "this query matched nothing" is a successful, correct answer.
        """
        total = len(records)
        failed = counts["failed"]

        if failed == 0:
            status = ImportJobStatus.COMPLETED
        elif failed == total:
            status = ImportJobStatus.FAILED
        else:
            status = ImportJobStatus.PARTIAL

        entries.append(
            _log_entry(
                "info",
                (
                    f"Import finished: {total} found, {counts['new']} new, "
                    f"{counts['updated']} updated, {counts['duplicate']} duplicates, "
                    f"{failed} failed."
                ),
            )
        )

        job.logs = list(job.logs or []) + entries
        return await self.job_repository.update(
            db,
            db_obj=job,
            update_data={
                "status": status,
                "completed_at": datetime.now(timezone.utc),
                "total_found": total,
                "new_leads": counts["new"],
                "updated_leads": counts["updated"],
                "duplicate_leads": counts["duplicate"],
                "failed_records": failed,
                "error_message": (
                    "Every collected record failed to import."
                    if status is ImportJobStatus.FAILED
                    else None
                ),
            },
        )

    async def _finalize_failed(
        self, db: AsyncSession, job: ImportJob, message: str
    ) -> ImportJob:
        """
        Marks a run FAILED because the source itself could not be read. No records were
        collected, so all counters stay at zero and the reason lands in `error_message`
        where the job-detail endpoint surfaces it.
        """
        job.logs = list(job.logs or []) + [
            _log_entry("error", f"Collection failed: {message}")
        ]
        return await self.job_repository.update(
            db,
            db_obj=job,
            update_data={
                "status": ImportJobStatus.FAILED,
                "completed_at": datetime.now(timezone.utc),
                "error_message": message,
            },
        )

    # -----------------------------------------------------------------------------------
    # Deduplication
    # -----------------------------------------------------------------------------------

    async def _find_best_match(
        self, db: AsyncSession, record: NormalizedLead
    ) -> tuple[Lead | None, str | None]:
        """
        Returns the existing lead this record is a duplicate of, plus the rule that matched.

        Candidates come back from one OR'd query; this method then decides *which* rule
        each candidate satisfies and picks the highest-confidence one (phone > email >
        name+city). Ties are broken by the most recently created lead, matching the
        repository's ordering, so behaviour is deterministic when a record genuinely
        matches two leads equally well.

        Returns (None, None) when the record is new.
        """
        phone_keys = set(record.phone_keys)
        email_keys = set(record.email_keys)
        business_key = record.business_key

        candidates = await self.lead_repository.find_duplicate_candidates(
            db,
            phone_keys=list(phone_keys),
            email_keys=list(email_keys),
            business_key=business_key,
        )
        if not candidates:
            return None, None

        best: Lead | None = None
        best_rank = 0
        best_rule: str | None = None

        for candidate in candidates:
            rule = self._classify_match(candidate, phone_keys, email_keys, business_key)
            if rule is None:
                continue
            rank = MATCH_RULE_RANK[rule]
            if rank > best_rank:
                best, best_rank, best_rule = candidate, rank, rule

        return best, best_rule

    @staticmethod
    def _classify_match(
        candidate: Lead,
        phone_keys: set[str],
        email_keys: set[str],
        business_key: str | None,
    ) -> str | None:
        """
        Reports which duplicate rule a candidate satisfies, highest confidence first.

        Recomputed in Python rather than returned by the query because the SQL uses one OR
        and cannot say which arm fired; and because the rule name is what gets written into
        the job log for the operator, so it must be exact.
        """
        from app.services.lead_providers.normalized import (
            normalize_business_key,
            normalize_email,
            normalize_phone,
        )

        if phone_keys:
            for stored in (candidate.phone, candidate.whatsapp):
                key = normalize_phone(stored)
                if key and key in phone_keys:
                    return "phone"

        if email_keys:
            key = normalize_email(candidate.email)
            if key and key in email_keys:
                return "email"

        if business_key:
            key = normalize_business_key(candidate.business_name, candidate.city)
            if key and key == business_key:
                return "business_name_city"

        return None

    @staticmethod
    def _match_within_batch(
        record: NormalizedLead,
        seen_phone_keys: dict[str, uuid.UUID],
        seen_email_keys: dict[str, uuid.UUID],
        seen_business_keys: dict[str, uuid.UUID],
    ) -> uuid.UUID | None:
        """
        Returns the id of a lead already touched by this run that the record duplicates,
        applying the same rule precedence as the database match.
        """
        for key in record.phone_keys:
            if key in seen_phone_keys:
                return seen_phone_keys[key]
        for key in record.email_keys:
            if key in seen_email_keys:
                return seen_email_keys[key]
        business_key = record.business_key
        if business_key and business_key in seen_business_keys:
            return seen_business_keys[business_key]
        return None

    @staticmethod
    def _remember(
        lead_id: uuid.UUID,
        record: NormalizedLead,
        seen_phone_keys: dict[str, uuid.UUID],
        seen_email_keys: dict[str, uuid.UUID],
        seen_business_keys: dict[str, uuid.UUID],
    ) -> None:
        """
        Registers every identifier a record contributed, against the lead it landed on, so
        subsequent records in the same run match it.
        """
        for key in record.phone_keys:
            seen_phone_keys.setdefault(key, lead_id)
        for key in record.email_keys:
            seen_email_keys.setdefault(key, lead_id)
        business_key = record.business_key
        if business_key:
            seen_business_keys.setdefault(business_key, lead_id)

    # -----------------------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------------------

    @staticmethod
    def _build_enrichment(existing: Lead, record: NormalizedLead) -> dict[str, Any]:
        """
        Computes the fill-in-the-blanks update for a matched lead: every enrichable field
        that is currently empty on the lead and non-empty on the record.

        Returns an empty dict when the record adds nothing, which is what lets the caller
        distinguish an update from a pure duplicate and skip the write entirely.

        The deliberate exception to "never overwrite" is `whatsapp`: if the lead has no
        WhatsApp number and the record's *primary* phone differs from the lead's stored
        phone, that second number is recorded as the WhatsApp number rather than discarded.
        This is the only way a second contact number collected later can be retained at
        all, given the CRM stores exactly two.
        """
        candidate_values: dict[str, Any] = {
            "contact_person": record.owner_name,
            "whatsapp": record.secondary_phone,
            "email": record.primary_email,
            "instagram": record.instagram,
            "facebook": record.facebook,
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
            from app.services.lead_providers.normalized import normalize_phone

            incoming = normalize_phone(record.primary_phone)
            stored = normalize_phone(existing.phone)
            if incoming and incoming != stored:
                candidate_values["whatsapp"] = record.primary_phone

        enrichment: dict[str, Any] = {}
        for field_name in ENRICHABLE_FIELDS:
            new_value = candidate_values.get(field_name)
            if new_value in (None, ""):
                continue
            current = getattr(existing, field_name, None)
            if current in (None, ""):
                enrichment[field_name] = new_value

        return enrichment

    async def _create_lead(
        self, db: AsyncSession, record: NormalizedLead, provider: LeadProvider
    ) -> Lead:
        """
        Creates a Lead row from a normalized record.

        The record's `source` is mapped onto the `LeadSource` enum, falling back to the
        provider's declared source and then to OTHER, so an adapter that forgets to set
        `source` still produces correctly-attributed leads rather than failing.

        The collected extras that the `leads` table has no column for — rating, review
        count, categories, pincode, source URL — are folded into `remarks` rather than
        dropped. That keeps this phase strictly additive: no ERP-adjacent schema is widened
        to hold scrape metadata, and the information stays visible to whoever works the lead.
        """
        source = self._resolve_source(record.source or provider.lead_source)

        lead = Lead(
            business_name=record.business_name,
            contact_person=record.owner_name,
            phone=record.primary_phone,
            whatsapp=record.secondary_phone,
            email=record.primary_email,
            instagram=record.instagram,
            facebook=record.facebook,
            youtube=record.youtube,
            website=record.website,
            address=record.address,
            city=record.city,
            district=record.district,
            state=record.state,
            country=record.country,
            latitude=record.latitude,
            longitude=record.longitude,
            source=source,
            status=LeadStatus.NEW,
            remarks=self._build_remarks(record),
            is_converted=False,
        )
        lead = await self.lead_repository.create(db, lead)
        await self.activity_service.log_created(db, lead)
        return lead

    @staticmethod
    def _resolve_source(value: str | None) -> LeadSource:
        """
        Maps a provider's declared source string onto the `LeadSource` enum, defaulting to
        OTHER for a value the enum does not carry. Falling back rather than raising means a
        new provider can be added and run before anyone decides whether it deserves its own
        enum member.
        """
        if not value:
            return LeadSource.OTHER
        try:
            return LeadSource(value.strip().upper())
        except ValueError:
            return LeadSource.OTHER

    @staticmethod
    def _build_remarks(record: NormalizedLead) -> str | None:
        """
        Renders the collected fields that have no dedicated Lead column into a short,
        human-readable remarks block. Returns None when there is nothing extra to say, so
        a lead's remarks are not padded with an empty header.
        """
        parts: list[str] = []
        if record.rating is not None:
            rating_text = f"Rating: {record.rating}"
            if record.review_count is not None:
                rating_text += f" ({record.review_count} reviews)"
            parts.append(rating_text)
        elif record.review_count is not None:
            parts.append(f"Reviews: {record.review_count}")
        if record.categories:
            parts.append(f"Categories: {', '.join(record.categories)}")
        if record.pincode:
            parts.append(f"Pincode: {record.pincode}")
        if record.source_url:
            parts.append(f"Source: {record.source_url}")
        if len(record.phone_numbers) > 2:
            # Numbers beyond phone + whatsapp have nowhere else to go.
            parts.append(f"Other numbers: {', '.join(record.phone_numbers[2:])}")
        if len(record.emails) > 1:
            parts.append(f"Other emails: {', '.join(record.emails[1:])}")

        if not parts:
            return None
        return "Imported via lead collection.\n" + "\n".join(parts)

    # -----------------------------------------------------------------------------------
    # Reads and retry
    # -----------------------------------------------------------------------------------

    async def get_job_by_id(self, db: AsyncSession, id: uuid.UUID) -> ImportJob:
        """
        Retrieves one import job. Raises NotFoundException if it does not exist.
        """
        job = await self.job_repository.get_by_id(db, id)
        if not job:
            raise NotFoundException(f"Import job with ID '{id}' was not found.")
        return job

    async def get_all_jobs(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        provider: str | None = None,
        status: ImportJobStatus | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[Sequence[ImportJob], int]:
        """
        Retrieves a paginated, filtered list of import jobs, newest first.
        """
        return await self.job_repository.get_all(
            db,
            skip=skip,
            limit=limit,
            provider=provider,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )

    async def get_statistics(self, db: AsyncSession) -> dict[str, Any]:
        """
        Retrieves lifetime aggregate statistics across every import run.
        """
        return await self.job_repository.get_statistics(db)

    async def retry_job(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        created_by: uuid.UUID | None = None,
        provider: LeadProvider | None = None,
    ) -> ImportJob:
        """
        Re-runs a finished job's request as a NEW job linked back to the original.

        Retrying creates a new row rather than resetting the old one so the record of the
        first failure survives; see `ImportJob.retry_of_job_id`.

        Retrying is safe by construction: deduplication means the leads the original run
        already imported are matched, not re-created, so a PARTIAL run can be retried whole
        without worrying about the part that succeeded.

        Raises:
            ConflictException: the job is still running, or already succeeded and so has
                nothing to redo.
            BadRequestException: the original was a file upload, whose bytes are not
                retained and therefore cannot be replayed.
        """
        original = await self.get_job_by_id(db, id)

        if original.status not in RETRYABLE_STATUSES:
            raise ConflictException(
                f"Import job '{id}' has status {original.status.value} and cannot be "
                f"retried. Only "
                f"{', '.join(sorted(s.value for s in RETRYABLE_STATUSES))} jobs are retryable."
            )

        if original.source_filename:
            # Storing uploaded files just to enable replay would turn the CRM into a
            # document store and duplicate data the operator already has. Re-uploading is
            # the correct path, and dedup makes it harmless.
            raise BadRequestException(
                f"Import job '{id}' was a file upload ('{original.source_filename}'). "
                f"File contents are not retained, so please re-upload the file instead."
            )

        return await self.run_import(
            db,
            provider_key=original.provider,
            query=original.query,
            created_by=created_by,
            retry_of_job_id=original.id,
            provider=provider,
        )
