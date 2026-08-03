"""
app/services/lead_providers/csv_provider.py

This file implements `CsvLeadProvider` — the adapter that turns an operator-uploaded CSV
into normalized leads.

It is the one adapter whose "source" is a human rather than a website, which drives every
design choice here: the column mapping is forgiving, because the file was assembled in a
spreadsheet by someone who called the column "Business Name", "business_name", "Studio" or
"NAME"; and a malformed row is always a per-row failure with a row number attached, never
a run-level abort, because losing 300 good rows to one bad one is not an acceptable
outcome for a manual upload.

Why the column mapping is alias-based rather than positional
------------------------------------------------------------
A positional or strictly-named contract would force operators to reshape their file before
uploading, and reshaping in a spreadsheet is exactly where leads get mangled. Instead every
normalized field declares the header aliases seen in practice, headers are matched
case- and punctuation-insensitively, and anything unrecognised is preserved in `raw` rather
than discarded — so an unmapped column is visible in diagnostics instead of silently lost.

Multi-value columns
-------------------
`phone_numbers`, `emails` and `categories` accept several values in a single cell separated
by comma, semicolon, pipe or slash, because that is how a spreadsheet holds a business's
two contact numbers. This is also why a phone column must not be blindly split on comma
alone — "+91 98765 43210, 080-2345-6789" and "Bengaluru, Karnataka" are both comma-bearing
cells, so splitting is applied only to columns mapped to multi-value fields.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Sequence

from app.services.lead_providers.base import (
    LeadProvider,
    ProviderCollectionError,
    ProviderContext,
    register_provider,
)
from app.services.lead_providers.normalized import NormalizedLead


#: Header aliases per normalized field. Compared after `_header_key` normalisation, so
#: "Business Name", "business_name" and "BUSINESS-NAME" all reduce to "businessname".
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "business_name": (
        "businessname", "business", "name", "studio", "studioname", "companyname",
        "company", "firm", "shopname", "leadname",
    ),
    "owner_name": (
        "ownername", "owner", "contactperson", "contact", "person", "proprietor",
        "contactname", "photographername",
    ),
    "phone_numbers": (
        "phone", "phonenumber", "phonenumbers", "mobile", "mobilenumber", "contactnumber",
        "contactno", "phoneno", "number", "whatsapp", "whatsappnumber", "telephone",
        "altphone", "alternatephone", "secondaryphone",
    ),
    "emails": (
        "email", "emails", "emailaddress", "emailid", "mail", "altemail",
    ),
    "website": ("website", "web", "url", "site", "websiteurl", "homepage"),
    "instagram": ("instagram", "instagramhandle", "insta", "ig", "instagramurl"),
    "facebook": ("facebook", "facebookurl", "fb", "fbpage", "facebookpage"),
    "address": ("address", "fulladdress", "streetaddress", "location", "addressline"),
    "city": ("city", "town", "cityname"),
    "district": ("district", "districtname"),
    "state": ("state", "province", "statename"),
    "country": ("country",),
    "pincode": ("pincode", "pin", "zip", "zipcode", "postalcode", "postcode"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lng", "long", "lon"),
    "rating": ("rating", "stars", "score", "googlerating"),
    "review_count": ("reviewcount", "reviews", "numreviews", "totalreviews", "ratingcount"),
    "source_url": ("sourceurl", "listingurl", "profileurl", "link", "mapsurl", "listing"),
    "categories": ("categories", "category", "tags", "services", "type", "businesstype"),
}

#: Fields whose cell may legitimately hold several values.
_MULTI_VALUE_FIELDS = frozenset({"phone_numbers", "emails", "categories"})

#: Separators accepted inside a multi-value cell.
_MULTI_VALUE_SPLIT = re.compile(r"[,;|/]")

#: Byte-order marks and stray quoting that spreadsheet exports prepend to the first header.
_BOM = "﻿"


def _header_key(header: str) -> str:
    """Reduces a CSV header to its comparison form: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", (header or "").replace(_BOM, "").strip().lower())


def build_column_map(headers: Sequence[str]) -> dict[str, list[str]]:
    """
    Maps normalized field names onto the actual header strings present in this file.

    Returns a dict of field → list of source headers, because several columns can feed one
    field (a file with both "Phone" and "Alternate Phone" contributes both to
    `phone_numbers`). Header order is preserved, which is what makes the leftmost phone
    column become the lead's primary number.

    Unrecognised headers are simply absent from the result; the row reader keeps them in
    `raw` so nothing is silently lost.
    """
    mapping: dict[str, list[str]] = {}
    for header in headers:
        key = _header_key(header)
        if not key:
            continue
        for field_name, aliases in _COLUMN_ALIASES.items():
            if key in aliases:
                mapping.setdefault(field_name, []).append(header)
                break
    return mapping


