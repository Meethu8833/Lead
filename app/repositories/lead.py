"""
app/repositories/lead.py

This file implements the LeadRepository.
Under Clean Architecture, this file belongs to the Interface Adapters layer.
It encapsulates SQL database access (via SQLAlchemy 2.0) and translates database rows
into rich objects (or models) that can be consumed by the business logic (Services).
By isolating SQL statements here, we keep services free of data access technologies.
"""

import re
import uuid
from typing import Sequence
from datetime import datetime, timezone
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lead import Lead, LeadStatus, LeadSource


class LeadRepository:
    """
    Lead Repository.
    Handles CRUD operations and advanced querying on the leads database table.
    """

    def __init__(self, include_deleted: bool = False) -> None:
        self.include_deleted = include_deleted

    async def create(self, db: AsyncSession, lead: Lead) -> Lead:
        """
        Persists a new Lead record to the database.
        """
        db.add(lead)
        await db.commit()
        await db.refresh(lead)
        return lead

    async def get_by_id(self, db: AsyncSession, id: uuid.UUID, include_deleted: bool | None = None) -> Lead | None:
        """
        Fetches a single Lead by its UUID.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Lead).where(Lead.id == id)
        if not inc:
            query = query.where(Lead.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_phone(self, db: AsyncSession, phone: str, include_deleted: bool | None = None) -> Lead | None:
        """
        Fetches a Lead by its phone number (unique constraint).
        Used for validation during creation/update.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted
        query = select(Lead).where(Lead.phone == phone)
        if not inc:
            query = query.where(Lead.is_deleted == False)
        result = await db.execute(query)
        return result.scalars().first()

    def _apply_filters(
        self,
        query,
        status: LeadStatus | None = None,
        source: LeadSource | None = None,
        district: str | None = None,
        city: str | None = None,
        assigned_employee_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ):
        """
        Applies the shared filter/search predicate set to a base Lead select() query.
        """
        filters = []
        if status:
            filters.append(Lead.status == status)
        if source:
            filters.append(Lead.source == source)
        if district:
            filters.append(Lead.district.ilike(f"%{district.strip()}%"))
        if city:
            filters.append(Lead.city.ilike(f"%{city.strip()}%"))
        if assigned_employee_id:
            filters.append(Lead.assigned_employee_id == assigned_employee_id)
        if created_from:
            filters.append(Lead.created_at >= created_from)
        if created_to:
            filters.append(Lead.created_at <= created_to)
        if search:
            keyword = f"%{search.strip()}%"
            filters.append(
                or_(
                    Lead.business_name.ilike(keyword),
                    Lead.contact_person.ilike(keyword),
                    Lead.phone.ilike(keyword),
                    Lead.whatsapp.ilike(keyword),
                    Lead.email.ilike(keyword),
                )
            )
        if not include_deleted:
            filters.append(Lead.is_deleted == False)

        if filters:
            query = query.where(and_(*filters))
        return query

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: LeadStatus | None = None,
        source: LeadSource | None = None,
        district: str | None = None,
        city: str | None = None,
        assigned_employee_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        search: str | None = None,
        include_deleted: bool | None = None,
    ) -> tuple[Sequence[Lead], int]:
        """
        Fetches a paginated, filtered, and/or searched list of leads, along with the
        total count of matching rows (ignoring skip/limit) for pagination metadata.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        base_query = self._apply_filters(
            select(Lead),
            status=status,
            source=source,
            district=district,
            city=city,
            assigned_employee_id=assigned_employee_id,
            created_from=created_from,
            created_to=created_to,
            search=search,
            include_deleted=inc,
        )

        count_query = self._apply_filters(
            select(func.count()).select_from(Lead),
            status=status,
            source=source,
            district=district,
            city=city,
            assigned_employee_id=assigned_employee_id,
            created_from=created_from,
            created_to=created_to,
            search=search,
            include_deleted=inc,
        )

        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        query = base_query.order_by(Lead.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all(), total

    async def find_duplicate_candidates(
        self,
        db: AsyncSession,
        phone_keys: Sequence[str] = (),
        email_keys: Sequence[str] = (),
        business_key: str | None = None,
        include_deleted: bool | None = None,
    ) -> Sequence[Lead]:
        """
        Fetches every existing lead that could be the same business as an incoming record,
        matched on any of the three duplicate rules used by the Lead Collection Engine:
        phone number, email address, or business name + city.

        All three rules are evaluated in ONE query with an OR, rather than three sequential
        queries short-circuiting on the first hit. That matters because the rules can
        disagree: a record's phone may match lead A while its business name + city matches
        lead B (typically because the same studio was captured twice under two numbers).
        The caller needs to see both to pick a winner and to know a pre-existing duplicate
        pair exists; three short-circuiting queries would hide it.

        Matching is done in SQL against normalised expressions so it survives formatting
        differences in stored data:
        - phone: non-digits stripped, compared on the trailing digits, mirroring
          `normalize_phone`. Both `phone` and `whatsapp` columns are checked, since a
          business first captured under its landline may be re-scraped under its mobile.
        - email: trimmed and lowercased.
        - business name + city: lowercased with non-alphanumerics removed, mirroring
          `normalize_business_key`.

        `regexp_replace` with the 'g' flag is PostgreSQL-specific, which is consistent with
        this codebase's use of JSONB and other PostgreSQL-only features elsewhere.

        Args:
            phone_keys: Normalised phone keys from `NormalizedLead.phone_keys`.
            email_keys: Normalised email keys from `NormalizedLead.email_keys`.
            business_key: Normalised "name|city" key from `NormalizedLead.business_key`.

        Returns:
            Matching leads, most recently created first. Empty when nothing matches or when
            no usable key was supplied.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        # The number of trailing digits compared, matching
        # `app.services.lead_providers.normalized._PHONE_KEY_DIGITS`.
        phone_key_digits = 10

        def phone_expression(column):
            """SQL equivalent of `normalize_phone` for a stored phone column."""
            digits = func.regexp_replace(func.coalesce(column, ""), r"\D", "", "g")
            return func.right(digits, phone_key_digits)

        predicates = []

        clean_phone_keys = [k for k in phone_keys if k]
        if clean_phone_keys:
            predicates.append(phone_expression(Lead.phone).in_(clean_phone_keys))
            predicates.append(phone_expression(Lead.whatsapp).in_(clean_phone_keys))

        clean_email_keys = [k for k in email_keys if k]
        if clean_email_keys:
            predicates.append(func.lower(func.trim(Lead.email)).in_(clean_email_keys))

        if business_key:
            name_expr = func.regexp_replace(
                func.lower(func.coalesce(Lead.business_name, "")), r"[^a-z0-9]+", "", "g"
            )
            city_expr = func.regexp_replace(
                func.lower(func.coalesce(Lead.city, "")), r"[^a-z0-9]+", "", "g"
            )
            # A stored lead with no city cannot match a name|city key, and concatenating an
            # empty city would make every city-less lead named "X" match "x|anything".
            predicates.append(
                and_(
                    city_expr != "",
                    name_expr != "",
                    (name_expr + "|" + city_expr) == business_key,
                )
            )

        if not predicates:
            return []

        query = select(Lead).where(or_(*predicates))
        if not inc:
            query = query.where(Lead.is_deleted == False)

        result = await db.execute(query.order_by(Lead.created_at.desc()))
        return result.scalars().all()

    async def find_proximity_candidates(
        self,
        db: AsyncSession,
        latitude: float | None = None,
        longitude: float | None = None,
        lat_delta: float | None = None,
        lon_delta: float | None = None,
        city: str | None = None,
        limit: int = 200,
        include_deleted: bool | None = None,
    ) -> Sequence[Lead]:
        """
        Fetches leads that may satisfy the two duplicate rules that are not exact equality:
        coordinate proximity and business-name similarity.

        This is a *prefilter*, not a decision. Neither rule can be expressed as an indexed
        lookup — proximity is a distance and name similarity is fuzzy — so the actual
        comparison happens in `LeadDeduplicationService`. This method's only job is to bound
        how many rows that comparison has to consider, which is what stops each imported
        record from becoming a table scan.

        Two predicates, OR'd:
        - a latitude/longitude bounding box, sized by the caller to be slightly larger than
          its distance tolerance so no point the haversine check would accept is excluded
          here (a box is a superset of the circle inside it);
        - an exact city match, since the name-similarity rule is scoped to one city.

        `limit` caps the result because a common city name would otherwise return the entire
        table; leads are ordered most-recently-created first so the cap keeps the rows most
        likely to be relevant, matching `find_duplicate_candidates`' ordering.

        Returns an empty sequence when no usable filter was supplied, rather than every
        lead — an unfiltered call here would be a silent full scan.
        """
        inc = include_deleted if include_deleted is not None else self.include_deleted

        predicates = []

        if (
            latitude is not None
            and longitude is not None
            and lat_delta is not None
            and lon_delta is not None
        ):
            predicates.append(
                and_(
                    Lead.latitude.is_not(None),
                    Lead.longitude.is_not(None),
                    Lead.latitude.between(latitude - lat_delta, latitude + lat_delta),
                    Lead.longitude.between(longitude - lon_delta, longitude + lon_delta),
                )
            )

        city_key = (city or "").strip()
        if city_key:
            # Compared on the same normalisation the service uses for its city scope:
            # lowercased with non-alphanumerics removed, so "New Delhi" and "new-delhi"
            # agree.
            city_expr = func.regexp_replace(
                func.lower(func.coalesce(Lead.city, "")), r"[^a-z0-9]+", "", "g"
            )
            normalized_city = re.sub(r"[^a-z0-9]+", "", city_key.lower())
            if normalized_city:
                predicates.append(city_expr == normalized_city)

        if not predicates:
            return []

        query = select(Lead).where(or_(*predicates))
        if not inc:
            query = query.where(Lead.is_deleted == False)

        result = await db.execute(query.order_by(Lead.created_at.desc()).limit(limit))
        return result.scalars().all()

    async def update(self, db: AsyncSession, db_obj: Lead, update_data: dict) -> Lead:
        """
        Updates a lead's attributes and commits changes.
        """
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Lead) -> bool:
        """
        Soft deletes a lead record from the database.
        """
        db_obj.is_deleted = True
        db_obj.deleted_at = datetime.now(timezone.utc)
        db.add(db_obj)
        await db.commit()
        return True


class AdminLeadRepository(LeadRepository):
    """
    Lead Repository that includes soft-deleted items by default.
    """
    def __init__(self) -> None:
        super().__init__(include_deleted=True)