def _split_values(value: str) -> list[str]:
    """Splits a multi-value cell on any accepted separator, discarding empty fragments."""
    return [part.strip() for part in _MULTI_VALUE_SPLIT.split(value) if part.strip()]


@register_provider
class CsvLeadProvider(LeadProvider):
    """
    Adapter that reads normalized leads from an uploaded CSV file.

    Unlike the search providers, this one takes no query: its input is `file_content` on
    the `ProviderContext`, supplied by the import endpoint from the uploaded file.
    """

    key = "csv"
    display_name = "Manual CSV Import"
    lead_source = "CSV_IMPORT"
    requires_query = False
    requires_file = True

    async def collect(self, context: ProviderContext) -> Sequence[dict[str, Any]]:
        """
        Parses the uploaded bytes into raw row dicts, each tagged with its 1-based row
        number so a per-row failure can be reported as "row 47" rather than "a row".

        Decoding tries UTF-8 (with BOM tolerance) then falls back to latin-1, which cannot
        fail — Excel on Windows still emits cp1252 files, and refusing them outright would
        make the feature useless to the operators most likely to need it.

        Raises:
            ProviderCollectionError: the file is empty, has no header row, or contains no
                column that maps to a business name or a phone number. These are
                file-level faults: every row would fail identically, so reporting it once
                as a run failure is more useful than N identical row errors.
        """
        if not context.file_content:
            raise ProviderCollectionError("No file content was supplied for the CSV import.")

        try:
            text = context.file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = context.file_content.decode("latin-1")

        if not text.strip():
            raise ProviderCollectionError("The uploaded CSV file is empty.")

        # Sniff the delimiter so semicolon- and tab-separated exports work too, falling
        # back to comma when the sniffer cannot decide on a short file.
        sample = text[:8192]
        try:
            dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise ProviderCollectionError("The uploaded CSV file has no header row.")

        column_map = build_column_map(reader.fieldnames)
        if "business_name" not in column_map and "phone_numbers" not in column_map:
            recognised = ", ".join(sorted(column_map)) or "none"
            raise ProviderCollectionError(
                "The uploaded CSV has no column that maps to a business name or a phone "
                f"number (recognised columns: {recognised}). Expected a header such as "
                "'Business Name' or 'Phone'."
            )

        records: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):  # row 1 is the header
            if len(records) >= context.limit:
                break
            # Skip entirely blank lines rather than counting them as failures; trailing
            # blank rows are an artefact of every spreadsheet export.
            if not any((value or "").strip() for value in row.values() if value is not None):
                continue
            records.append({
                "_row_number": row_number,
                "_column_map": column_map,
                "values": {k: v for k, v in row.items() if k is not None},
            })

        if not records:
            raise ProviderCollectionError(
                "The uploaded CSV file contains a header but no data rows."
            )

        return records

    def normalize(self, raw: dict[str, Any]) -> NormalizedLead:
        """
        Maps one CSV row onto the uniform shape, using the column map built at parse time.

        Multi-value fields accumulate across every column mapped to them and are split on
        the accepted separators; single-value fields take the first non-empty mapped column,
        so a file with both "Website" and an empty "URL" column still yields the website.
        """
        column_map: dict[str, list[str]] = raw.get("_column_map") or {}
        values: dict[str, Any] = raw.get("values") or {}
        row_number = raw.get("_row_number")

        def single(field_name: str) -> str | None:
            for header in column_map.get(field_name, []):
                cell = values.get(header)
                if cell is not None and str(cell).strip():
                    return str(cell).strip()
            return None

        def multi(field_name: str) -> list[str]:
            collected: list[str] = []
            for header in column_map.get(field_name, []):
                cell = values.get(header)
                if cell is None or not str(cell).strip():
                    continue
                collected.extend(_split_values(str(cell)))
            return collected

        lead = NormalizedLead(
            business_name=single("business_name"),
            owner_name=single("owner_name"),
            phone_numbers=multi("phone_numbers"),
            emails=multi("emails"),
            website=single("website"),
            instagram=single("instagram"),
            facebook=single("facebook"),
            address=single("address"),
            city=single("city"),
            district=single("district"),
            state=single("state"),
            country=single("country"),
            pincode=single("pincode"),
            latitude=single("latitude"),
            longitude=single("longitude"),
            rating=single("rating"),
            review_count=single("review_count"),
            source=self.lead_source,
            source_url=single("source_url"),
            categories=multi("categories"),
            # The whole original row is retained, including columns we did not map, so an
            # operator can see exactly what was uploaded for a row that failed.
            raw={"row_number": row_number, "row": values},
        )
        return lead.normalize()
