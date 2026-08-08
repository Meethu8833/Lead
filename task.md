# Task Log

Tracks feature work completed in this repository, one section per feature phase.

## Orders Module — Foundation Phase

**Status:** Complete

**Scope:** Listing, viewing, filtering, creating, and editing orders. Production workflow,
payments, invoices, delivery, notifications, and attachments are explicitly out of scope for
this phase (see `app/models/order.py` relationships — those live on separate models/endpoints
already present in the backend but not wired into the frontend yet).

### Checklist

- [x] `src/features/orders/types.ts` — TypeScript types mirroring `app/schemas/order.py` /
      `app/schemas/order_item.py`.
- [x] `src/features/orders/api.ts` — thin axios wrappers over the existing `/orders`,
      `/orders/{id}/items`, `/order-items/{id}` endpoints, plus lightweight photographer/product
      lookups for form selects.
- [x] `src/features/orders/validation.ts` — Zod schemas for the order form and add-item dialog.
- [x] `src/features/orders/hooks.ts` — TanStack Query hooks (`useOrders`, `useOrder`,
      `useCreateOrder`, `useUpdateOrder`, `useDeleteOrder`, `useAddOrderItem`,
      `useUpdateOrderItem`, `useRemoveOrderItem`) with optimistic cache updates.
- [x] Components: `OrdersTable`, `OrderFilters`, `OrderForm`, `OrderItemsTable`,
      `AddItemDialog`, `OrderSummaryCard`, `DeleteOrderDialog`, `OrderStatusBadge` (+
      `ProductionStageBadge`, `PaymentStatusBadge`), `OrderSkeleton` (list/details/form variants).
- [x] Pages: `OrdersPage`, `OrderDetailsPage`, `CreateOrderPage`, `EditOrderPage`.
- [x] Routes wired into `src/App.tsx` — `/orders`, `/orders/new`, `/orders/:id`,
      `/orders/:id/edit`, each behind `ProtectedRoute` with the matching `orders:*` permission.
- [x] RBAC — create/edit/delete actions hidden per `orders:create` / `orders:update` /
      `orders:delete`; list/detail routes require `orders:view`.
- [x] `src/tests/orders.test.tsx` — 14 tests covering loading, success, error + retry, search
      filter, status filter + clear, RBAC visibility (hidden and shown), delete confirm/cancel,
      create-form validation, create → redirect-to-edit flow, edit prefill + submit, add-item
      flow, and order details rendering.
- [x] `npm run test` — 129/129 tests passing (9 files, including the new suite).
- [x] `npm run build` — `tsc` + `vite build` succeed with zero TypeScript errors.

### Known gaps / follow-ups for a later phase

1. **No backend `priority` field on `Order`.** The spec asked for a Priority field on the
   order form, but `app/models/order.py` has no such column (only `Photographer.priority`
   exists, which belongs to the lead/CRM entity, not the order). Omitted from this phase;
   needs a backend model + schema + migration change before it can be added.
2. **No separate `Customer` entity.** `Photographer` is this CRM's client/lead entity (see
   `LeadStatus.CUSTOMER` in `app/models/photographer.py`) and doubles as the order's customer.
   Table/detail/form show one combined "Photographer / Customer" field backed by
   `order.photographer_id` — confirmed with the user rather than inventing a second identity.
3. **"Production Stage" reuses `order.status`.** The `Order` model has no separate
   production-stage field at the order level (only `OrderItem.production_stage`, which is a
   production-workflow concern out of scope for this phase). The dashboard's existing
   `RecentOrdersTable` already established the precedent of showing `order.status` under both a
   "Status" and a "Production Stage" column; this phase follows the same convention for
   consistency.
4. **No server-side pagination/filtering for orders.** `GET /orders` and `GET /orders/search`
   return bare arrays with `skip`/`limit` only — no total count, and `search` only supports
   `order_number`, `job_name`, `status`. Sorting, pagination, and the remaining filters (payment
   status, photographer, date ranges) are done client-side over a capped `limit=200` fetch, the
   same pattern already used by the dashboard. This will need real server-side
   pagination/filtering if the orders table needs to scale beyond a couple hundred rows.
5. **No column resizing.** The shared `DataTable` component doesn't support resizable columns;
   adding that was judged out of scope for a reusable-component change in this phase.
6. **Order items are a separate sub-resource, not part of order create/update.** Backend
   `OrderCreate`/`OrderUpdate` schemas don't accept an items array — items are created via
   `POST /orders/{id}/items` after the order exists. `CreateOrderPage` therefore creates the
   order shell first, then redirects to `EditOrderPage` where the Order Items section becomes
   active. `total_amount` is also fully server-derived from item subtotals (see
   `OrderService.update_order`), so it is never sent from the frontend — the "Grand Total" shown
   during editing is a live client-side sum of the same item subtotals for parity.

## Lead Management Module — Backend Foundation Phase

**Status:** Complete (backend only)

**Scope:** The `Lead` domain entity and its full backend stack — model, schemas, repository,
service, RBAC-gated REST endpoints, Alembic migration, and integration tests. WhatsApp
integration, scraping, CSV/bulk imports, campaigns, and follow-ups are explicitly **out of
scope** for this phase (the `LeadSource.CSV_IMPORT` / `GOOGLE_MAPS` / `INSTAGRAM` enum values
exist so those pipelines have a slot to write into later, but no import/scrape code was
written). **No frontend work** — per the task's explicit instruction. **No existing ERP module**
(Orders, Payments, Inventory, Production, Delivery, Invoices, Photographers) was modified.

### Checklist

- [x] `app/models/lead.py` — `Lead` model + `LeadStatus` (9 values) and `LeadSource` (8 values)
      enums, with soft delete, optimistic locking (`version_id_col`), and a nullable
      `assigned_employee_id` FK → `employees.id` (`ON DELETE SET NULL`).
- [x] `app/schemas/lead.py` — `LeadCreate`, `LeadUpdate` (all-optional + `version`),
      `LeadResponse`, `LeadListResponse` (paginated envelope with `total`).
- [x] `app/repositories/lead.py` — `LeadRepository` with a shared `_apply_filters()` powering
      both the page query and the `COUNT(*)`, plus `AdminLeadRepository` for soft-deleted rows.
- [x] `app/services/lead.py` — `LeadService`: unique-phone enforcement, forced `status=NEW` on
      create, optimistic-lock version check, 404s via `NotFoundException`.
- [x] `app/api/v1/endpoints/leads.py` — the 5 specified routes, each gated with
      `RequirePermission("leads:<action>")`.
- [x] Wiring — `app/models/__init__.py`, `app/schemas/__init__.py`,
      `app/repositories/__init__.py`, `app/services/__init__.py`, `get_lead_service()` in
      `app/api/deps.py`, and `leads.router` mounted at `/leads` in `app/api/v1/router.py`.
- [x] RBAC — `leads:create/update/delete/view/*` added to `scripts/seed_roles.py`; `leads:*`
      granted to `Manager` and `Reception`; `Viewer`'s existing `*:view` covers `leads:view`.
      Seed script re-run and confirmed idempotent.
- [x] Alembic — `2dcb418e93d7_create_leads_table.py`. Autogenerate detected **only** the new
      `leads` table + its 8 indexes; zero changes to any existing table. Applied to head.
- [x] `tests/test_leads.py` — 10 sections covering create/defaults, duplicate phone, blank-name
      validation, update, optimistic lock, filtering (6 filters), search (5 fields), pagination,
      soft delete, audit logs, and RBAC. All passing.
- [x] Existing test suite re-run for regressions — see "Known gaps" #3 below for the pre-existing
      failures.

### Known gaps / follow-ups for a later phase

1. **`Lead` and `Photographer` are two separate entities with two separate lead-status
   concepts.** `app/models/photographer.py` already had its own `LeadStatus`/`LeadPriority`/
   `ContactMethod` CRM fields from an earlier phase, with a *different* set of status values
   (`NEGOTIATING`/`INACTIVE`/`REJECTED`) than this task specified for the new module
   (`MESSAGE_SENT`/`REPLIED`/`NEGOTIATION`/`LOST`). They could not be merged without changing
   `Photographer`, which this task forbids. The new Postgres enum types are therefore named
   `lead_status`/`lead_source` (underscored) to avoid colliding with the existing `leadstatus`
   type owned by `photographers`. **A future phase should decide whether `Photographer`'s CRM
   fields get retired in favour of `Lead`**, and what the `Lead → Photographer` conversion path
   looks like — `is_converted` is currently a plain flag with no conversion logic behind it.
2. **`is_converted` has no behaviour attached.** It's settable via `LeadUpdate` and defaults to
   `False`, but nothing reads it and nothing links a converted lead to a `Photographer` row.
   Wiring `status == CUSTOMER` → create/link a `Photographer` is deliberately deferred, since
   the task scoped this phase to "Only create the Lead domain."
3. **Pre-existing test failures, unrelated to this module.** `test_erp.py`,
   `test_production.py`, and `test_delivery_payment.py` fail both with and without this change:
   the shared dev database holds a soft-deleted `Photographer` row (`ab3dd978-...`) that those
   suites' "pick any existing photographer" fixture doesn't filter by `is_deleted`, so they
   select it and then get a 404 from `OrderService.create_order`. Reproduced with `test_erp.py`
   run entirely alone. Fixing it means touching `Order`/`Photographer` test fixtures, which this
   task's "do not modify existing ERP modules" rule puts out of scope. Similarly `test_auth.py`
   passes alone but fails its final `assert cleaned == 1` inside a full sequential run
   (ordering-sensitive expired-session cleanup) — also pre-existing.
4. **`npm run build` fails on 3 pre-existing TypeScript errors** in
   `src/features/orders/components/AddItemDialog.tsx` and `OrderItemEditor.tsx`
   (`ProductSelectorProps.products` missing). These are in uncommitted Orders-module frontend
   work that predates this session; this phase touched zero frontend files.
5. **RBAC is enforced on `leads` routes but still not on the older modules.** `orders`,
   `photographers`, `inventory`, etc. define permissions but don't actually apply
   `RequirePermission` to their routes. The `leads` endpoints do. Retro-fitting the older
   modules would change existing ERP behaviour and was left alone.
6. **No `GET /leads/search` route.** Search is a `search=` query parameter on `GET /leads` so it
   composes with the other filters and shares one pagination/count path, rather than a second
   endpoint with a divergent response shape.

## Lead Activity & Notes Module

**Status:** Complete

**Scope:** Backend only. Chronological activity timeline + manual notes for leads, with
automatic activity creation on lead create/update/delete/status-change/convert and on manual
note creation. WhatsApp automation, follow-ups, campaigns, CSV import, and all frontend work
are explicitly out of scope for this phase.

**Constraints honoured:** No existing ERP module was modified. The `leads` table was **not**
altered — the two new tables reference it by FK only (confirmed by an Alembic autogenerate that
detected nothing but the two new tables).

### Checklist

- [x] `app/models/lead_activity.py` — `LeadActivity` (append-only) + `LeadNote` (editable,
      soft-deletable) + the `ActivityType` enum (all 11 specified members, plus `DELETED`).
      `metadata` is mapped as the Python attribute `activity_metadata` because `metadata` is
      reserved by SQLAlchemy's declarative base; the DB column and the API field are both
      still named `metadata`.
- [x] `app/schemas/lead_activity.py` — `LeadNoteCreate/Update/Response/ListResponse`,
      `LeadActivityResponse/ListResponse`. No `LeadActivityCreate` by design: activities are
      emitted by the service layer, never posted by a client.
- [x] `app/repositories/lead_activity.py` — `LeadActivityRepository` (create + read only, no
      update/delete path — this is what enforces append-only), `LeadNoteRepository`,
      `AdminLeadNoteRepository`. All writes take `commit: bool = True` per house convention.
- [x] `app/services/lead_activity.py` — `LeadActivityService` (single writer of the timeline,
      via `record()` + `log_*` helpers) and `LeadNoteService` (note CRUD; creating a note and
      its `NOTE` activity commit in one transaction).
- [x] `app/services/lead.py` — automatic activity hooks added to `create_lead`, `update_lead`,
      `delete_lead`. No-op updates emit nothing; a status change emits both `UPDATED` and
      `STATUS_CHANGED`; `CONVERTED` fires on transition only.
- [x] `app/api/v1/endpoints/lead_activities.py` — the 5 specified routes, each gated with
      `RequirePermission("leads:view")` or `("leads:update")`.
- [x] Wiring — `app/models/__init__.py`, `app/schemas/__init__.py`,
      `app/repositories/__init__.py`, `app/services/__init__.py`,
      `get_lead_activity_service()` / `get_lead_note_service()` in `app/api/deps.py`, and the
      router mounted at the root prefix **before** `leads.router` in `app/api/v1/router.py`
      so `/leads/{id}/notes` is not shadowed by `/leads/{id}`.
- [x] RBAC — reuses the existing `leads:view` / `leads:update` permissions. **No seed change
      was needed**: both already exist in `scripts/seed_roles.py` and are granted to
      Manager/Reception, with Viewer's `*:view` covering the reads.
- [x] Audit — reuses the existing `before_flush` listener; no new wiring. Verified by test.
- [x] Alembic — `504f5c5d4a31_add_lead_activities_and_notes.py`. Applied to head, downgrade/
      re-upgrade round-trip verified, and a follow-up autogenerate came back empty (no drift).
- [x] `tests/test_lead_activities.py` — 16 sections covering note create/edit/delete, activity
      creation, automatic status activity, timeline ordering, pagination, RBAC, JSONB
      round-trip, immutability, audit reuse, and regression of existing Lead CRUD. All passing.
- [x] Existing test suite re-run for regressions — 9 pass, 3 pre-existing ERP failures
      (see #4 below).

### Notable findings

1. **A real FK bug was caught by the existing `tests/test_leads.py` and fixed.**
   `created_by_employee_id` is a genuine FK to `employees.id`, but the actor it is resolved
   from (`audit_context`) is populated from the **unauthenticated** `x-user-id` /
   `x-performed-by` request headers, which may hold any string. Writing that value straight
   into the FK would have made **any request carrying a bogus `x-user-id` header 500 on every
   lead write**. Fixed via `resolve_actor_employee_id()`, which validates the UUID against the
   `employees` table and falls back to `None` (system-generated) rather than failing the
   domain operation. `AuditLog.performed_by` is unaffected — it is free text by design.

2. **Ordering uses `created_at DESC, id DESC`, not `created_at` alone.** Multiple activities
   emitted inside one transaction share an identical `created_at` (Postgres `now()` is fixed
   per transaction), so without the `id` tiebreaker paginated reads could duplicate and skip
   rows. Pinned by a test that pages an 11-entry timeline in pages of 3.

### Known gaps / follow-ups for a later phase

1. **WhatsApp activity types are defined but never emitted.** `WHATSAPP_SENT`/`DELIVERED`/
   `READ`/`REPLIED` exist in the enum so the timeline schema is stable before the messaging
   integration lands, but nothing writes them this phase (asserted by a test). `PHONE_CALL`
   and `FOLLOW_UP` are likewise only reachable through the internal
   `LeadActivityService.record()` API — there is no endpoint to log a call or schedule a
   follow-up yet, since follow-ups were explicitly out of scope.

2. **`LeadNote` has no optimistic-locking `version` column,** unlike `Lead`. Notes are short
   single-author free text with no derived state to protect, so last-write-wins is the
   intended behaviour. If concurrent note editing by multiple staff becomes real, this needs
   revisiting.

3. **Editing a note does not appear on the timeline.** Deliberate: the timeline records that a
   note was written, and the automatic audit log already captures the old→new body. If the
   product wants "X edited a note" visible in the timeline, that's a new activity type.

4. **Pre-existing test failures, unrelated to this module.** `test_erp.py`,
   `test_production.py`, and `test_delivery_payment.py` fail on the same soft-deleted
   `Photographer` (`ab3dd978-...`) documented in the previous phase. **Re-confirmed
   pre-existing this session** by `git stash`-ing every change and re-running `test_erp.py` on
   the clean tree — identical error, identical photographer ID. Fixing it means touching
   `Order`/`Photographer` test fixtures, which the "do not modify existing ERP modules" rule
   puts out of scope.

5. **Timeline reads are per-lead only.** There is no cross-lead activity feed (e.g. "everything
   my team did today"), since the spec scoped this to the Lead Details page. The
   `(lead_id, created_at DESC)` index is built for the per-lead query; a global feed would want
   a different index.

---

## WhatsApp Campaign Management Module

**Phase goal.** Turn the CRM's outreach story from "leads sit in a table" into "leads get
messaged, tracked and re-categorised automatically" — without committing to a WhatsApp vendor.
This phase is backend-only and deliberately touches no ERP module.

Scope note: this phase pivots the product from a generic photographer ERP toward a **Lead
Generation CRM**. Orders, Inventory, Production, Billing, Payments, Delivery, ERP dashboards
and Photographer management were explicitly out of scope and were not modified.

### Checklist

- [x] `WhatsAppTemplate` model — name, category, language, body, derived `variables` (JSONB),
      `is_active`, soft delete, optimistic locking, partial unique index on name.
- [x] `WhatsAppCampaign` model — template FK (RESTRICT), lifecycle status, `scheduled_at`,
      six denormalized counters, `created_by`, soft delete, optimistic locking.
- [x] `CampaignRecipient` model — campaign+lead FKs (CASCADE), snapshotted `phone`,
      `message_status`, `rendered_message`, `provider_message_id`, and the four delivery
      timestamps (`sent_at`/`delivered_at`/`read_at`/`replied_at`).
- [x] `(campaign_id, lead_id)` unique constraint — a lead cannot be enrolled twice.
- [x] `Lead.last_contacted_at` column added (nullable, indexed) — the one Lead change.
- [x] Provider abstraction: `WhatsAppProvider` ABC + `ProviderSendResult` + registry +
      `NoOpWhatsAppProvider`. **No real vendor integrated.**
- [x] Repositories for all three entities, following the house `commit: bool` /
      `(rows, total)` / `Admin*` conventions.
- [x] `WhatsAppTemplateService` — CRUD, variable extraction, rendering, preview.
- [x] `WhatsAppCampaignService` — CRUD, enrolment, lifecycle state machine, dispatch,
      delivery-status transitions, counters, statistics, progress.
- [x] `CampaignReplyService` — reply matching, timeline entry, `last_contacted_at`, and the
      reply → lead-status automation.
- [x] Pydantic schemas for every request/response shape.
- [x] 19 endpoints under `/api/v1/whatsapp`, all behind `RequirePermission`.
- [x] New `whatsapp:*` permission set seeded; granted to Manager (full) and Reception
      (view/create/update, no delete).
- [x] Alembic migration `3f2dfbe6340d` — applied, downgraded, re-upgraded cleanly.
- [x] `tests/test_whatsapp.py` — 15 sections, all passing, stable across three consecutive runs.

### Reply → lead status mapping

Implemented as data (`REPLY_TYPE_TO_LEAD_STATUS` in `app/services/whatsapp.py`), not branching:

| `reply_type` | New `Lead.status` |
|---|---|
| `interested` | `NEGOTIATION` |
| `not_interested` | `LOST` |
| `need_details` | `REPLIED` |

An explicit `lead_status` in the payload overrides the mapping. An **unrecognised**
`reply_type` maps to nothing (the lead is left alone) rather than falling back to a default,
so a new intent label added upstream cannot silently reclassify leads. A lead already at
`CUSTOMER` is never re-categorised by an inbound message.

### Notable findings

1. **Two real bugs were caught by the new suite, both fixed.**
   - `SCHEDULED → SCHEDULED` was missing from the campaign transition table, so **rescheduling
     an already-scheduled campaign raised a 400**. An operator would have had to bounce the
     campaign back to `DRAFT` just to move it by an hour. Added as a legal transition.
   - The dispatch loop assigned `error_text` only inside its `except` branch, so a **stale
     failure reason from an earlier recipient could be attributed to a later one**. Now reset
     per iteration.

2. **Recipient list position is not stable across reads.** Bulk enrolment writes every row
   inside one transaction, so they share an identical `created_at` (Postgres `now()` is fixed
   per transaction) and ordering falls to the random-UUID `id` tiebreaker. The first version of
   the test indexed recipients positionally and failed intermittently. The repository ordering
   is correct; the test now keys recipients by `lead_id`.

3. **Delivery webhooks must be monotonic, not last-write-wins.** Providers retry and reorder
   callbacks, so a late "delivered" arriving after "read" would otherwise regress the row.
   `MESSAGE_STATUS_RANK` makes every status callback forward-only, which is what makes the
   endpoint idempotent under replay. Pinned by a test that replays `DELIVERED` after `READ`
   and asserts both the status and the original timestamp are untouched.

4. **Counters are recomputed, never incremented.** All six `total_*` columns are derived from
   one grouped query over the recipient rows. Incrementing them per transition would let a
   single missed webhook desynchronise them permanently; recomputing makes drift impossible by
   construction. The statistics endpoint recomputes independently, and a test asserts the two
   agree.

5. **Counts are cumulative, not exclusive.** A lead who replied also received and read the
   message. Counting them only under "replied" would make the delivery rate understate reality,
   so `total_delivered` means "reached DELIVERED **or beyond**". Asserted directly (one READ
   recipient out of four ⇒ `delivery_rate == read_rate == 25.0`).

### Known gaps / follow-ups for a later phase

1. **Dispatch is synchronous inside the request.** There is no task queue in this codebase, so
   `POST /campaigns/{id}/start` sends in a loop and returns when done. With the no-op provider
   that is instant, but at a real vendor's ~100ms/message a large audience would exceed a
   request timeout. The provider port is already `async`, so moving the loop into a worker
   needs no interface change. **This is the first thing to add alongside a real provider.**

2. **`scheduled_at` is recorded and enforced but nothing polls it.** A campaign is dispatched
   by an explicit call to the start endpoint. `WhatsAppCampaignRepository.get_due_for_dispatch`
   is written and ready for the scheduler that does not exist yet — the query is there so
   adding a poller requires no repository change.

3. **The reply webhook is protected by RBAC, not by signature verification.** A real provider
   cannot present a JWT and will need `X-Hub-Signature-256` (Meta) or `X-Twilio-Signature`
   verification instead. That check is provider-specific and belongs with the adapter, so it is
   deferred with it. Leaving the endpoint behind `whatsapp:update` in the meantime is the safe
   default — an unauthenticated webhook with no signature check would let anyone on the
   internet rewrite lead statuses.

4. **Phone-only reply matching attributes to the most recent dispatch.** When a provider gives
   us no `provider_message_id`, a reply is matched to that number's latest dispatched message.
   If the same lead is enrolled in several campaigns, the reply lands on the most recent one —
   which is how a human reads the conversation, but it is a heuristic, not a fact. Supplying
   `provider_message_id` avoids the ambiguity entirely.

5. **No per-recipient variable overrides.** Campaign messages are personalised from the lead
   record (`business_name`, `contact_person`, `city`, …) via
   `WhatsAppTemplateService.build_lead_variables`. There is no way to pass a per-recipient
   value (e.g. a unique coupon code). Adding one means a JSONB column on `campaign_recipients`.

6. **No opt-out / do-not-contact handling.** A lead has no "unsubscribed" flag, so nothing
   prevents enrolling someone who asked not to be messaged. Real WhatsApp Business compliance
   requires this before any live send; it is a Lead-model change and was out of scope here.

7. **Templates are not submitted to any provider for approval.** Meta requires marketing
   templates to be pre-registered and approved. `TemplateCategory` deliberately mirrors the
   categories providers ask for so existing rows can be mapped at submission time, but no
   submission workflow exists.

8. **Pre-existing ERP test failures persist, unrelated to this module.** `test_erp.py`,
   `test_production.py` and `test_delivery_payment.py` still fail on the soft-deleted
   `Photographer` fixture documented in the previous two phases. Untouched — fixing them means
   editing ERP test fixtures, which this phase's "do not modify unrelated ERP modules" rule
   puts out of scope.

---

## Lead Collection Engine

**Phase goal.** Collect photographer leads from multiple sources into the existing `leads`
table, never creating a duplicate, with an architecture where adding the *next* source
touches no existing file.

Scope note: this phase is strictly the collection path. Orders, Inventory, Production,
Payments, Dashboard and every other ERP module were explicitly out of scope and were not
modified. The `Lead` model itself was not modified. Per instruction, **no real scraping is
implemented** — the deliverable is the provider architecture plus one `MockProvider` and a
working CSV importer.

### Checklist

- [x] `ImportJob` model + `ImportJobStatus` — provider, query, status, `started_at`,
      `completed_at`, `total_found`, `new_leads`, `updated_leads`, `duplicate_leads`,
      `failed_records`, `logs` (JSONB), soft delete, optimistic locking.
- [x] `provider` stored as `String`, **not** an enum — an enum would force a migration per
      new provider, contradicting the extensibility requirement.
- [x] `retry_of_job_id` self-FK — a retry is a new row, preserving the original's failure record.
- [x] Abstract `LeadProvider` with the specified `search(query)` / `collect()` / `normalize()`
      contract, plus `ProviderContext`, registry, and `collect_normalized()` composition.
- [x] `NormalizedLead` DTO carrying every field in the spec — `business_name`, `owner_name`,
      `phone_numbers`, `emails`, `website`, `instagram`, `facebook`, `address`, `city`,
      `district`, `state`, `pincode`, `latitude`, `longitude`, `rating`, `review_count`,
      `source`, `source_url`, `categories` (+ `country` and `raw` for diagnosis).
- [x] Provider interfaces for all 7 required sources: Google Maps, Justdial, Facebook,
      Instagram, IndiaMART, wedding directories, CSV.
- [x] `MockLeadProvider` — deterministic offline fixtures (same query → same records, which is
      what makes the "second run creates zero leads" assertion possible).
- [x] `CsvLeadProvider` — alias header mapping, multi-value cells, delimiter sniffing,
      encoding fallback, per-row failure reporting.
- [x] Deduplication on phone, email, and business name + city — one OR'd SQL query, ranked
      phone > email > name+city.
- [x] Phone matching normalised in SQL against **both** `phone` and `whatsapp` columns.
- [x] Within-batch deduplication (same run, same business under two phone formats).
- [x] Enrichment on match — fills empty fields only, never overwrites; no write at all when
      the record carries nothing new.
- [x] `ImportJobRepository` + `find_duplicate_candidates` on `LeadRepository` (the only edit
      to an existing repository).
- [x] `LeadImportService` — lifecycle, dedup, enrichment, per-record isolation, retry.
- [x] Pydantic schemas for run requests, job responses, provider listing, statistics.
- [x] Endpoints: `POST /leads/import`, `GET /leads/imports`, `GET /leads/imports/{id}`,
      `POST /leads/imports/{id}/retry` (all four required), plus `POST /leads/import/csv`,
      `GET /leads/import/providers`, `GET /leads/imports/statistics`.
- [x] Router registered **before** `leads.router` so `/leads/imports` is not swallowed by
      `/leads/{id}`.
- [x] New `leads:import` permission seeded (distinct blast radius from `leads:create`).
- [x] Alembic migration `21a40470e494` — `import_jobs`, with hand-added `DROP TYPE` in
      `downgrade()`; round-trip verified.
- [x] Integration tests — 8 sections covering provider interface, normalization, duplicate
      detection, CSV import, import statistics, job status, plus schema and isolation checks.
- [x] Full backend suite re-run for regressions.

### Bug found and fixed

**`limit=0` silently became `limit=100`.** `LeadProvider.search` read
`kwargs.get("limit") or 100`; since `0 or 100` evaluates to `100`, the `if limit < 1`
validation immediately below was unreachable and an explicit request for zero records ran a
full-size import. Changed to an `is None` check. Caught only because the suite asserts the
rejection rather than just the happy path.

### Verification

```
alembic upgrade head                            # 21a40470e494
alembic downgrade -1 && alembic upgrade head    # round-trip OK
python scripts/seed_roles.py                    # leads:import seeded
python tests/test_lead_import.py                # ALL 8 sections PASS
```

The autogenerated migration diff contained **only** `import_jobs` — no drift into any other
module. New suite passes; `test_leads.py`, `test_lead_activities.py`, `test_whatsapp.py`,
`test_audit.py`, `test_auth.py`, `test_permissions.py`, `test_roles.py`, `test_dashboard.py`,
`test_inventory.py` and `test_search.py` all still pass.

### Known gaps / follow-ups for a later phase

1. **No real scraping — by instruction.** Six sources (Google Maps, Justdial, Facebook,
   Instagram, IndiaMART, wedding directories) ship as registered `PlannedProvider` classes
   that are discoverable and API-validatable but refuse to run. Each is governed by terms of
   service and, in most cases, an official API with credentials and quota (Google Places,
   Meta Graph, IndiaMART's lead API) or a licensed feed. Implementing one means replacing a
   class body — no change to the service, endpoints, schemas or database.

2. **Imports run synchronously inside the request.** Same shape as the WhatsApp dispatch gap.
   Runs are bounded by `limit` (max 1000) so this is safe with the offline providers, but a
   network-bound provider fetching 1000 listings will exceed a request timeout. The
   `ImportJob` lifecycle (`PENDING → RUNNING → terminal`) is already shaped for a worker to
   pick up, and `collect()` is already `async`, so moving it needs no interface change.
   **This is the first thing to add alongside a real provider.**

3. **CSV uploads cannot be retried.** The uploaded bytes are not retained — storing them would
   turn the CRM into a document store and duplicate a file the operator already has. The retry
   endpoint returns a clear "re-upload the file instead" message. Re-uploading is harmless
   because deduplication makes it a no-op.

4. **Collected extras live in `remarks`, not columns.** `rating`, `review_count`, `categories`,
   `pincode` and `source_url` have no home in the `leads` table, so they are folded into a
   readable `remarks` block. This kept the phase strictly additive — no ERP-adjacent schema
   widened to hold scrape metadata — but they are not queryable. Promoting them to real
   columns (or a `lead_metadata` JSONB column) is a Lead-model change for a later phase.

5. **A lead still stores only two phone numbers.** `NormalizedLead` carries every number a
   source exposes and deduplication checks all of them, but persistence flattens to `phone` +
   `whatsapp`; any third number goes to `remarks`. A `lead_contacts` child table would be the
   proper fix if multi-number businesses turn out to be common.

6. **Business-name+city matching is exact after normalisation, not fuzzy.** "Sunrise
   Photography" and "Sunrise Photo Studio" in the same city are treated as different
   businesses. Fuzzy matching (trigram similarity via `pg_trgm`) would catch more duplicates
   but risks false merges, which is the more expensive error — so the conservative rule was
   chosen deliberately. Revisit with real scraped data volume.

7. **No scheduled/recurring imports.** Every run is triggered explicitly. There is no poller,
   the same gap as `scheduled_at` in the campaign module.

8. **Pre-existing ERP test failures persist, unrelated to this module.** `test_erp.py`,
   `test_production.py` and `test_delivery_payment.py` still fail on the soft-deleted
   `Photographer` (`ab3dd978-...`) fixture documented in all three previous phases —
   **re-confirmed identical here**, and confirmed to fail in isolation on the Orders creation
   path, which this module never touches. Untouched: fixing them means editing ERP test
   fixtures, which this phase's scope rule puts out of bounds.

---

## Google Maps Lead Provider

**Phase goal.** Implement the first *real* lead provider — Google Maps — behind the existing
`LeadProvider` interface, so that a search like "Wedding Photographer Thrissur" collects live
photography businesses into the existing lead pipeline.

Scope note: this phase touched **only** the collection path. WhatsApp, Lead Management, Orders,
Inventory, Payments, Production, Delivery, Dashboard and Authentication were not modified. No
new endpoint was added — `POST /api/v1/leads/import` was reused exactly as it stood. The
`Lead` model, the `ImportJob` model and the database schema were **not** changed, so this phase
needed **no Alembic migration**.

### Checklist

- [x] `GoogleMapsLeadProvider` in `app/services/lead_providers/google_maps.py`, implementing
      the existing `search(query)` / `collect()` / `normalize()` contract.
- [x] Built on the **official Google Places API** (Text Search + Place Details), not scraping.
- [x] Registered under the existing key `google_maps`, replacing the `PlannedProvider` stub —
      which was deleted from `planned.py`.
- [x] Collects every field the brief listed: business name, phone number(s), website, Google
      Maps URL, address, city, district, state, postal code, latitude, longitude, rating,
      review count, business category, and opening hours.
- [x] Google `address_components` split into the CRM's `city` / `district` / `state` /
      `country` / `pincode` columns, with `sublocality` / `postal_town` fallbacks.
- [x] Returns `NormalizedLead` objects the Lead Collection Engine already supports — no new
      DTO, no change to `NormalizedLead`.
- [x] **Reuses the existing deduplication pipeline** unchanged; the provider never touches the
      `Lead` table and inserts nothing itself.
- [x] Uses the existing `ImportJob` lifecycle — `total_found`, `new_leads`, `updated_leads`,
      `duplicate_leads`, `failed_records` and `logs` are all maintained by `LeadImportService`
      exactly as before.
- [x] Per-business error isolation: a failing business never stops the import, and every
      failure is recorded in the job's `logs`.
- [x] All configuration read from environment variables via `app/core/config.py` —
      `GOOGLE_MAPS_API_KEY`, `GOOGLE_MAPS_BASE_URL`, `GOOGLE_MAPS_REGION`,
      `GOOGLE_MAPS_LANGUAGE`, `GOOGLE_MAPS_TIMEOUT_SECONDS`, `GOOGLE_MAPS_FETCH_DETAILS`,
      `GOOGLE_MAPS_MAX_PAGES`. **No API key anywhere in code.**
- [x] `is_available` computed from configuration: with no key the provider reports itself
      unavailable and refuses with the setting name to fix.
- [x] `httpx` added to `requirements.txt`, imported **lazily** so an image without it starts
      normally and fails only that provider.
- [x] Integration suite `tests/test_google_maps_import.py` — 7 sections covering provider
      initialization, search execution, normalization, the import pipeline, duplicate
      handling, import statistics and error handling.
- [x] Existing `tests/test_lead_import.py` updated (it asserted `google_maps` was an
      unimplemented stub) and re-run.
- [x] Full backend suite re-run for regressions.

### Notable findings

**The limit had to be applied before the Details fan-out, not after.** Google's Text Search
returns 20 results per page and paginates to 60, but returns neither a phone number nor a
website — those come only from Place Details, which is billed *per call*. Applying
`context.limit` after collecting all search pages would have made `limit=5` cost 20 Details
calls. The limit is therefore applied to the search results before any Details call is made,
and the test suite asserts the call count directly (`limit=5` over 20 available results costs
exactly 5 Details calls) rather than only asserting the returned records — the cost model is
the part that bites in production, so it is tested as behaviour.

**A failed Place Details lookup is not a failed business.** The Text Search half of that
record is still a real listing, so it is retained with a `detail_error` breadcrumb rather than
discarded; it then fails validation on its own merits (no phone number) and is counted and
logged by the engine like any other unusable record. This kept the "one failure never stops the
run" guarantee at the level the engine already implements it, instead of adding a second,
provider-local notion of failure.

**Providers needed to be able to say *why* they are unavailable.** The base class's refusal
message was hardcoded to "declared but not yet implemented", which would have been actively
misleading for a fully-implemented provider that is merely missing an API key — it sends an
operator looking for a missing feature instead of a missing config value. Added an overridable
`unavailable_reason` property on `LeadProvider`; `describe()` now surfaces it to the provider
listing endpoint too. Planned providers keep the original wording.

**A city fallback was needed to keep deduplication working.** `normalize_business_key` returns
no key unless *both* business name and city are present, so a Google record with no `locality`
component (common for a listing on a highway or in an unincorporated area) would silently lose
the business-name+city duplicate rule and re-import next month. Added a conservative fallback
that derives the city from the formatted address, returning `None` rather than guessing when
the address shape does not match — a wrong city creates false merges, which is the more
expensive error.

### Verification

```
python tests/test_google_maps_import.py        # ALL 7 sections PASS
python tests/test_lead_import.py               # ALL 8 sections PASS (updated + re-run)
```

No migration was generated or needed — this phase added no column, table or enum value.
`LeadSource.GOOGLE_MAPS` already existed from the Lead Management phase.

Full sweep: `test_audit.py`, `test_auth.py`, `test_dashboard.py`, `test_google_maps_import.py`,
`test_inventory.py`, `test_lead_activities.py`, `test_lead_import.py`, `test_leads.py`,
`test_permissions.py`, `test_roles.py`, `test_search.py` and `test_whatsapp.py` all **PASS**
(12 suites). `test_erp.py`, `test_production.py` and `test_delivery_payment.py` fail on the
**pre-existing** soft-deleted `Photographer` fixture (`ab3dd978-...`) documented in all four
previous phases — re-confirmed identical here, and the row was verified in the database to be
`is_deleted=True` with a `created_at` predating this phase.

### Known gaps / follow-ups for a later phase

1. **Imports still run synchronously inside the request.** This is now the *pressing* version
   of the gap flagged in the previous phase, because the provider is genuinely network-bound: a
   `limit=60` run makes 3 search calls plus 60 Place Details calls. Details calls are already
   issued concurrently (bounded at 5 in flight) which keeps a typical run to a few seconds, but
   a large run against a slow network will still approach a request timeout. The `ImportJob`
   lifecycle and the async `collect()` are already shaped for a background worker; moving it
   needs no interface change. **This is the first thing to add next.**

2. **Google returns no email address and no owner name.** Places exposes neither, so
   `emails` is always empty and `owner_name` is always `None` for this provider. Both were left
   empty rather than derived — scraping the business website for an address is a different
   integration with different consent implications, and guessing a contact name from a business
   name would let `_build_enrichment` overwrite nothing but would pollute the CRM. Leads from
   Google are therefore deduplicated on phone and name+city, never on email.

3. **Opening hours are collected but have nowhere to live.** They are retained on the record's
   `raw` payload and readable via `GoogleMapsLeadProvider.opening_hours(raw)`, but the `leads`
   table has no column for them so they are not persisted as a queryable field. This is the
   same "collected extras live in remarks" gap already recorded for `rating` / `review_count` /
   `categories`; a `lead_metadata` JSONB column would fix the whole class at once.

4. **Pagination is capped at Google's own 3-page / 60-result ceiling.** A query needing more
   than 60 businesses must be narrowed (by city, by more specific term) and run again.
   `GOOGLE_MAPS_MAX_PAGES` makes the ceiling configurable but Google will not serve past it.

5. **No caching of Place Details.** Re-running the same search re-fetches every Detail, and is
   billed again, even though deduplication means almost nothing new is written. Caching
   `place_id → details` (even briefly) would cut the cost of a repeated survey substantially.
   Deliberately not built here: it is a cost optimisation, not a correctness one, and it wants
   real usage data to size.

6. **The API key is a single global credential.** There is no per-user or per-tenant key and no
   spend cap enforced in the application — quota exhaustion is detected and reported
   (`OVER_QUERY_LIMIT` fails the run with a billing-actionable message) but not prevented.

---

## Instagram Lead Provider

**Phase goal.** Implement an Instagram lead provider behind the existing `LeadProvider`
interface, so that a search like "Wedding Photographer Kerala" discovers photography
businesses on Instagram and imports them through the existing Lead Collection Engine.

Scope note: this phase touched **only** the collection path. ERP, Orders, Inventory, WhatsApp
Campaigns, Authentication and Lead Management were not modified. No new endpoint was added —
`POST /api/v1/leads/import` was reused exactly as it stood. The `Lead` model, the `ImportJob`
model and the database schema were **not** changed, so this phase needed **no Alembic
migration**; `LeadSource.INSTAGRAM` already existed from the Lead Management phase.

### Checklist

- [x] `InstagramLeadProvider` in `app/services/lead_providers/instagram.py`, implementing the
      existing `search(query)` / `collect()` / `normalize()` contract.
- [x] Built on the **official Instagram Graph API** (hashtag search + Business Discovery), not
      scraping.
- [x] Registered under the existing key `instagram`, replacing the `PlannedProvider` stub —
      which was deleted from `planned.py`.
- [x] Supports all five documented search forms: "Wedding Photographer Kerala",
      "Photographer Kozhikode", "Photography Studio Kochi", "Wedding Photography Thrissur",
      "Pre Wedding Photography Kerala".
- [x] Collects every publicly available field the brief listed: business name, username,
      profile URL, bio, phone, email, website, WhatsApp number, address, city, state,
      followers count, following count, posts count, business category, profile image URL and
      verified status.
- [x] Returns `NormalizedLead` objects the engine already supports — no new DTO, no change to
      `NormalizedLead`.
- [x] **Reuses the existing deduplication pipeline** unchanged; the provider never touches the
      `Lead` table and inserts nothing itself.
- [x] Uses the existing `ImportJob` lifecycle — `total_found`, `new_leads`, `updated_leads`,
      `duplicate_leads`, `failed_records` and `logs` are all maintained by `LeadImportService`
      exactly as before.
- [x] Per-profile error isolation: a failing profile never stops the import, and every failure
      is recorded in the job's `logs`.
- [x] All configuration read from environment variables via `app/core/config.py` —
      `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `INSTAGRAM_GRAPH_BASE_URL`,
      `INSTAGRAM_GRAPH_API_VERSION`, `INSTAGRAM_TIMEOUT_SECONDS`, `INSTAGRAM_CONCURRENCY`,
      `INSTAGRAM_MAX_PAGES`, `INSTAGRAM_REQUIRE_CONTACT`, `INSTAGRAM_MIN_FOLLOWERS`.
      **No token or account id anywhere in code.**
- [x] `is_available` computed from configuration: with either credential missing the provider
      reports itself unavailable and names the specific setting to fix.
- [x] Integration suite `tests/test_instagram_import.py` — 8 sections covering provider
      initialization, search execution, profile collection, normalization, the import
      pipeline, duplicate detection, import statistics and error handling.
- [x] Existing `tests/test_lead_import.py` updated (it asserted `instagram` was an
      unimplemented stub) and re-run.
- [x] Full backend suite re-run for regressions.

### Notable findings

**Instagram has no search endpoint, so the query had to be translated into hashtags.**
Business Discovery — the only sanctioned way to read another business's public profile — takes
an exact *username*, not a query. It cannot be asked "Wedding Photographer Kerala" at all. The
only query-shaped surface in the API is the hashtag endpoints, so `search()` translates the
operator's query into an ordered hashtag list (`#weddingphotographerkerala`,
`#weddingphotographer`, `#keralaphotography`, …) and `collect()` walks those hashtags' media to
harvest the authoring usernames, then runs Business Discovery on each. Discovery is therefore
two-phase, and the second phase is one call per profile — the same N+1 cost shape as the Google
Maps adapter, and handled the same way: `context.limit` is applied **before** the fan-out, and
lookups run at bounded concurrency. The test suite asserts this directly — 40 discoverable
profiles with `limit=10` must spend exactly 10 lookups.

**The hashtag list is ordered by precision, and that ordering is load-bearing.** Collection
walks the list only until it has enough candidates, so a run that fills its limit from
`#weddingphotographerkozhikode` never pays for the nationally-noisy `#weddingphotographer`.
Searching only the compound tag would return almost nothing; searching only the bare tag would
return the whole country. Both are needed, in that order.

**All the contact data is in free text, which made the bio parser the riskiest code here.**
Instagram exposes `biography`, `website` and follower counts as structured fields — but the
phone number, WhatsApp number, email and address are not fields at all. Photographers write
them into the bio: `"📍 Kozhikode, Kerala | 📞 +91 98470 12345 | WhatsApp 9847012345"`. So
`_parse_bio` does the job Google's `address_components` did for the previous provider, and
every extraction in it is deliberately **conservative — it returns nothing rather than
guessing**. The reason is asymmetric cost: a missing phone means one lead is skipped and
logged, while a *wrong* phone silently merges the record onto an unrelated existing lead
(phone is the highest-confidence duplicate rule) and corrupts a row a human may have curated.
Under-extraction is recoverable; over-extraction is not. Concretely:

- Cities are matched against a **known vocabulary** (`_KNOWN_CITIES`), not parsed generically.
  A bio reading "📍 Kozhikode | Destination weddings worldwide" would give a general-purpose
  parser "Destination" or "Worldwide" as the city — and a wrong city feeds the
  business-name+city duplicate rule, so it can merge two unrelated studios or split one across
  two rows. An unrecognised place yields no city, and the lead imports without one.
- A number is only treated as **WhatsApp when the bio explicitly labels it** so (in words or a
  `wa.me` link). Promoting an unlabelled second number would have the CRM's messaging features
  dial a landline that cannot receive messages.
- The 📍 marker does **not** by itself produce an address: "📍 Kozhikode, Kerala" is a city and
  state the record already carries in structured form, so copying it into `address` would
  duplicate data rather than add any. A segment consisting only of known place names is
  rejected; a street address always carries something more ("3rd Floor, MG Road, Thrissur").
- Pincode extraction strips phone-shaped substrings first, so a 10-digit mobile cannot donate
  six of its digits to a false pincode match.

**A profile that Business Discovery cannot resolve is dropped, not counted as a failure.**
This is the one place the adapter deliberately differs from the Google Maps one. There, a
failed Place Details call still leaves a real listing worth keeping, so the record is retained
with a breadcrumb. Here, a failed lookup leaves a username and nothing else — no name, no bio,
no contact route — so there is nothing to import. Personal accounts (which Business Discovery
refuses by design) are the common case, and counting each one as a `failed_record` would make
that counter useless as a signal that something is actually wrong. They are dropped during
collection and logged. `failed_records` is reserved for profiles that *were* collected and
still could not become leads.

**Candidate over-collection.** Because a fraction of harvested usernames turn out to be
personal accounts, `collect()` gathers `limit × 2` candidates (capped at 300) so that a
`limit=20` run usually returns 20 profiles rather than 12. Kept deliberately small: every
surplus candidate that *does* resolve is a lookup spent past the limit.

**Both credentials are required for availability, and the refusal says which is missing.**
Business Discovery is issued *as* an account — a token with no `INSTAGRAM_BUSINESS_ACCOUNT_ID`
has nothing to ask on behalf of. `is_available` therefore requires both, and
`unavailable_reason` names exactly the one(s) unset rather than listing both generically, so an
operator is sent to the right environment variable.

**Meta reports its errors in the body with HTTP 400, so the body is parsed before the status
code is judged.** That is the only way to distinguish an expired token (fatal — fails the run,
because it applies identically to every remaining profile) from a personal account (ordinary —
drops one record). `_FATAL_ERROR_CODES` / `_FATAL_ERROR_SUBCODES` enumerate the credential,
permission and rate-limit codes that qualify; everything else is contained per-record.

### Verification

```
python tests/test_instagram_import.py         # ALL 8 sections PASS
python tests/test_lead_import.py              # ALL 8 sections PASS (updated + re-run)
python tests/test_google_maps_import.py       # ALL 7 sections PASS
```

No migration was generated or needed — this phase added no column, table or enum value.

Full sweep: `test_audit.py`, `test_auth.py`, `test_dashboard.py`, `test_google_maps_import.py`,
`test_instagram_import.py`, `test_inventory.py`, `test_lead_activities.py`,
`test_lead_import.py`, `test_leads.py`, `test_permissions.py`, `test_roles.py`,
`test_search.py` and `test_whatsapp.py` all **PASS** (13 suites). `test_erp.py`,
`test_production.py` and `test_delivery_payment.py` fail on the **pre-existing** soft-deleted
`Photographer` fixture (`ab3dd978-...`) documented in all five previous phases — re-confirmed
identical here, and none of the three touches the collection path.

### Known gaps / follow-ups for a later phase

1. **Imports still run synchronously inside the request.** Unchanged from the previous phase
   and now compounded: an Instagram run makes hashtag-resolution calls, media-page calls, and
   one Business Discovery call per profile. Lookups are concurrent (bounded at
   `INSTAGRAM_CONCURRENCY`), but a large run against a slow network will approach a request
   timeout. The `ImportJob` lifecycle and the async `collect()` are already shaped for a
   background worker; moving it needs no interface change. **Still the first thing to add
   next.**

2. **Hashtag discovery is a proxy for search, and an imperfect one.** The candidates are
   whoever posted recently under a hashtag, which is not the same population as "photography
   businesses in this city" — it includes couples, guests and venues who tagged the same
   thing. Business Discovery filters most of them out (they are personal accounts) and
   `INSTAGRAM_MIN_FOLLOWERS` filters more, but precision here is structurally lower than a
   directory source's. Expect a higher drop rate than Google Maps and size `limit` accordingly.

3. **`INSTAGRAM_REQUIRE_CONTACT` is defined and documented but not yet enforced as a collection
   filter.** Records with no phone are currently rejected downstream by
   `NormalizedLead.is_valid()` and counted as failed records, which is the same end state; the
   setting exists so a later change can drop them during collection instead and keep
   `failed_records` cleaner. Wiring it is a small, isolated change to `_is_worth_importing`.

4. **The city vocabulary is a hand-maintained list.** `_KNOWN_CITIES` covers Kerala's districts,
   frequently-seen towns and neighbouring metros. A studio in an unlisted town imports without
   a city, which disables the name+city duplicate rule for it. Extending the list is how the
   provider's geographic reach grows; a gazetteer lookup would fix the whole class at once but
   is a different dependency decision.

5. **Followers / following / posts / verified / profile image live in `remarks`, not columns.**
   Same "collected extras have nowhere to live" gap already recorded for Google's rating and
   review count. These are genuinely useful qualifying signals — "142,000 followers, Verified"
   is exactly what makes a lead worth calling first — so a `lead_metadata` JSONB column would
   pay off more here than it did for the previous provider, and would fix both at once.

6. **No caching of Business Discovery results.** Re-running the same search re-fetches every
   profile and re-spends the rate-limit budget, even though deduplication means almost nothing
   new is written. Deliberately not built: it is a cost optimisation, not a correctness one.

7. **Long-lived tokens expire after 60 days.** Expiry is detected and reported with an
   actionable message (the run fails with "set a fresh INSTAGRAM_ACCESS_TOKEN") but there is no
   automatic refresh and no proactive expiry warning. A token refresh job is the real fix.

---

## Follow-up & Task Management Module

**Status:** Complete

**Scope:** A follow-up engine that tells employees which leads need action today — task CRUD,
assignment, completion, rescheduling, cancellation, the today/upcoming/overdue worklists,
statistics, and automatic task creation from campaign replies and lead status changes. Every
follow-up action emits a `LeadActivity`.

Explicitly out of scope, by instruction: **notifications** and **background schedulers**
(both deferred to a later phase — see the gaps below, and `walkthrough.md` §5 for how the
absence of a scheduler shaped the overdue query rather than being stubbed). ERP modules,
Orders, Inventory, Production, Billing and Authentication were not modified.

### Checklist

- [x] `app/models/follow_up.py` — `FollowUpTask` with all specified fields, plus
      `FollowUpType` (Call/WhatsApp/Meeting/Reminder/Email), `FollowUpPriority`
      (Low/Medium/High/Urgent) and `FollowUpStatus` (Pending/Completed/Cancelled/Overdue).
      Soft delete, optimistic locking, three composite indexes matching the hot queries.
- [x] `app/models/lead_activity.py` — +5 `ActivityType` members (`TASK_CREATED`,
      `TASK_COMPLETED`, `TASK_RESCHEDULED`, `TASK_CANCELLED`, `MEETING_SCHEDULED`).
- [x] `app/repositories/follow_up.py` — CRUD, `get_due_between`, `get_overdue`,
      `find_open_duplicate`, aggregate helpers, + `AdminFollowUpTaskRepository`.
- [x] `app/services/follow_up.py` — `FollowUpTaskService` (CRUD, assign, complete,
      reschedule, cancel, today/upcoming/overdue, statistics) and
      `FollowUpAutomationService` (the four triggers).
- [x] `app/schemas/follow_up.py` — create/update/complete/reschedule/assign/cancel/response/
      list/statistics DTOs, with naive-datetime normalization at the boundary.
- [x] `app/api/v1/endpoints/followups.py` — all 9 specified routes, plus 4 lifecycle routes
      (`/assign`, `/complete`, `/reschedule`, `/cancel`). Literal paths declared before `/{id}`.
- [x] Automation wired: `whatsapp.py::record_reply` (reply triggers + the NEGOTIATION
      transition it causes) and `lead.py::update_lead` (manual NEGOTIATION transition).
- [x] Every lifecycle transition emits a `LeadActivity` in the same transaction.
- [x] RBAC — `followups:{view,create,update,delete,*}` seeded; granted `*` to Manager and
      view/create/update to Reception.
- [x] `alembic/versions/9dcc5194e0bb_add_follow_up_task_management.py` — `follow_up_tasks`
      table + hand-added `ALTER TYPE lead_activity_type ADD VALUE` statements (autogenerate
      does not diff enum members) + enum cleanup on downgrade. Applied successfully.
- [x] `tests/test_followups.py` — 15-section integration suite, all passing.
- [x] Full regression sweep — 13/13 pre-existing suites pass; the 3 ERP suites fail on the
      documented pre-existing `Photographer` fixture only.

### Notable finding

The automation contract ("a follow-up failure must never cost us the triggering event") was
**not** satisfied by the obvious `try/except Exception`. A DB-level error poisons the
SQLAlchemy session, so the caller's own later `commit()` still failed with
`PendingRollbackError` — the swallow defeated itself and the reply was lost anyway. Fixed by
running the automation write inside a SAVEPOINT (`db.begin_nested()`), and the test now
asserts both halves: the call returns `None` **and** the caller can still commit real work.
A bare try/except passes the first and fails the second. Full detail in `walkthrough.md` §8.

### Known gaps / follow-ups for a later phase

1. **No background scheduler, so nothing writes the stored `OVERDUE` status.** By
   instruction. The overdue query is deliberately written to derive overdue-ness
   (`status == PENDING AND scheduled_at < now`) OR-ed with the stored value, so the worklist
   is correct today and the sweeper — when it lands — only has to flip the stored value with
   **no query changes**. The one live consequence: a row's stored `status` may read `PENDING`
   while it is in fact overdue, so anything reading `status` directly (a future report, an
   export) must use the same rule rather than trusting the column.

2. **No notifications.** By instruction. The service emits log lines and `LeadActivity` rows
   at every transition, which is the natural place a notification dispatch would hook in; no
   interface change is needed to add it.

3. **Day boundaries are computed in UTC.** "Today" rolls over at 05:30 for an IST team. This
   is the most user-visible limitation in the module. The fix is a configured business
   timezone in `app/core/config.py` threaded through `day_bounds()` — deliberately not
   hardcoded to a `+05:30` offset, which would break the moment the business has a second
   location. **Recommended as the first thing to add next.**

4. **The `days` window for "upcoming" is a query parameter with a 7-day default, not a
   per-user preference.** Fine for now; a saved per-employee default belongs with a wider
   user-preferences feature rather than being special-cased here.

5. **Automated task delays (2h/4h/24h/1h) are hardcoded in `AUTOMATION_RULES`.** They are
   expressed as data in one dictionary rather than scattered through branching, so making
   them DB-configurable is a contained change — but it is a change. Worth doing once a
   manager asks to tune them without a deploy.

6. **No recurring or dependent tasks.** Every task is a single independent item; there is no
   "call again every week until they answer" and no "task B unblocks when task A completes".
   Neither was specified, and both would need a genuine scheduler (gap 1) to be useful.

7. **Statistics are computed live on every request.** Seven `COUNT` queries plus three
   `GROUP BY` queries per call, all indexed and fast at current data volumes. If the
   statistics endpoint becomes a dashboard polling target, it wants caching or a materialized
   rollup — not a rewrite, but worth watching.

8. **No bulk operations.** Completing or reassigning twenty tasks is twenty API calls. A
   `PUT /followups/bulk` would be a straightforward addition to the existing service methods
   once the frontend needs it.

---

## WhatsApp Cloud API Provider

**Status:** Complete

**Scope:** Replace the NoOp WhatsApp provider with a production-ready Meta WhatsApp Cloud API
implementation behind the existing `WhatsAppProvider` port — message sending, template
sending, status mapping, webhook verification, reply handling and error handling for every
failure mode named in the specification.

Strictly limited to the provider and its inbound webhook. Lead Management, the Follow-up
engine, ERP modules, Orders, Inventory, Authentication and RBAC were **not** modified. The
campaign services were not modified except for one additive webhook-routing class — no
campaign business logic moved into the provider, and `start_campaign`,
`apply_delivery_status` and `record_reply` are unchanged.

### Checklist

- [x] `app/core/config.py` — **+14 settings**: `WHATSAPP_ACCESS_TOKEN`,
      `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_VERIFY_TOKEN`,
      `WHATSAPP_APP_SECRET`, `GRAPH_API_VERSION`, plus provider selection, retry budget,
      timeout, default country code, template toggle and signature-requirement flag. No
      credential hardcoded anywhere.
- [x] `.env` — the same block, all credentials left empty so the provider stays disabled and
      `WHATSAPP_PROVIDER=noop` keeps sends simulated until an operator opts in.
- [x] `app/services/whatsapp_provider.py` — port extended with `send_template()`,
      `get_message_status()` and `validate_configuration()` as **concrete** methods with
      working defaults (so no existing adapter breaks), plus `ProviderConfigurationResult` /
      `ProviderMessageStatus` DTOs, `retryable`/`error_code` on `ProviderSendResult`, and a
      settings-driven factory that lazily imports adapters.
- [x] `app/services/whatsapp_cloud.py` — **new.** `WhatsAppCloudProvider` (all four methods
      + `health_check`), `MetaWebhookVerifier` (GET challenge + POST HMAC),
      `MetaWebhookParser` (Meta JSON → flat events), `classify_graph_error` and
      `normalize_msisdn` as pure, independently testable functions.
- [x] Message sending — plain text, template messages, parameterized templates (positional
      body + header components), and language selection with locale normalisation
      (`pt-BR` → `pt_BR`).
- [x] Status handling — Meta's `sent`/`accepted`/`delivered`/`read`/`failed` mapped onto
      `CampaignRecipient` statuses; `deleted` deliberately ignored; `QUEUED`/`REPLIED` left as
      CRM-internal states with no Meta equivalent.
- [x] Webhook — `GET /whatsapp/webhook/meta` verifies the subscription challenge and echoes it
      as plain text; `POST /whatsapp/webhook/meta` verifies `X-Hub-Signature-256` over the
      **raw body** and rejects invalid signatures with 403. **No JWT on either**, per
      instruction; both fail closed when their secret is unset.
- [x] Reply handling — `MetaWebhookService` routes parsed events into the existing pipeline
      (`apply_delivery_status` / `record_reply`). No duplicated business logic; the monotonic
      status guard, lead-status automation, timeline entries and follow-up triggers are all
      the existing implementations, reached unchanged.
- [x] Error handling — 429 rate limits (retried, honouring `Retry-After`), expired access
      token (**not** retried), invalid template (**not** retried), network timeout (retried),
      provider unavailable (retried), bad recipient (**not** retried). Nothing raises into
      campaign execution; every failure lands on the recipient row with its Meta error code.
- [x] `app/api/v1/endpoints/whatsapp.py` — **+3 routes** (Meta webhook GET/POST, provider
      status). Existing routes untouched.
- [x] `app/api/deps.py` — `get_meta_webhook_service` added; existing providers unchanged.
- [x] `tests/test_whatsapp_cloud.py` — 11-section suite, Graph API fully mocked via
      `httpx.MockTransport`. **No real WhatsApp account required.** Covers configuration
      validation, message sending, template sending, status mapping, webhook verification,
      reply handling and provider failures, plus phone normalisation, campaign execution and
      registry selection.
- [x] Full regression sweep — **15/15 non-ERP suites pass**, including the pre-existing
      `tests/test_whatsapp.py`. The 3 ERP suites fail on the documented pre-existing
      `Photographer` fixture, confirmed identical on a stashed (untouched) tree.

### Notable findings

**1. The rendered-string contract cannot survive contact with Meta, and the fix was already
in the port.** Meta rejects free text outside a 24-hour service window (error 131047), so
campaign messaging *must* use pre-registered templates. Rather than widening the port (which
would make it Meta-shaped) or moving rendering into the adapter (which the spec forbids), the
adapter uses `template_name` and `language` — which the port already forwarded "for vendors
that require a pre-registered template identifier". **Operational consequence: a CRM template's
`name` must match an approved template in Meta Business Manager.** Detail in `walkthrough.md` §3.

**2. Retrying every failure would have been actively harmful.** An expired token retried once
per recipient turns a five-minute credential rotation into 15,000 doomed calls against Meta's
rate limiter. Auth, template and bad-recipient errors are classified as **non**-retryable and
fail immediately; only 429s, timeouts and 5xx are retried. Meta returns **400 for both** an
expired token and a rate limit, so classification is by error *code* first and HTTP status
second. The tests assert **call counts**, not just results — a result-only assertion passes
even with the retry policy inverted. Detail in §4.

**3. The test suite caught a real webhook-parsing bug.** The first parser used
`(entry or {}).get(...)`, which guards `None` but lets a *string* through to the next `.get()`,
raising `AttributeError`. Since **a webhook that raises is one Meta retries until it disables
the subscription**, this would have been a production outage triggered by one malformed
payload. Fixed with a type-checking `_as_dict()` helper at every nested access. A suite that
only fed well-formed payloads would have shipped it. Detail in §9.

**4. Webhook signature verification must read the raw body.** The endpoint deliberately does
not declare a Pydantic body model: the HMAC covers the exact bytes Meta sent, and letting
FastAPI parse-then-re-serialise produces different bytes whose signature never matches. This is
the easiest way to get webhook verification subtly and permanently wrong. Detail in §7.

### Known gaps / follow-ups for a later phase

1. **A retried timeout can duplicate a message.** Meta's `/messages` endpoint has no
   idempotency key, so a request that timed out *after* Meta processed it is indistinguishable
   from one that never arrived. Bounded retries and never-retrying-a-2xx limit the exposure;
   a client-side dedupe window keyed by (recipient, template, minute) is the real fix and is
   worth adding before high-volume sending.

2. **Dispatch is still synchronous inside the HTTP request.** Real Meta latency is
   ~100–300ms/message, so a 1,000-lead campaign is now a multi-minute request. **A task queue
   is the single most valuable next addition.** The port is already async, so moving the
   dispatch loop into a worker requires no interface change. Retry backoff is capped at 30s
   specifically because of this constraint.

3. **Rate limiting is reactive.** The adapter retries a 429 rather than pacing sends beneath
   Meta's tier limit. A token-bucket throttle in the campaign loop would be strictly better
   and belongs with the task queue (gap 2).

4. **`reply_type` classification is keyword-based.** Safe (it returns `None` when unsure, so an
   ambiguous reply never writes a lead off as LOST) but it will miss Malayalam/Hindi replies
   and indirect phrasing. The rules are data in one list, so replacing them is contained.

5. **Template parameters are a single positional value.** The whole rendered body is passed as
   `{{1}}`. A Meta template with three separate placeholders needs the CRM to model its
   parameter *structure* — a `provider_template_name` + parameter-mapping column on
   `whatsapp_templates`. First thing to add when a template needs more than one variable.

6. **No template-catalogue sync.** Nothing validates a CRM template name against the WABA's
   approved template list, so a mismatch fails at send time (132001) rather than at save time.
   A sync endpoint reading the catalogue would catch it earlier.

7. **The webhook has no replay/dedupe log.** Harmless for statuses (the monotonic rank guard
   makes a repeated status a no-op) but a re-delivered *reply* appends a second timeline entry.
   Storing seen message ids with a short TTL would close it.

8. **`get_message_status` returns `None` by design** — the Cloud API has no status-read
   endpoint; delivery state is push-only. Implemented explicitly rather than left inherited so
   the fact is documented where someone will look for it.


---

## Lead CRM Dashboard — Frontend Module

**Status:** Complete

**Scope:** Build the Lead CRM Dashboard as the CRM's landing page, consuming the **existing
backend APIs only**. This is the first phase of the project's pivot from a full Colour Lab ERP
to a Lead CRM focused on photographer acquisition.

**No backend business logic was modified.** No endpoint, service, repository, model, schema or
migration was touched — the entire phase is frontend. The ERP modules named as out of scope
(Orders, Production, Inventory, Payments, Deliveries, Customer Management) were **not** built
on and **not** deleted; their routes remain reachable by direct URL but are no longer part of
the sidebar navigation (see "Decisions taken" §3).

### Checklist

- [x] `src/features/leads/types.ts` — **new.** TypeScript mirrors of the backend response
      schemas (`LeadResponse`, `FollowUpTaskResponse`, `FollowUpStatisticsResponse`,
      `ImportJobResponse`, `WhatsAppCampaignResponse`, `CampaignRecipientResponse`) plus the
      seven status enums and the derived view-model types the widgets consume. A generic
      `Paginated<T>` captures the envelope every list endpoint returns.
- [x] `src/services/leads.ts` — **new.** All HTTP access for the domain:
      `leadsService` (list + `count`), `followUpsService` (today / statistics / complete /
      reschedule), `leadImportsService`, `campaignsService` (list + recipients) and
      `leadEmployeesService`. No component or hook calls axios directly.
- [x] `src/features/leads/hooks.ts` — **new.** All business logic: the eight-counter fan-out,
      the cross-campaign replies assembly, the task↔lead↔employee joins, the three chart
      aggregations, the campaign funnel, and the two follow-up mutations with their cache
      invalidation.
- [x] **Section 1 — Lead Summary Cards.** All eight counters (Total, New, Message Sent,
      Replied, Interested, Negotiation, Follow-up Today, Lost), each a drill-through link to a
      pre-filtered lead list. Loading, empty and error states all covered.
- [x] **Section 2 — Recent Replies.** Lead name, phone, reply preview (truncated), relative
      reply time with the absolute timestamp on hover, lead status badge and an Open Lead
      button.
- [x] **Section 3 — Today's Follow-ups.** Lead name, phone, scheduled time, follow-up type,
      assigned employee, plus working **Complete** and **Reschedule** actions. Reschedule opens
      a validated date/time dialog.
- [x] **Section 4 — Recent Lead Imports.** Provider, import time, leads imported, new,
      duplicate, failed and status — as a scrollable table on desktop, stacked cards on mobile.
- [x] **Section 5 — WhatsApp Campaign Summary.** Campaign name, sent, delivered, read, replies
      and interested leads.
- [x] **Section 6 — Quick Actions.** Import Leads, Create Campaign, View Leads and Today's
      Follow-ups, each gated on its own permission and hidden when not held.
- [x] **Section 7 — Charts.** Lead Sources (donut), Lead Status Distribution (bar), Daily Lead
      Growth (14-day line) and Campaign Performance (grouped bar), all via the existing
      `recharts` dependency.
- [x] **Section 8 — Layout.** Uses the existing `AppLayout`, the existing UI component library
      (`Card`, `StatCard`, `Badge`, `Button`, `Dialog`, `Input`, `Textarea`, `Skeleton`,
      `EmptyState`, `ErrorState`, `LayoutHelpers`), TanStack Query for all server state,
      Zustand (`useAuthStore` for RBAC, `useNotificationStore` for mutation toasts), the
      existing RBAC guards, and a responsive 1/2/4-column grid.
- [x] **Section 9 — Architecture.** Feature-scoped under `src/features/leads/`
      (`types.ts` / `hooks.ts` / `components/` / `pages/`), matching the existing
      `src/features/*` shape. API logic in services, business logic in hooks, no duplicated
      components — two new reusable widgets (`DashboardSection`, `LeadStatusBadge`) absorb what
      would otherwise have been repeated six times.
- [x] `src/App.tsx` — the index route now renders `LeadDashboardPage`; seven Lead CRM routes
      added as placeholders so every link on the dashboard resolves.
- [x] `src/layouts/AppLayout.tsx` — sidebar repointed to Lead CRM navigation; `isNavItemActive`
      extracted so both the desktop and mobile navs share one active-route rule.
- [x] `src/tests/leadDashboard.test.tsx` — **new, 62 tests** across services, hooks, widget
      states, actions, RBAC and helpers.
- [x] **`npm test` passes: 191/191 across 10 files.** **`npm run build` succeeds.**

### Pre-existing breakage fixed to meet the verification requirement

Both `npm test` and `npm run build` were **already failing before this phase began**, from one
root cause: `ProductSelector` requires a `products` prop that two of its callers never passed.

- `npm run build` — 3 TypeScript errors (`AddItemDialog.tsx:96`, `OrderItemEditor.tsx:45,113`).
- `npm test` — 1 failing test (`orders.test.tsx`), `products.map` on `undefined`.

Both callers already received `products` in their own props and simply failed to forward it, so
the fix is two one-line prop additions. Reported here rather than folded in silently: it is ERP
code, outside this phase's scope, and touched only because the phase's verification criteria
could not otherwise be met.

### Decisions taken

**1. Recent Replies is assembled client-side, because no endpoint returns it.**
Reply text lives on `campaign_recipients.reply_text` and is reachable only per-campaign via
`GET /whatsapp/campaigns/{id}/recipients`. With backend changes out of scope, `useRecentReplies`
fans out over the five most recent campaigns, filters each to `message_status=REPLIED`, joins
each recipient to its lead, then merges and sorts by `replied_at`. **Consequence:** an N+1 of at
most six requests, and replies from leads never enrolled in a recent campaign do not appear. A
`GET /whatsapp/replies/recent` endpoint would collapse this to one request.

**2. The eight counters are eight separate requests.**
No endpoint returns a status histogram — `GET /dashboard` is entirely ERP (revenue, orders,
deliveries, invoices) and carries nothing lead-related. Each counter is therefore a
`GET /leads?status=X&limit=1` probe read for its `total`, which the backend computes ignoring
pagination. Payloads stay at one row each and TanStack Query issues them concurrently. The
alternative — fetching 500 leads and tallying client-side — is silently wrong past 500 rows.

**3. ERP frontend code was kept, not deleted.**
The sidebar now lists only Lead CRM destinations and `/` renders the Lead CRM dashboard, but the
Orders feature, the ERP dashboard and the ERP routes remain on disk and reachable by direct URL.
Chosen over deletion because it removes ERP from the product surface without discarding working
code and its passing tests.

**4. "Follow-up Today" counts tasks, not leads.**
It reads `GET /followups/statistics.due_today` — open tasks due today — rather than leads in
`FOLLOW_UP` status. These are different questions; the card carries a "Tasks due today" footer
so the figure is not misread.

**5. "Interested Leads" per campaign is computed, and is present-tense.**
Not a backend counter. `useCampaignSummary` intersects each campaign's recipients with leads
currently in `INTERESTED` status, so it reflects status *now*, not at send time. The column
header carries this as a tooltip.

### Known gaps / follow-ups for a later phase

1. **The Lead Sources and Daily Lead Growth charts describe a 500-lead sample, not the whole
   table.** `GET /leads` caps `limit` at 500 and there is no aggregation endpoint, so both
   charts aggregate the most recent 500 leads. The hook returns `isSampled`, and both chart
   subtitles say "most recent 500" when it is true — the figure is never presented as a
   full-table total. A `GET /leads/statistics` returning source and status histograms would fix
   this properly and would also collapse decision §2's eight requests into one.

2. **Recent Replies costs up to six requests and misses non-campaign replies** (decision §1).
   The single highest-value backend addition for this page.

3. **The lead sample is fetched once and shared, which bounds the name lookups.** Replies,
   follow-ups and campaign summary all resolve lead names from the same cached 500-lead query
   (one request, not three). A lead outside that sample degrades gracefully — the reply shows
   the phone number, the follow-up shows the task title — but is not resolved to a business
   name. Per-id lead fetches or an `ids` filter on `GET /leads` would close it.

4. **Employee names come from an unpaginated `GET /employees` fetch** capped at 200. A larger
   organisation would need the assignee name denormalised onto the follow-up response, or an
   `ids` filter.

5. **The dashboard's link destinations are placeholders.** `/leads`, `/leads/import`,
   `/leads/:id`, `/followups`, `/campaigns`, `/campaigns/new` and `/campaigns/:id` are
   permission-guarded stubs so no link 404s. Building them out is the next phase.

6. **No auto-refresh.** Data is fetched on mount and on explicit Refresh; there is no polling or
   websocket, so a reply arriving while the page is open is not shown until refresh. A
   `refetchInterval` on the replies and follow-ups queries is the cheap version.

7. **The production bundle is 1.14 MB (335 KB gzipped) and Vite warns about it.** Pre-existing
   and not worsened materially here, but the ERP feature code still ships in it. Route-level
   `React.lazy` splitting is the fix, and deleting the ERP frontend (decision §3) would help.

8. **`npm run lint` cannot run — `eslint` is not installed** in this project's `node_modules`
   despite the script existing in `package.json`. Typechecking is covered via `tsc` in
   `npm run build`, which passes clean.

## Lead Details Workspace — Frontend Phase

**Status:** Complete

**Scope:** The Lead Details page (`/leads/:id`) as the primary workspace for managing one lead —
profile, activity timeline, notes, follow-ups, WhatsApp history, quick actions and status panel,
built on the existing backend API. **No ERP functionality** was built or modified (Orders,
Payments, Inventory, Production, Delivery, Invoices, Photographers are untouched). Exactly one
backend line changed — see the Backend note below.

### Checklist

- [x] `src/features/leads/types.ts` — extended with `LeadActivity`, `LeadNote`, `ActivityType`
      (all 17 enum members), `LeadUpdatePayload`, `FollowUpCreatePayload`, `FollowUpCancelPayload`,
      `LeadWhatsAppHistoryEntry`, and `last_contacted_at` on `Lead`.
- [x] `src/services/leads.ts` — added `leadActivitiesService` (timeline paging),
      `leadNotesService` (list/create/update/remove across the two backend roots),
      `leadsService.update`, and `followUpsService.listByLead` / `.create` / `.cancel`.
- [x] `src/features/leads/detailHooks.ts` — 14 hooks: `useLead`, `useUpdateLead`,
      `useUpdateLeadStatus`, `useLeadActivities`, `useLeadNotes` + 3 note mutations,
      `useLeadFollowUps` + 4 lifecycle mutations, `useLeadWhatsAppHistory`.
- [x] `src/features/leads/utils.ts` — `mapsUrlFor`, `normalizePhone`, `telHref`, `whatsAppHref`,
      `externalHref`, `instagramHref`, `mailtoHref`, `formatAddress`.
- [x] Components: `LeadProfileCard`, `LeadActivityTimeline`, `LeadNotesSection`,
      `LeadFollowUpsSection`, `LeadWhatsAppHistory`, `LeadQuickActions`, `LeadStatusPanel`,
      `EditLeadDialog`, `CreateFollowUpDialog`. `RescheduleDialog` and `DashboardSection` were
      **reused** from the dashboard phase rather than reimplemented.
- [x] Page: `LeadDetailsPage` — composition, dialog state and per-section RBAC only.
- [x] Route wired into `src/App.tsx` — the `leads/:id` placeholder replaced with the real page,
      still behind `ProtectedRoute requiredPermission="leads:view"`.
- [x] All 8 specified sections built; all 18 profile fields, all 10 timeline events, all 7 quick
      actions, all 4 follow-up actions.
- [x] `src/tests/leadDetails.test.tsx` — 76 tests covering the six required areas (profile
      rendering, timeline loading, notes CRUD, follow-up actions, status updates, RBAC) plus the
      utils, services and hooks beneath them.
- [x] `npm run test` — 267/267 tests passing (11 files, including the new suite).
- [x] `npm run build` — `tsc` + `vite build` succeed with zero TypeScript errors.

### Backend change (one line)

`app/schemas/lead.py` — `last_contacted_at: datetime | None` added to **`LeadResponse` only**.

The column already exists on `Lead` and is already maintained by the WhatsApp module (stamped on
dispatch and on reply), but `LeadResponse` inherits `LeadBase`, which does not declare it — so the
value never reached the client. It was added to the response schema and deliberately **not** to
`LeadBase`/`LeadCreate`/`LeadUpdate`, which would have made server-maintained contact history
client-writable. No service, repository, endpoint, model or migration changed.

### Design decisions

1. **Google Maps URL is derived from `latitude`/`longitude`, not stored.** There is no
   `google_maps_url` column; the Maps import provider computes a `source_url` but `LeadImportService`
   folds it into the lead's free-text `remarks` instead of persisting it as a field. `mapsUrlFor()`
   builds the link from the coordinate columns — which covers Maps-sourced leads, the ones that have
   coordinates — and returns `null` otherwise, in which case the profile **hides the row** rather
   than rendering a dead link.

2. **WhatsApp history is a bounded client-side fan-out.** `GET /whatsapp/campaigns/{id}/recipients`
   has no `lead_id` filter and there is no lead-scoped message-history route, so the hook fetches
   recent campaigns, fans out over their recipients, and keeps rows matching this lead — the same
   pattern `useRecentReplies` established on the dashboard. Capped at
   `LEAD_CAMPAIGN_HISTORY_LIMIT = 10`, and the truncation is **reported** via `isSampled` rather
   than hidden, since a silently partial history reads as "never messaged".

3. **The timeline accumulates pages instead of replacing them.** `useLeadActivities` renders every
   page `0..n-1` through `useQueries` and concatenates, so Load More grows the list, each page is
   its own cache entry, and invalidation refreshes all loaded pages without collapsing back to one.
   Rows are de-duplicated by id, because an activity written between two page fetches shifts the
   boundary row and can deliver it twice.

4. **Status changes are confirmed and carry `version`.** A status change writes to the immutable
   timeline and moves dashboard counters, so it is two-step. `version` is sent so a change issued
   from a stale page returns 409 `VERSION_CONFLICT` instead of clobbering a concurrent edit; the
   panel renders that as readable text.

5. **Query keys nest under a shared `detail(leadId)` prefix**, so "refresh all related queries after
   update" is one `invalidateQueries` call covering profile, timeline, notes and follow-ups.
   `useUpdateLead` additionally invalidates the dashboard's `summary()`/`sample()` keys, since a
   status change makes those per-status counters wrong.

6. **The edit form submits a diff, not the whole form.** Only changed fields plus `version` are
   sent; a cleared optional field sends `null` (not `""`, which the backend's URL/email validators
   reject); and a no-op save closes without issuing a request. Sending the full form would turn any
   concurrent edit into silent data loss even when the two edits touched different fields.

7. **`Select`'s `placeholder` could not be used for "Unassigned".** It renders as
   `<option disabled hidden>`, so it cannot be re-selected — a form where a task could be assigned
   but never un-assigned. Both assignee selects use a real `{ label: 'Unassigned', value: '' }`
   option instead.

8. **Overdue requires open *and* `is_overdue`.** The server-computed flag is authoritative (there is
   no sweeper, so stored `status` can lag), but it can remain true on a task since completed — so
   the highlight and count require both, or a task completed two days late would show "Overdue"
   forever. Lifecycle actions render only on open tasks, since the backend 400s on closed ones.

9. **RBAC is per-control and mirrors the endpoints.** `leads:update` for edit/status/notes (notes
   reuse the lead permission set server-side), `followups:view`/`create`/`update` for the follow-up
   controls, `whatsapp:view`/`create` for WhatsApp. Copy Phone / Open WhatsApp / Call Now are
   **ungated** — they touch no API, and gating them would restrict nothing while making the rail
   feel broken. `EditLeadDialog` is unmounted, not merely hidden, without `leads:update`.

10. **"Send WhatsApp" opens a wa.me conversation.** There is no per-lead send endpoint — the backend
    dispatches per campaign (`POST /whatsapp/campaigns/{id}/start`) — so the action opens the chat
    rather than pretending a one-off API send exists. Still gated on `whatsapp:create`.

### Known gaps / follow-ups for a later phase

1. **WhatsApp history covers only the 10 most recent campaigns** (decision §2). A `lead_id` filter on
   the recipients endpoint, or a `GET /leads/{id}/whatsapp-history` route, would make it complete and
   collapse the fan-out to a single request. Highest-value backend addition for this page.

2. **Leads without coordinates show no Maps link** (decision §1), even when the importer captured a
   real Maps URL into `remarks`. A `google_maps_url` column populated from the provider's
   `source_url` would fix it properly.

3. **Author and assignee names come from an unpaginated `GET /employees`** capped at 200 — the same
   limitation the dashboard carries. Denormalising the author name onto `LeadNoteResponse` and
   `FollowUpTaskResponse` would remove the dependency.

4. **Timeline activity-type filtering is not exposed in the UI.** The endpoint and the service layer
   both support `activity_type`; the spec asked for pagination rather than filtering, so no control
   was built. Small addition when wanted.

5. **No follow-up edit or reassign.** `PUT /followups/{id}` and `PUT /followups/{id}/assign` exist and
   are unused — the spec listed create / complete / cancel / reschedule only.

6. **No auto-refresh.** Fetch-on-mount plus the explicit Refresh button; a reply arriving while the
   page is open is not shown until refreshed.

7. **The production bundle is now 1.19 MB (348 KB gzipped)**, up ~50 KB from this phase and still
   un-split. Route-level `React.lazy` remains the fix.

8. **`npm run lint` still cannot run — `eslint` is not installed** in `node_modules` despite the
   script existing in `package.json`. Pre-existing and unrelated to this phase; typechecking is
   covered by `tsc` inside `npm run build`, which passes clean.

---

## Lead Pipeline (Kanban Board) — Frontend Phase

**Status:** Complete

**Scope:** The Lead Pipeline board at `/leads` — every lead grouped into a column per status, with
drag-and-drop between columns, filters, sorting, per-column incremental loading, column totals and
per-card quick actions. **No ERP functionality** was built or modified (Orders, Payments,
Inventory, Production, Delivery, Invoices, Photographers are untouched). One backend enum value was
renamed — see the Backend change note below.

### Checklist

- [x] `app/models/lead.py` — `LeadStatus.CUSTOMER` renamed to `CONVERTED` (+ migration, + the two
      service call-sites). See "Backend change" below.
- [x] `alembic/versions/a1f4c7b93e02_rename_lead_status_customer_to_converted.py` — in-place
      Postgres enum rename, applied and verified against the live database.
- [x] `src/features/leads/types.ts` — `PipelineSort`, `PipelineFilters`, `PipelineColumnState`
      added; `LeadStatus` updated to `CONVERTED`.
- [x] `src/services/leads.ts` — `leadPipelineService.column()` (one filtered request per column)
      and `.moveToStatus()` (the narrow status-only write behind a drop), plus
      `followUpsService.pending()` for the cards' due-date badges.
- [x] `src/features/leads/pipelineUtils.ts` — `PIPELINE_COLUMNS`, `sortLeads` (4 comparators),
      `isMoveAllowed`, `hasActiveFilters`, `EMPTY_PIPELINE_FILTERS`, `PIPELINE_DND_MIME`.
- [x] `src/features/leads/pipelineHooks.ts` — `usePipelineBoard` (per-column paged fetching +
      accumulation + totals), `useMoveLeadStatus` (optimistic move with whole-board rollback),
      `usePipelineDragAndDrop` (drag state machine + toasts), `usePipelineFollowUpDueDates`,
      `usePipelineCreateFollowUp`, `usePipelineCreateNote`.
- [x] Components: `PipelineColumn`, `PipelineCard`, `PipelineFiltersBar`, `AddNoteDialog`.
      `CreateFollowUpDialog` and `LeadStatusBadge` were **reused** from earlier phases rather than
      reimplemented.
- [x] Page: `LeadPipelinePage` — composition, filter/sort state and dialog state only.
- [x] Route wired into `src/App.tsx` — the `leads` placeholder replaced with the real board, still
      behind `ProtectedRoute requiredPermission="leads:view"`.
- [x] All 9 columns; all 7 card fields; all 5 filters; all 4 sorts; all 4 quick actions; column
      totals; per-column Load More.
- [x] `src/tests/leadPipeline.test.tsx` — 72 tests covering the six required areas (column
      rendering, drag-and-drop, status updates, filters, sorting, RBAC) plus the utils, services
      and hooks beneath them.
- [x] `npm run test` — 339/339 passing (12 files, including the new suite).
- [x] `npm run build` — `tsc` + `vite build` succeed with zero TypeScript errors.
- [x] Backend regression: `tests/test_lead_activities.py`, `tests/test_whatsapp.py` and
      `tests/test_followups.py` all pass against the live database after the rename.

### Backend change (one enum value)

The brief specified a **`CONVERTED`** column, but `LeadStatus` had no such member — its
terminal-success value was `CUSTOMER`. Dropping a card on a "Converted" column would have sent an
invalid enum value and been rejected with a 422. Rather than label the column with a word the API
does not speak, the enum member was renamed (confirmed with the requester before doing so):

- `app/models/lead.py` — `CUSTOMER = "CUSTOMER"` → `CONVERTED = "CONVERTED"`.
- `app/services/lead.py:208` — the conversion-detection transition now compares against
  `LeadStatus.CONVERTED`.
- `app/services/whatsapp.py:105` — `_TERMINAL_LEAD_STATUSES`, the guard stopping an inbound reply
  from demoting a converted lead, now holds `LeadStatus.CONVERTED`.
- `alembic/versions/a1f4c7b93e02` — `ALTER TYPE lead_status RENAME VALUE 'CUSTOMER' TO 'CONVERTED'`.

**`app/models/photographer.py` declares a *separate* `LeadStatus` that keeps its own `CUSTOMER`
member**, on a different Postgres type (`leadstatus`, no underscore). It was deliberately left
alone, and both types were re-inspected in the database after the migration to confirm the rename
touched only `lead_status`. `app/services/photographer.py` is unchanged.

The rename is exact rather than additive: Postgres cannot drop an enum member, so an
add-plus-backfill would have left `CUSTOMER` permanently reachable. `RENAME VALUE` rewrites the
catalog label without rewriting a single row, and the downgrade is its exact inverse.

### Design decisions

1. **Nine columns, not eight.** The brief listed eight and omitted `CONTACTED`, which is a real,
   reachable status. A board without it would hide every lead sitting there and give them no column
   to be dragged out of, so it is rendered in its pipeline position between New and Message Sent.
   Confirmed with the requester.

2. **One request per column, not one for the board.** `GET /leads` caps `limit` at 500 and returns
   no status histogram. Fetching everything and grouping client-side would truncate silently and
   report per-column totals that only describe the first 500 rows. Nine filtered requests give each
   column an exact `total` from its own envelope and let one column paginate without refetching the
   rest.

3. **Native HTML5 drag-and-drop, no library.** No DnD library was installed, and adding one was not
   necessary. The native API keeps cards as plain elements that jsdom can exercise with real
   `dragStart`/`dragOver`/`drop` events — so the drag behaviour is genuinely unit tested rather than
   mocked away. The cost is that HTML5 drag supports neither keyboard nor touch, which is why every
   card also carries a **"Move…" select** performing the identical mutation through the identical
   code path. That control is not a fallback bolted on afterwards; it is the accessible primary path.

4. **The column is the drop target, not the card.** A lead can therefore be dropped into the empty
   space below the last card — and into an **empty column**, which would otherwise be the one place
   a card could never be moved to.

5. **`dragCounter` prevents highlight flicker.** `dragleave` fires when the pointer crosses into a
   *child* of the drop target, so a naive enter/leave toggle makes the column strobe as the cursor
   passes over each card. Enters minus leaves, clearing only at zero, is the fix — and is covered by
   a test that walks the exact enter/enter/leave/leave sequence.

6. **Optimism is a whole-board snapshot, not a per-card one.** A single move mutates several cache
   entries: the source column's page, the destination's page, and both columns' totals. Rolling back
   only the card would leave the counts wrong, so `onMutate` snapshots every entry under the board
   prefix via `getQueriesData` and `onError` restores all of them. `cancelQueries` runs first, or an
   in-flight column fetch resolving after the optimistic edit would snap the card back.

7. **Sorting is client-side, and the UI says so.** `GET /leads` accepts no `sort`/`order_by`
   parameter. Ordering is therefore applied per column after each page arrives — exact for a
   fully-loaded column, approximate for a partial one, since the server picks which 20 rows page 1
   holds. Every partially-loaded column header reads "Showing N of M" rather than implying a
   complete ranking.

8. **`LAST_CONTACTED` sinks never-contacted leads.** A null `last_contacted_at` is not "contacted
   long ago"; treating it as epoch 0 would float those leads to the top of a descending sort, which
   is the opposite of what the sort is for. Nulls go last, and a test pins it.

9. **Follow-up due dates come from one bulk read, not an N+1.** The due date is not a column on
   `Lead`, and `GET /followups?lead_id=` takes a single id — one request per visible card would mean
   dozens per board render. The hook reads the open worklist once (ordered soonest-first, the API's
   own ordering) and indexes it by `lead_id`. Stated plainly: a lead whose only open follow-up falls
   outside the 200 most imminent tasks shows no due date on its card. That is decoration on a card;
   the Lead Details page remains authoritative.

10. **Blank filters are stripped, not sent.** The backend matches `city`/`district` with `ILIKE
    %value%`, so `city=` is a literal empty-string match returning nothing. The service drops empty
    values rather than making every caller remember to.

11. **City and District are free-text, not selects.** The backend matches them partially and exposes
    no endpoint enumerating distinct values — a dropdown would have to be built by scanning a lead
    sample and would silently omit every place not in that sample.

12. **RBAC is per-control and mirrors the endpoints.** `leads:update` gates the "Move…" control (it
    performs the same write a drop does), `followups:create` gates Create Follow-up, `whatsapp:create`
    gates Send WhatsApp. **Open Lead is ungated** beyond the page's own `leads:view` — it navigates
    and touches no API. Note that hiding the Move control does **not** disable native dragging, which
    is a client-side gesture; the server still rejects the write. The guard mirrors the server, it
    does not replace it.

13. **The board scrolls horizontally at every breakpoint.** Nine columns cannot be made legible on a
    phone at any width, and a wrapping grid destroys the left-to-right progression that makes a
    pipeline readable. Columns keep a fixed width (widening slightly on `sm`) and each scrolls
    vertically inside itself.

### Known gaps / follow-ups for a later phase

1. **Native drag is mouse-only.** HTML5 drag-and-drop fires no events for touch, so on a phone or
   tablet the "Move…" select is the only way to change a status from the board. A pointer-events
   based drag implementation (or `@dnd-kit`, which supports touch sensors) would close this. The
   board is fully usable without it — this affects the gesture, not the capability.

2. **No cross-column card ordering is persisted.** Cards are ordered by the chosen sort, not by a
   user-defined rank, because `Lead` has no ordering column. Dropping a card into a specific
   *position* within a column is therefore not meaningful — only the column it lands in matters.

3. **Sorting only orders what has been loaded** (decision §7). An `order_by` parameter on
   `GET /leads` would make it exact and is the single highest-value backend addition for this page.

4. **Follow-up due dates are bounded to 200 open tasks** (decision §9). A `lead_id__in` filter, or
   denormalising the next due date onto `LeadResponse`, would make the badge complete.

5. **No realtime or polling.** The board fetches on mount with a 30s stale window and an explicit
   Refresh button; a lead moved by a colleague is not reflected until one of those happens.

6. **Assignee names still come from an unpaginated `GET /employees`** capped at 200 — the same
   limitation the dashboard and details pages carry. A lead assigned to the 201st employee shows
   "Unassigned".

7. **The production bundle is 1.21 MB (353 KB gzipped)**, up ~24 KB from this phase and still
   un-split. Route-level `React.lazy` remains the fix.

8. **`npm run lint` still cannot run — `eslint` is not installed** in `node_modules` despite the
   script existing in `package.json`. Pre-existing and unrelated to this phase; typechecking is
   covered by `tsc` inside `npm run build`, which passes clean.

## Lead Import — Frontend Phase

**Status:** Complete

**Scope:** The Lead Import screen at `/leads/import` — provider selection (Google Maps, Instagram,
CSV), keyword and result-limit inputs, drag-and-drop CSV upload, live import progress, an outcome
summary, run history with retry, and lifetime statistics. **The backend was not modified**: the
import engine, providers, deduplication, API endpoints and schemas were consumed exactly as they
already existed. No ERP functionality, no database schema, no provider implementation, no
deduplication logic and no WhatsApp code was touched.

### Checklist

- [x] `src/features/leads/types.ts` — `ImportJobDetail`, `ImportJobLogEntry`, `ImportProvider`,
      `ImportProviderList`, `ImportRunPayload`, `ImportStatistics`, `ImportJobListParams` added;
      `ImportJobStatus` corrected to include `CANCELLED` (the backend enum has six members, the
      frontend type declared five).
- [x] `src/services/leads.ts` — `leadImportsService` extended with `runImport`, `importCsv`,
      `listProviders`, `listJobsFiltered`, `getJob`, `getStatistics` and `retryJob`. API calls only,
      on the existing shared Axios instance — no second client was created.
- [x] `src/features/leads/importUtils.ts` — pure helpers: the provider capability catalogue, CSV
      validation, duration/byte/provider formatting, status→Badge mapping, and
      `toFriendlyErrorMessage` (the single place raw backend errors are translated).
- [x] `src/features/leads/importValidation.ts` — Zod schema factory, built per provider so the
      "keyword required" rule follows the registry rather than a hardcoded provider list.
- [x] `src/features/leads/importHooks.ts` — business logic: `useImportProviders`,
      `useImportHistory`, `useImportStatistics`, `useProviderBreakdown`, `useLeadImport`
      (the import mutation, its toasts and its cache invalidation) and `useRetryImport`.
- [x] Components (presentational only): `ProviderSelector`, `CsvDropZone`, `ImportResultSummary`,
      `ImportHistoryTable`, `ImportStatsCards`.
- [x] Page: `src/features/leads/pages/ImportLeadsPage.tsx` — composition and form wiring only.
- [x] Route wired into `src/App.tsx` — the "Coming in the next phase" placeholder replaced, and the
      guard corrected from `leads:create` to `leads:import` (see "Route permission" below).
- [x] Reused `Button`, `Card`, `Input`, `NumberInput`, `ProgressBar`, `StatCard`, `Spinner`,
      `Badge`, `EmptyState`, `ErrorState`, `Skeleton`, `FilePreview` and the existing
      `ToastProvider`/`useNotificationStore`. No new design-system component was added.
- [x] `src/tests/importLeads.test.tsx` — 61 tests covering all twelve required areas.
- [x] `npm run test` — 400/400 passing (13 files, including the new suite).
- [x] `npm run build` — `tsc` + `vite build` succeed with zero TypeScript errors.

### Route permission (one-line frontend fix, no backend change)

The placeholder route was guarded on `leads:create`, but every import endpoint in
`app/api/v1/endpoints/lead_imports.py` enforces **`leads:import`** — a deliberately separate
permission, because bulk-importing hundreds of leads has a different blast radius from adding one by
hand. Left as it was, a user holding `leads:create` but not `leads:import` would have reached the
page and had every request rejected with a 403. The route now matches the API. `leads:import` is
already seeded in `scripts/seed_roles.py:86`, so no backend or seed change was needed.

### Design decisions

1. **No `FileUpload` component was created.** The brief named one, but `src/components/ui/` has no
   such primitive. Rather than add a global component for a single call site, `CsvDropZone` composes
   the primitives that do exist (`FilePreview`, `ProgressBar`). If a second screen ever needs file
   upload, that component is the one to promote into `components/ui/`.
2. **The provider list comes from the API, not a constant.** `is_available` is a deployment fact —
   whether an API key is configured — so a hardcoded list would show Instagram as ready on a server
   that cannot run it. Only the marketing copy (the ✔ bullets) is local, keyed by provider, and
   merged onto whatever the registry returns; an unrecognised provider still renders.
3. **The provider key is not a form field.** It lives in the selector's state and is passed at
   submit. An earlier revision mirrored it into the form via `setValue`, which produced two sources
   of truth and a submit that silently failed validation on an empty `provider`.
4. **No polling.** The backend runs collection synchronously and returns the finished job, so the
   response *is* the result. Progress is therefore a real determinate bar during CSV upload and an
   indeterminate one during server-side collection, rather than a fake percentage.
5. **A successful import invalidates `leadKeys.all`, not just the import keys.** New leads exist, so
   every lead list, count and chart is stale. One broad invalidation cannot miss a widget, and
   TanStack Query only refetches what is mounted.
6. **Raw 5xx bodies are never shown.** `toFriendlyErrorMessage` surfaces backend text only for the
   statuses whose bodies are written for humans (400/404/409/422, which come from our own
   `AppException`s); 5xx is replaced wholesale, since it may carry a stack trace.

### Known gaps / follow-ups

1. **The provider breakdown is derived from the loaded history page**, not a dedicated endpoint —
   the statistics endpoint aggregates by status, and nothing aggregates by provider. The card says
   so when more runs exist than were read.
2. **Import history is a single page of 10** with a Refresh button; no pagination controls yet.
3. **Per-record import logs are not surfaced.** `GET /leads/imports/{id}` returns them and
   `getJob`/`ImportJobLogEntry` are in place, but no drill-in view consumes them yet.
4. **`npm run lint` still cannot run** — `eslint` is not installed and is not even a declared
   devDependency. Pre-existing; `tsc` inside `npm run build` passes clean.

---

## OpenStreetMap / Overpass Lead Provider (free replacement for Google Maps)

**Phase goal.** Replace the **paid** Google Maps provider with a **free** one: collect
photography businesses from OpenStreetMap via the public Overpass API, behind the existing
`LeadProvider` interface, so a search costs nothing and requires no API key.

Scope note: this phase touched **only** the collection path. The **CRM and `Lead` models were
not modified** — no column, no enum member, and therefore **no Alembic migration**. WhatsApp,
Lead Management, Orders, Inventory, Payments, Production, Delivery, Dashboard and
Authentication were not modified, and no endpoint was added — `POST /api/v1/leads/import` is
reused exactly as it stands.

### Checklist

- [x] `OverpassLeadProvider` in `app/services/lead_providers/overpass.py`, reusing the
      existing `LeadProvider` interface — `search(query)` / `collect()` / `normalize()`.
- [x] Built on the **public Overpass API**, with no credential of any kind.
- [x] Accepts **city**, **category** and **radius_km** (the last two via
      `ProviderContext.options`, which is exactly what that free-form field exists for — a
      parameter no other adapter has, added without widening the shared dataclass).
- [x] **City → latitude/longitude via Nominatim**, one geocode per run, biased to India
      (`countrycodes=in`) and narrowed by `state` when supplied.
- [x] Overpass QL generated for photography tags: `shop=photo`, `office=photographer`,
      `studio=photography` as specified, **plus** `craft=photographer` and `shop=photo_studio`
      — `craft=photographer` outnumbers `office=photographer` in OSM's real data, and omitting
      it halves the yield.
- [x] All three element types queried (`node` / `way` / `relation`), with `out center` so ways
      and relations come back with a usable coordinate.
- [x] Query executed and **every** returned element parsed.
- [x] Extracts, whenever available: business name, address, phone, email, website, coordinates
      — plus city / district / state / country / pincode / categories / OSM permalink.
- [x] Normalized into the existing `NormalizedLead` model, unchanged.
- [x] **Nothing is saved to the database.** The module imports no model, no repository and no
      session; `collect_normalized()` returns `NormalizedLead` objects and nothing else. This
      is asserted structurally in the test suite via `inspect.getsource`.
- [x] **Overpass rate limits respected** — outbound calls serialised behind a lock and spaced
      by `OVERPASS_MIN_REQUEST_INTERVAL_SECONDS`, a required `User-Agent`, a bounded radius,
      and a server-side `[timeout:N]` held below the client timeout.
- [x] **Retry with exponential backoff** — `base * 2**attempt`, capped; `Retry-After` honoured
      over the computed delay (and itself capped); `429`/`504`/`5xx`/transport faults retried;
      `400`/`403` deliberately **not** retried.
- [x] Unit suite `tests/test_overpass_import.py` — 10 sections, entirely mocked Overpass and
      Nominatim responses, **no database and no network**.
- [x] Registered under the new key `overpass`, **alongside** `google_maps` rather than over it.
- [x] `walkthrough.md` and `task.md` updated.

### Files

| File | Change |
|---|---|
| `app/services/lead_providers/overpass.py` | **New** — the provider. |
| `tests/test_overpass_import.py` | **New** — 10-section unit suite. |
| `app/core/config.py` | New `OVERPASS_*` / `NOMINATIM_*` settings block; nothing existing altered. |
| `app/services/lead_providers/__init__.py` | One import line + one `__all__` entry. |
| `tests/test_lead_import.py` | Registry assertion now expects 9 providers, not 8. |

`google_maps.py`, `base.py`, `normalized.py`, `planned.py`, `lead_import.py`, all models and
all endpoints are byte-for-byte unchanged.

### Design decisions

1. **Two calls per import, not N+1 — the cost model evaporates.** Google needed a Text Search
   plus one *billed* Place Details call per business, which drove three separate mitigations
   (limit applied before the fan-out, bounded concurrency, a switch to disable details).
   Overpass returns everything in one query, so none of that machinery exists here. What
   replaces it is politeness, because the public endpoints are donated capacity governed by a
   usage policy — the failure mode is being blocked, not an invoice.
2. **The rate limiter holds its lock across the whole request, not just the sleep.** The usage
   policy asks for roughly one query at a time from a client, so the correct model is a queue,
   not a token bucket. Holding the lock for the request duration is what makes two *concurrent*
   imports through one provider instance queue instead of doubling the observed load; a bare
   `asyncio.sleep` between calls would not achieve that, and the test measures it.
3. **`400`/`403` are not retried.** Only `{429, 500, 502, 503, 504}` and transport faults are.
   A malformed query or a block is a final answer, and retrying it adds load to an endpoint
   that has already said no — which is itself the behaviour that earns a block.
4. **`Retry-After` beats the computed backoff, but is still capped.** The server knows when it
   will be ready; ignoring an explicit instruction is the fastest way to lose access. The cap
   stops a mistaken or hostile header from parking an import for hours.
5. **`city` is mandatory here though it was optional for Google.** Overpass is queried by
   coordinates, and the city is what gets geocoded — with none there is no query to build.
   `search()` refuses at request time, before the job is marked RUNNING.
6. **`category` does not narrow the Overpass query.** OSM has no free-text index to narrow
   *with*; the tag filters are the only selectivity the API offers. The category is recorded
   and surfaces as a lead category tag. Filtering names client-side would drop correctly
   tagged studios whose names simply lack the operator's word.
7. **City falls back to the searched city when the element has no `addr:city`.** Unsound for a
   general geocoder, sound here: every element is by construction within `radius_km` of that
   city's centre. Without a city, `normalize_business_key` cannot produce a key at all, so the
   same studio re-collected next month would import twice.
8. **`lead_source = "GOOGLE_MAPS"`.** `LeadSource` is an enum on `app/models/lead.py`, which
   this phase was told not to modify; adding `OPENSTREETMAP` would mean a model edit plus an
   `ALTER TYPE` migration. Overpass leads are map-listing leads, so reusing the member keeps
   every existing dashboard, filter and dedup rule working and keeps this a pure provider-layer
   addition. See the follow-up below.
9. **Registered alongside `google_maps`, not over it.** Both are selectable at request time, so
   the two can be compared on the same city before the paid one is retired — and retiring it
   later is deleting one import line. A hard cutover on a provider with materially different
   coverage would be a one-way door.
10. **Backoff delays are recorded, not spent, in tests.** `asyncio.sleep` is swapped for a
    recorder, so the suite asserts the computed policy in milliseconds. A retry suite that
    really slept would take half a minute and would be the first thing a developer skips.

### Verification

```
python tests/test_overpass_import.py       # ALL 10 SECTIONS PASSED
python tests/test_lead_import.py           # unchanged, still passing (9 providers)
```

The Overpass suite touches **no database and no network** — it needs no `.env`, no Postgres and
no credential, and is safe to run anywhere.

### Known gaps / follow-ups

1. **Expect a higher failed-record rate than Google Maps.** OSM's photography coverage in India
   is thinner, and many OSM elements carry a name and a location but **no phone**, which
   `NormalizedLead.is_valid()` rejects. Each such record is counted and logged with its reason,
   so the job log stays honest — but size `limit` expectations accordingly. This is the trade
   for a free provider, not a defect in the adapter.
2. **`LeadSource.OPENSTREETMAP` is not added.** Overpass leads are attributed `GOOGLE_MAPS`
   (decision 8). Whenever a `Lead` model change is in scope, adding the member plus an enum
   migration and flipping one class attribute would make attribution literal; nothing else
   would need to change.
3. **No email/website enrichment beyond the tags.** OSM's `email` and `contact:email` are read
   directly — a genuine gain over Google Places, which returns no email at any price — but a
   business that publishes an address only on its own site stays without one. Crawling the
   website would be a different integration with different consent implications.
4. **The frontend provider selector has no marketing copy for `overpass`.** The Lead Import
   screen reads the provider list from the API, so `overpass` appears and is selectable
   automatically — but its ✔ bullets are keyed by provider locally and will be absent, and the
   screen has **no input for `radius_km`**, so imports run at the configured default until a
   field is added.
5. **A single Nominatim result is trusted.** `limit=1` with an India bias; an ambiguous city
   name shared by two Indian towns resolves to whichever Nominatim ranks first. Supplying
   `state` disambiguates. Surfacing the resolved `display_name` back to the operator for
   confirmation would close this properly.
6. **The public endpoint is the default.** For sustained or heavy use the Overpass usage policy
   recommends a dedicated instance; `OVERPASS_BASE_URL` is configurable for exactly that, and
   `OVERPASS_USER_AGENT` should be set to a real contact address in production.

---

## Website Discovery — Lead Enrichment (`WebsiteDiscoveryService`)

**Phase goal.** Extend the lead discovery pipeline with an enrichment step: for every
normalized lead that arrived **without** a website, search the public web on business name +
city, discover the official site, validate it belongs to the same business, ignore directory
sites, and return the enriched `NormalizedLead`.

Scope note: this phase is **additive and read-only**. Nothing is written to the database —
the new module imports no model, no repository and no session. The `Lead` model, `LeadSource`,
every provider, `LeadImportService` and every endpoint are **unchanged**, and **no Alembic
migration** was generated because nothing schema-shaped changed. The service is not yet wired
into the import path; that is a deliberate follow-up (see below).

### Checklist

- [x] **Separate `WebsiteDiscoveryService`** in `app/services/website_discovery.py` — a
      service, not a `LeadProvider`. A provider answers "what businesses exist"; this answers
      "given a business, what is its website". Folding it into an adapter would mean
      re-implementing it in every adapter that returns websiteless records (Overpass and
      Instagram both do).
- [x] **Rule 1 — search the public web on business name + city.** `_build_query` joins the
      two; city is what disambiguates the many studios sharing a common name across India,
      the same reason `normalize_business_key` includes it.
- [x] **Rule 2 — discover the official website**, via a pluggable `SearchBackend` port with a
      zero-credential `DuckDuckGoSearchBackend` default.
- [x] **Rule 3 — validate it belongs to the same business.** `_score_candidate` requires
      token overlap between the business name and the domain, corroborated by the result
      title and city. Below `WEBSITE_DISCOVERY_MIN_CONFIDENCE` the lead is returned unchanged.
- [x] **Rule 4 — directory websites ignored.** ~90 domains (Justdial, Sulekha, IndiaMART,
      WeddingWire, WedMeGood, Facebook, Instagram, Google Maps, linktr.ee, …), matched on the
      domain *and any subdomain of it*, rejected **before** scoring so rank cannot rescue one.
- [x] **Rule 5 — only the official domain is saved.** The deep URL that happened to rank is
      reduced to its registrable domain; path, query string, fragment and `www.` are dropped.
- [x] **Rule 6 — existing websites are never overwritten.** Checked first, before any work,
      so a lead that already has one issues **no outbound search at all**.
- [x] **Rule 7 — returns the enriched `NormalizedLead`.** A new instance; the input is never
      mutated and every other field survives the round trip.
- [x] **No database writes.** Asserted structurally in the suite via `inspect.getsource`, and
      by `discover()`'s signature carrying no session parameter.
- [x] Rate-limited and politeness-headed, on the same reasoning as the Overpass adapter — the
      default backend is an unmetered public endpoint, so the failure mode is being blocked.
- [x] Unit suite `tests/test_website_discovery.py` — **no database, no network**. (Extended to 15 sections by the follow-up phase below.)
- [x] `walkthrough.md` and `task.md` updated.

### Files

| File | Change |
|---|---|
| `app/services/website_discovery.py` | **New** — the service, the directory list and the scorer. (The `SearchBackend` port and the DuckDuckGo backend were later extracted into `app/services/lead_providers/web_search/` — see the follow-up phase below.) |
| `tests/test_website_discovery.py` | **New** — unit suite (later extended to 15 sections). |
| `app/core/config.py` | New `WEBSITE_DISCOVERY_*` settings block; nothing existing altered. (The search-transport half was later renamed to `WEB_SEARCH_*`.) |

Every provider, `base.py`, `normalized.py`, `lead_import.py`, all models, all schemas and all
endpoints are byte-for-byte unchanged.

### Design decisions

1. **A service, not a provider.** The `LeadProvider` contract is `search → collect →
   normalize` over a *query*; discovery is a function of an *existing lead*. Keeping it
   separate means it composes with every provider at once — Overpass and Instagram both emit
   websiteless leads — and is testable on a hand-built `NormalizedLead` with no provider,
   no context and no network.
2. **The search backend is a port, defaulting to a keyless engine.** "Search the public web"
   has no single correct implementation: an operator with a Google CSE or Brave key wants
   that, an operator with neither still wants the feature to work. `SearchBackend` is a
   one-method ABC; `DuckDuckGoSearchBackend` is the credential-free default, for exactly the
   reason `OverpassLeadProvider` was added alongside the billed Google adapter. Adding a keyed
   engine is a new class plus one registry entry — this service does not change.
3. **Validation is the hard part; search is not.** A search for "Sunrise Studio Kozhikode"
   always returns *something*. The risk is not finding nothing, it is confidently attaching
   the wrong domain — which is worse than an empty field, because an empty field visibly
   reads as a gap while a wrong one looks like data. Hence two defences in order: reject
   directories outright, then require what survives to *earn* its place.
4. **Directory rejection precedes scoring, not follows it.** Justdial and WeddingWire rank
   *above* a small studio's own site for precisely the query this service issues, so a
   "take the first result" implementation would attach a directory to the majority of leads.
   Rejecting before scoring is what guarantees rank can never rescue one. Subdomains are
   matched too, because directories serve city pages from them (`kozhikode.justdial.com`).
5. **Generic photography vocabulary carries no identity.** "photography", "studio", "wedding",
   "films" and ~50 others are stripped before matching: "Sunrise Photography" and "Lakeside
   Photography" are unrelated businesses, and matching on the shared word would validate
   either one's domain against the other's name. When *every* token is generic ("The Photo
   Studio") the full list is used as a fallback and the confidence threshold decides.
6. **Declining to guess is a supported outcome, not a failure.** `below_threshold` is a
   first-class status carrying the best candidate's score and reasoning, so an operator can
   see the service considered a domain and rejected it. This is the behaviour the asymmetry
   in decision 3 demands.
7. **The domain is stored, not the ranking URL.** A lead's website is the business's site,
   not the one page a search engine chose to surface. `sunrisestudio.in/gallery?ref=ddg#top`
   becomes `https://sunrisestudio.in`, and several pages of one site collapse to one candidate.
8. **Every decision is explainable after the fact.** `discover_with_outcome()` returns a
   `DiscoveryOutcome` carrying the status, confidence, the evidence that produced it, and the
   directories rejected. `discover()` stays a plain lead-in/lead-out function for the common
   case — the same split `LeadProvider` makes between `collect()` and `collect_normalized()`.
9. **Nothing raises.** A network fault, a challenge page, a backend bug and a lead with no
   website all resolve to "returned unchanged". This is enrichment: an import of two hundred
   leads must never fail because one of them could not be resolved. Section 10 of the suite
   asserts it, including for a backend that violates the contract and raises `RuntimeError`.
10. **The SERP parse degrades to nothing, never to garbage.** The DuckDuckGo HTML endpoint is
    not a documented API, so the parse is anchored on the stable `result__a` / `result__snippet`
    class names and skips anything unrecognised. A SERP redesign costs recall; it cannot
    produce wrong URLs. Regex rather than an HTML parser because none is a dependency of this
    project and adding one for a single defensive extraction is not worth the supply-chain surface.
11. **Rate limited like Overpass, for the same reason.** The default backend is donated public
    capacity, so calls are serialised behind a lock held *across the request* (not merely
    across the sleep), spaced by a configured interval, and sent with an identifying
    User-Agent. The failure mode for bursting is a block, not an invoice.
12. **Not yet wired into `LeadImportService`.** The brief asked for the service and no
    database writes; wiring it into the import path is a behavioural change to every import
    run and a separate decision. See the follow-up below.

### Verification

```
python tests/test_website_discovery.py    # ALL 15 SECTIONS PASSED (after the follow-up phase)
python tests/test_overpass_import.py      # unchanged, still passing
python -c "from app.main import app"      # app imports cleanly with the new settings
```

The suite touches **no database and no network** — it needs no `.env`, no Postgres and no
credential, and is safe to run anywhere.

### Known gaps / follow-ups for a later phase

1. **Not wired into the import pipeline (decision 12).** `LeadImportService._process_records`
   does not call it yet, so no import run is enriched today. Wiring it is roughly: construct
   the service, `await service.discover_many(records)` between `collect_normalized()` and
   `_process_records()`, and log each `DiscoveryOutcome.detail` into the job's log array.
   That should land with an operator-facing switch (`enrich_websites: bool` on the import
   request), because it adds one outbound search per websiteless lead to every run.
2. **`registrable_domain` is not a public-suffix-list implementation.** It strips `www.` and
   lowercases; it does not consult the PSL. Sufficient for comparison and directory matching,
   and it has no stale-dataset failure mode — but a domain under an unusual multi-part suffix
   is tokenized slightly imprecisely, which can only cost a little confidence, never
   misattribute.
3. **The directory list is static and India-weighted.** ~90 domains chosen for this CRM's
   market. A new aggregator, or a regional one outside India, is not rejected until it is
   added. Promoting the list to a config value or a small table would let an operator extend
   it without a deploy.
4. **The candidate's site is never fetched.** Validation uses the domain, the SERP title and
   the snippet only. Fetching the homepage and checking it for the lead's phone number would
   be materially stronger evidence — it is the single highest-value improvement available here
   — but it is a second outbound request per lead and a different consent posture, so it was
   left out of a phase specified as "search, validate, return".
5. **DuckDuckGo may serve a challenge page under load.** The parse degrades to zero results
   (decision 10) and the lead is returned unchanged, so the failure is safe but silent-ish —
   it surfaces as `no_candidates`, indistinguishable from a business that genuinely has no
   site. An operator seeing a run where *every* lead reports `no_candidates` should suspect
   the backend, and a keyed backend is the fix.
6. **No confidence is persisted.** `DiscoveryOutcome.confidence` and its reasoning exist only
   for the duration of the call; once wired in, only the URL would reach the `Lead` row. If
   operators need to review borderline attributions, the score belongs in the job log at
   minimum, and arguably on the lead itself.

---

## Web Search Abstraction — Website Discovery, Phase 2 (`web_search/`)

**Phase goal.** Promote the search backend from a section inside `website_discovery.py` to a
**pluggable package of its own**, and close the four operational gaps the first phase left:
live URL validation, retries with exponential backoff, robots.txt compliance, and a bounded
redirect budget.

Scope note: this phase is **additive and still read-only**. No model, no schema, no endpoint
and no UI changed, and the Alembic autogenerate check produced an **empty** migration
(`upgrade()`/`downgrade()` both `pass`), confirming **no migration is required**. The
Overpass provider, the Import Leads UI and the Lead model are byte-for-byte unchanged, and
the Google Maps provider is not involved.

### Checklist

- [x] **`app/services/lead_providers/web_search/base.py`** — the port: `SearchResult`
      (`title`, `url`, `snippet` — nothing more), the `SearchBackend` ABC, `SearchBackendError`,
      and a `@register_search_backend` registry with `get_search_backend()`.
- [x] **`app/services/lead_providers/web_search/duckduckgo.py`** — the default backend. All
      HTML parsing, the redirect-wrapper unwrapping, the rate limiter, the retry schedule and
      robots.txt handling are **isolated here**, per the brief.
- [x] **`WEB_SEARCH_BACKEND=duckduckgo`** configurable setting, plus the transport knobs
      (`WEB_SEARCH_TIMEOUT_SECONDS`, `WEB_SEARCH_MAX_ATTEMPTS`,
      `WEB_SEARCH_RETRY_BACKOFF_SECONDS`, `WEB_SEARCH_MAX_REDIRECTS`,
      `WEB_SEARCH_RESPECT_ROBOTS`, …). **No credential setting exists**, and the suite asserts
      that no `WEB_SEARCH_*_KEY|TOKEN|SECRET` can be added unnoticed.
- [x] **No lead or database logic in the search provider.** The backend imports no model, no
      repository, no session and not even `NormalizedLead`; asserted on the source in the suite.
- [x] **Rule 4, completed — the discovered URL is now validated for real.** `_validate_website`
      shape-checks the scheme and host, then confirms something answers: `HEAD` first, falling
      back to `GET` on 405/501, under a short dedicated timeout and a **bounded** redirect
      budget. A failure yields `validation_failed` and leaves the website **empty**.
- [x] **A failed lookup never fails the lead.** Search faults, validation faults, exhausted
      retries and backend bugs all resolve to "lead returned unchanged".
- [x] **Retries with exponential backoff and jitter** — only for 429/5xx and transport faults.
      A 403 is *not* retried, because retrying a block hastens it.
- [x] **robots.txt fetched and honoured**, cached per process; an *unreachable* robots.txt is
      treated as allowed rather than as a ban.
- [x] Suite extended to **15 sections**, still **no database and no network** — every HTTP
      call, including robots.txt, is served by `httpx.MockTransport`.
- [x] Alembic autogenerate check run: **empty migration → none required**.
- [x] `walkthrough.md` and `task.md` updated.

### Files

| File | Change |
|---|---|
| `app/services/lead_providers/web_search/__init__.py` | **New** — package entry point; imports backends for their registration side effect. |
| `app/services/lead_providers/web_search/base.py` | **New** — `SearchResult`, `SearchBackend`, `SearchBackendError`, the registry, `get_search_backend()`. |
| `app/services/lead_providers/web_search/duckduckgo.py` | **New** — the default backend: HTML parse, rate limiter, retries/backoff, robots.txt, bounded redirects. |
| `app/services/website_discovery.py` | **Modified** — backend code removed (now imported from the package and re-exported for compatibility); `_validate_website` added; new `validation_failed` status. |
| `app/core/config.py` | **Modified** — `WEBSITE_DISCOVERY_*` search-transport settings renamed to `WEB_SEARCH_*` and extended; two validation knobs added. |
| `tests/test_website_discovery.py` | **Modified** — 10 → 15 sections; new coverage for validation, retries/backoff, robots/redirects, no-credentials and duplicate results. |

`app/models/`, `app/schemas/`, `app/repositories/`, every endpoint, `overpass.py`, the Import
Leads UI and every Alembic version are **unchanged**.

### Design decisions

1. **The package boundary is enforced in both directions.** `web_search/` knows nothing about
   leads; `website_discovery.py` knows nothing about HTML SERPs. The seam is `SearchResult` —
   three strings. This is what makes a future Google CSE or Brave backend a new file rather
   than an edit to the service, and it is asserted in section 14, which greps the backend
   source for `NormalizedLead`, `AsyncSession`, `app.models` and `app.repositories`.
2. **Registration is a decorator, not a dict entry.** `@register_search_backend` puts the
   declaration and the wiring on the same line in the same file, so a backend cannot be
   written and then silently left unreachable — the same pattern `lead_providers/base.py`
   already uses for providers.
3. **An unknown backend key degrades rather than raises** — the opposite of `get_provider`,
   deliberately. A wrong *provider* key means an operator asked for data we cannot supply and
   must be told. A wrong *search* key would only mean one enrichment step used a different
   engine; since discovery writes nothing and weak results are discarded by the threshold
   anyway, falling back to the free default beats failing an import run.
4. **Validation is a reachability check, not a content check.** It answers "does something
   answer here", not "is this the right business" — that is the scorer's job, and conflating
   the two would let a reachable wrong domain pass on the strength of returning HTTP 200.
   `HEAD` first because it is far cheaper; `GET` on 405/501 because enough small hosts reject
   `HEAD` that treating it as failure would discard working sites.
5. **Only retryable faults are retried.** 429 and 5xx are transient; a 403 is a decision about
   *this client* and retrying it only arrives at a block faster. Backoff is
   `base * 2**(attempt-1)` with **full jitter**, because several concurrent imports that all
   failed on one upstream blip would otherwise retry in lockstep and reproduce the burst.
6. **An unreachable robots.txt means "allowed", not "forbidden".** A file we could not fetch
   is not a directive to stay away; treating it as one would disable discovery entirely on any
   transient network fault. An explicit `Disallow` *is* honoured, and the verdict is cached for
   the process lifetime — re-fetching it per search would itself be the traffic robots.txt
   exists to limit.
7. **Redirects are bounded everywhere.** Both the search request and the validation request
   carry `max_redirects=WEB_SEARCH_MAX_REDIRECTS`. Unlimited following turns a parked-domain
   redirect loop into a request that consumes the whole timeout budget.
8. **Old import paths still work.** `SearchResult`, `SearchBackend`, `SearchBackendError` and
   `get_search_backend` are re-exported from `website_discovery`, so the move is not a
   breaking change for anything that imported them — they are aliases, not a second copy.
9. **The settings split mirrors the code split.** `WEB_SEARCH_*` configures the swappable
   transport; `WEBSITE_DISCOVERY_*` configures the scoring and validation that are *not*
   swappable. Which knob belongs to which layer is readable from its name.

### Verification

```
python tests/test_website_discovery.py    # ALL 15 SECTIONS PASSED
python tests/test_lead_discovery.py       # ALL 8 SECTIONS PASSED
python tests/test_contact_extractor.py    # ALL 17 SECTIONS PASSED
python tests/test_overpass_import.py      # ALL 10 SECTIONS PASSED (provider untouched)
npm run test                              # 452 passed (13 files)
npm run build                             # tsc + vite build clean
alembic revision --autogenerate           # empty upgrade()/downgrade() → no migration needed
```

### Known gaps / follow-ups for a later phase

1. **Still not wired into `LeadImportService`.** Unchanged from the previous phase:
   `LeadDiscoveryService` calls it, but the plain import path does not. Wiring it needs an
   operator-facing switch, since it adds an outbound search per websiteless lead.
2. **robots.txt matching is minimal, not RFC 9309.** It evaluates the `User-agent: *` group
   only, with simple prefix matching and no full `Allow`-precedence rules. It errs toward not
   fetching when a rule matches. `urllib.robotparser` is stdlib but synchronous and would
   block the event loop on its own fetch, so only the matching is reimplemented.
3. **Validation confirms reachability, not ownership.** A domain that scores well and returns
   HTTP 200 is accepted; the page body is never inspected. Fetching the homepage and matching
   the lead's phone number remains the highest-value improvement available — and is now much
   cheaper to add, since the validation request already exists.
4. **Only one backend ships.** The registry, the port and the config are all in place for a
   keyed engine, but `duckduckgo` is the only registered key today. Adding Google CSE or Brave
   is a new module plus a `WEB_SEARCH_BACKEND` value, with no change to the service.
5. **Contact extraction is deliberately out of scope**, per the brief — this phase discovers
   the official website only. `ContactExtractorService` is the separate phase that consumes it.

---

## Contact Extraction — Lead Enrichment (`ContactExtractorService`)

**Phase goal.** Extend the lead enrichment pipeline with the step that follows website
discovery: for a normalized lead that **has** a website, visit it, read the header, footer,
contact page and about page, extract phone numbers, WhatsApp numbers, email addresses,
Instagram/Facebook/YouTube links, normalize them all, and return the enriched
`NormalizedLead`.

This is the improvement `walkthrough.md` named as the highest-value one available after
discovery: a studio's own site is the most authoritative contact source there is, and far
better evidence than a directory listing.

Scope note: this phase is **additive and read-only with respect to the database**. The new
module imports no model, no repository and no session. The `Lead` model, every endpoint and
the CRM schema are **unchanged**, and `alembic revision --autogenerate` produces an **empty
migration** (verified, then deleted) because nothing schema-shaped changed.

`NormalizedLead` — the in-memory DTO, *not* a database table — gained two optional fields,
`whatsapp_numbers: list[str]` and `youtube: str | None`, both defaulted so every existing
provider and caller is unaffected. This is the "smallest backwards-compatible extension" the
brief asks for: WhatsApp numbers have to be storable *separately* from ordinary phones, and
carrying them in `raw` (as the first cut did) meant the one place that needs them —
`secondary_phone`, which fills the CRM's `whatsapp` column — could not see them.

### Checklist

- [x] **Separate `ContactExtractorService`** in `app/services/contact_extractor.py` — a
      service, not a `LeadProvider`, the same shape as `WebsiteDiscoveryService`. Discovery
      answers "what is this business's website"; this answers "given the website, how do I
      contact them". They compose in that order.
- [x] **Visits the website** of a `NormalizedLead`. A lead with no website is returned
      untouched, with no request issued at all.
- [x] **Reads header, footer, contact page and about page.** Header and footer are scanned
      **first and separately**, then the whole document — because `NormalizedLead` promotes
      `phone_numbers[0]` to the CRM's `phone` column, and the number a business leads with
      belongs first. Footer/header are matched by tag, ARIA role **and** class/id convention,
      since most small-business templates ship `<div class="site-footer">`, not `<footer>`.
- [x] **Extracts** phone numbers, WhatsApp numbers, email addresses, and Instagram, Facebook
      and YouTube links — from `href` attributes (authoritative) and from page text (fallback).
- [x] **Normalizes every value** through `normalized.py`'s existing helpers, so extraction
      produces exactly what the CRM already stores and deduplicates on.
- [x] **Uses BeautifulSoup**, imported lazily (the `httpx` pattern) so a missing dependency
      degrades enrichment instead of taking the API down at startup. `lxml` is used when
      present, `html.parser` otherwise.
- [x] **Respects `robots.txt`** via `urllib.robotparser`, fetched **once per host** and cached
      — including across concurrent leads on that host. A `Disallow` is final: zero page
      requests, lead untouched.
- [x] **Crawl depth is one level, structurally.** One fetch for the home page, one fetch per
      selected contact/about link, and links found on *those* pages are never followed. There
      is no recursion, no work queue, and no depth parameter that could be raised.
- [x] **The whole site is not crawled.** Off-host links are never followed, ordinary internal
      links (`/gallery`, `/pricing`) are never fetched, and the second level is capped by
      `CONTACT_EXTRACTION_MAX_SUBPAGES`.
- [x] **No database writes.** Asserted structurally in the suite via `inspect.getsource`, and
      by `extract()`'s signature carrying no session parameter.
- [x] **Never overwrites.** `instagram`/`facebook` are filled only when empty; scraped phones
      and emails are *appended* behind the provider's, deduplicated on the CRM's comparison
      keys. The input lead is never mutated.
- [x] Per-host rate limiting and an identifying User-Agent, on the same reasoning as the
      Overpass and discovery adapters.
- [x] **Phone parsing via `phonenumbers`** (libphonenumber). Every Indian form the brief lists
      — `9876543210`, `+91 9876543210`, `+919876543210`, `0091 9876543210`, `080 12345678` —
      parses, validates and normalises to **E.164**. Validity is checked against the real
      numbering plan, so an order number or a GST identifier is rejected however many digits
      it carries. Imported lazily: without the package, extraction falls back to the
      structural heuristics rather than failing.
- [x] **WhatsApp is stored separately** in `NormalizedLead.whatsapp_numbers`, populated only
      from click-to-chat links (`wa.me`, `api.whatsapp.com/send`) — the one place a number is
      *known* to be WhatsApp-reachable. No number is assumed to be on WhatsApp.
      `secondary_phone` now promotes a known WhatsApp number into the CRM's `whatsapp` column
      in preference to guessing at `phone_numbers[1]`.
- [x] **Bounded transfer.** The body is **streamed** and abandoned the moment it passes
      `CONTACT_EXTRACTION_MAX_PAGE_BYTES` (an oversized `Content-Length` is refused before any
      body is read); redirects are capped by `CONTACT_EXTRACTION_MAX_REDIRECTS`, so a redirect
      loop fails fast instead of running unbounded.
- [x] **Ownership/relevance signal.** `_score_relevance` compares the fetched pages against the
      lead's business name, city, known phone and email domain, returning a score in `[0,1]`, a
      band (`owned`/`uncertain`/`unrelated`) and the individual signals. **Advisory only** — a
      low score never discards the website or the extracted contacts; `LeadDiscoveryService`
      decides.
- [x] **Result statuses** distinguish `extracted`, `partial`, `no_contact_found`,
      `fetch_failed`, `robots_blocked`, `invalid_content`, `no_website`. "Found nothing" is a
      **success** (`succeeded` is True), not a system error.
- [x] Unit suite `tests/test_contact_extractor.py` — **17 sections**, no database, no network.
- [x] `walkthrough.md` and `task.md` updated.

### Files

| File | Change |
|---|---|
| `app/services/contact_extractor.py` | **New** — the service, the robots cache, the region/link selection, the extractors and the normalisers. |
| `tests/test_contact_extractor.py` | **New** — 17-section unit suite. |
| `app/core/config.py` | `CONTACT_EXTRACTION_*` settings block, plus `MAX_REDIRECTS`, `PHONE_REGION`, `MIN_RELEVANCE` and the brief's `WEBSITE_*` aliases. |
| `app/services/lead_providers/normalized.py` | Two optional DTO fields (`whatsapp_numbers`, `youtube`); `secondary_phone` prefers a known WhatsApp number. |
| `app/services/contact_normalization.py` | Canonicalises `whatsapp_numbers` by the same rules as ordinary phones. |
| `app/services/lead_discovery.py` | The extraction stage records per-status and per-relevance counts in `StageStats.detail`. |
| `requirements.txt` | Added `beautifulsoup4==4.12.3` and `phonenumbers==9.0.36`. |

Every provider, `base.py`, `lead_import.py`, `website_discovery.py`, all models, all schemas
and all endpoints are unchanged. The `Lead` table and the CRM schema are untouched.

### Design decisions

1. **A service, not a provider** — for the same reason discovery is one. The input is a
   `NormalizedLead`, not a query, and it composes with every provider at once.
2. **Depth is enforced by shape, not by a counter.** A `max_depth=1` parameter is one edit
   away from `max_depth=3`. Instead there is exactly one home-page fetch and one round of
   sub-page fetches, with no recursion and no queue — the module cannot become a crawler
   without being restructured. The suite asserts this on the *actual request log*, not on the
   return value, and separately greps the source for a work queue.
3. **A page is fetched because it is a contact page, not because it exists.** A link
   qualifies only if its text or path says contact/about, and it must be on the same host.
   Fetching every internal link is precisely the crawl the brief forbids.
4. **`robots.txt` absent means allowed; `robots.txt` present and denying means denied.** An
   unreachable or 404 robots.txt permits fetching (the documented convention); a file that
   parses and disallows us ends the extraction with zero page requests. Treating a broken
   server as a prohibition would fail closed against sites that never configured anything.
5. **Header and footer are scanned before the document body.** This is an *ordering* decision
   with a real consequence: the first phone number becomes the CRM's `phone`. Source order
   would let a number in a testimonial outrank the studio's own switchboard.
6. **Links are authoritative; text is inference.** A `tel:`/`mailto:` href is a value the site
   *declared*; a digit run in prose is a guess. Declared values lead the ordering, and the
   text pass is defended by `_looks_like_phone` / `_valid_email`.
7. **A wrong phone number is worse than a missing one** — it is the field the CRM deduplicates
   on, so a bogus value can collapse two unrelated businesses onto one lead. Hence years,
   prices, pincodes, placeholder runs, asset filenames (`logo@2x.png`), analytics DSNs and
   platform furniture (`facebook.com/sharer/…`) are all rejected, and `<script>`/`<style>` are
   stripped before any text is read.
8. **WhatsApp is only claimed when the site claims it.** A number is recorded as WhatsApp only
   from a `wa.me` / `api.whatsapp.com/send` link, which carries the number in the URL. A
   number printed in a footer might or might not be on WhatsApp, and guessing would put a
   wrong claim in front of an operator about to message it.
9. **Existing provider data wins.** A Google Places record is better attributed than a regex
   over HTML, so single-valued fields are filled only when empty and list fields are appended
   to — mirroring rule 6 of website discovery.
10. **`whatsapp_numbers` and `youtube` are DTO fields; `raw` keeps the full harvest.** The
    first cut carried both in `raw` to avoid widening a shared contract. That was wrong for
    WhatsApp specifically: the brief requires it stored *separately* from ordinary phones, and
    `secondary_phone` — which fills the CRM's `whatsapp` column — cannot read `raw`. Both are
    now optional, defaulted fields, so no existing provider or caller changes.
    `raw["contact_extraction"]` still records the complete harvest and the page list, so a
    value that lost to an existing field is visible rather than discarded.
11. **Rate limiting is per host, not global.** The politeness obligation is owed to each
    server individually: five pages on one small studio's site should queue; two unrelated
    domains have no reason to.
12. **Nothing raises.** A dead domain, TLS error, timeout, 404, non-HTML body, unparseable
    markup and a robots prohibition all resolve to "returned unchanged".
13. **Phone numbers are normalised to E.164 by libphonenumber, not by regex.** Indian sites
    write one number five different ways; comparing or dialling them requires one canonical
    form. libphonenumber also knows which ranges are *assignable*, which a digit-count
    heuristic cannot — that is what keeps a 10-digit order number out of the phone field.
14. **The ownership score is advice, never a verdict.** A real studio whose site is an
    image-only splash page with its name in a logo scores near zero. Discarding on that would
    lose a good lead, so the score, its band and its individual signals are *reported* and the
    pipeline decides. This is the explicit instruction in the brief.
15. **The size cap is enforced while streaming.** Reading a response fully and truncating
    afterwards means a site advertising a 2 GB page has already been pulled into memory. An
    oversized page is also *refused* rather than parsed as a prefix: half a document yields
    half-parsed markup and phone numbers sliced across the boundary.
16. **Wired into `LeadDiscoveryService`, behind an existing operator switch.** See "Integration"
    below — the `extract_contacts` flag already existed, so nothing about the operator-facing
    workflow changed.

### Verification

```
python tests/test_contact_extractor.py    # ALL 17 SECTIONS PASSED
python tests/test_website_discovery.py    # unchanged, still passing
python -c "from app.main import app"      # app imports cleanly with the new settings
```

The suite touches **no database and no network** — every page and every `robots.txt` is served
by an injected `httpx.MockTransport`, so the real fetch path, the real BeautifulSoup parse and
the real robots handling are what is under test, with only the socket replaced.

### Known gaps / follow-ups for a later phase

1. **The relevance score is recorded but nothing acts on it yet.** Per-run counts land in
   `StageStats.detail` (`relevance_owned` / `_uncertain` / `_unrelated`). A later phase could
   let an operator review or auto-drop `unrelated` sites — deliberately not done here, since
   acting on a heuristic silently is exactly what the brief warns against.
2. **JavaScript-rendered sites yield nothing.** A site whose contact block is injected by
   React at runtime has no contact details in the served markup. This resolves to
   `no_contact_found` — safe, but indistinguishable from a site that publishes no contacts. A
   headless-browser backend would fix it at a large cost in dependencies and runtime.
3. **Obfuscated emails are not decoded.** Addresses written as `name [at] domain [dot] com`,
   or assembled in JavaScript, are missed. Decoding the common textual patterns is cheap and
   worth doing; decoding the JavaScript ones is not.
4. **Contact pages behind a form are not submitted**, and never should be — the service reads
   published pages only. A business exposing its number solely through a contact form is not
   reachable by this route.
5. **`raw["contact_extraction"]` is a Python dict, not a schema.** Once the service is wired
   in and an endpoint surfaces it, that block should get a Pydantic projection like
   `NormalizedLeadPreview`, rather than being consumed as a free-form dict.
6. **The `_SOCIAL_NOISE_SEGMENTS` and hint lists are static.** A new platform URL shape, or a
   site using an unusual word for its contact page ("say hello"), is missed until added.

### Integration — is it wired in?

**Yes, and no operator-facing workflow changed.** `LeadDiscoveryService` already had an
enrichment stage for this, and `DiscoveryRunRequest` already carried an `extract_contacts`
boolean (alongside `discover_websites`). The stage now calls `extract_many_with_outcomes`
instead of `extract_many` so the per-lead statuses and ownership scores reach the run summary
as `StageStats.detail`, e.g.:

```json
{"stage": "contact_extraction", "records_in": 25, "records_enriched": 14,
 "detail": {"extracted": 12, "partial": 2, "no_contact_found": 8, "fetch_failed": 2,
            "robots_blocked": 1, "relevance_owned": 11, "relevance_unrelated": 3}}
```

`detail` is **additive** — consumers reading only `stage`/`records_in`/`records_enriched`
(including the frontend's `importLeads` tests) are unaffected. The stage also degrades
gracefully: an injected extractor that offers only `extract_many` still works, since that is
the interface this stage has always depended on.

Per the brief, **no new endpoint was added and the Import Leads UI was not redesigned.** The
`[ ] Discover websites` / `[ ] Extract contacts` choice the brief anticipates is already
supported by the backend contract; surfacing it as checkboxes is a UI phase.

⚠️ **Operational note:** `extract_contacts` defaults to `true`, so a discovery run visits the
website of every lead that has one. With the shipped defaults that is bounded — at most
`1 + CONTACT_EXTRACTION_MAX_SUBPAGES` (5) pages per lead, 3 leads at a time, one request per
second per host — but it is real outbound traffic. An operator who wants map data alone sets
`extract_contacts: false`.

### Configuration

| Setting | Default | Purpose |
|---|---|---|
| `CONTACT_EXTRACTION_TIMEOUT_SECONDS` | `10.0` | Per-request timeout. |
| `CONTACT_EXTRACTION_MAX_SUBPAGES` | `4` | Second-level contact/about pages per lead. |
| `CONTACT_EXTRACTION_MAX_PAGE_BYTES` | `2_000_000` | Streamed body cap; exceeded ⇒ `invalid_content`. |
| `CONTACT_EXTRACTION_MAX_REDIRECTS` | `5` | Redirect chain cap. |
| `CONTACT_EXTRACTION_CONCURRENCY` | `3` | Leads visited at once. |
| `CONTACT_EXTRACTION_MIN_REQUEST_INTERVAL_SECONDS` | `1.0` | Gap between requests to the *same* host. |
| `CONTACT_EXTRACTION_RESPECT_ROBOTS` | `True` | Honour `robots.txt`. No operational reason to disable. |
| `CONTACT_EXTRACTION_USER_AGENT` | identifying string | Sent on every request; **set a real contact address in production**. |
| `CONTACT_EXTRACTION_PHONE_REGION` | `"IN"` | Region for parsing bare national numbers. |
| `CONTACT_EXTRACTION_MIN_RELEVANCE` | `0.3` | Band boundary for the advisory ownership score. |

The brief names five of these with a `WEBSITE_` prefix. Those names work as **aliases**:
`WEBSITE_CONTACT_TIMEOUT`, `WEBSITE_MAX_PAGES_PER_LEAD`, `WEBSITE_MAX_RESPONSE_BYTES`,
`WEBSITE_MAX_REDIRECTS`, `WEBSITE_MAX_CONCURRENT_REQUESTS`. Setting one in `.env` overrides
its canonical counterpart, so a documented variable name is never silently ignored. Note
`WEBSITE_MAX_PAGES_PER_LEAD` counts **total** pages including the home page, while
`CONTACT_EXTRACTION_MAX_SUBPAGES` counts only the second level — they differ by one.

### Privacy and compliance

- Only **publicly published** business contact details are read — the same pages any visitor
  sees. No login, no paywall, no form submission.
- **`robots.txt` is honoured**, cached once per host, and a `Disallow` is final.
- The service **identifies itself** by User-Agent and rate-limits per host.
- **No social-media scraping and no platform APIs.** Instagram/Facebook/YouTube values are the
  links the business publishes *on its own site*; those hosts are never requested. Asserted in
  the suite against the recorded request log.
- No Google Maps, no paid search APIs, no credentials of any kind.
- Data collected is business contact information, not personal data about individuals; the
  `owner_name` field is populated only when a site publishes it as a business contact.

## Lead Discovery Pipeline (`LeadDiscoveryService`)

**Phase goal.** Add the orchestrator that ties the existing collection and enrichment stages
into one runnable pipeline:

```
city → Overpass provider → website discovery → website contact extraction
     → normalization → deduplication → save new leads → summary
```

This is the wiring the two previous phases deliberately deferred. `WebsiteDiscoveryService`
and `ContactExtractorService` both shipped unwired, each with a note in `task.md` saying the
wiring "is small when it comes" and belongs with an operator-facing switch. This phase is
that wiring, and it ships the switch (`discover_websites` / `extract_contacts`).

Scope note: the service **orchestrates only**. It contains no scraping, no HTTP, no HTML
parsing, no matching rules and no normalisation logic — every one of those already lives in a
service with its own test suite, and duplicating any of it here would create two copies that
drift. This is asserted structurally in the suite, not just documented. No model, schema,
endpoint or provider changed, and **no Alembic migration** was generated because nothing
schema-shaped changed.

### Checklist

- [x] **`LeadDiscoveryService`** in `app/services/lead_discovery.py` — orchestrates the six
      stages and nothing else.
- [x] **City is the input.** `run(db, city=...)` is the whole call; `query` defaults to
      `"photography"` so a caller does not have to know the Overpass adapter needs a non-empty
      query alongside the city it actually geocodes.
- [x] **Every stage is dependency-injected** — `provider`, `website_discovery`,
      `contact_extractor`, `contact_normalizer`, `deduplication_service`, `lead_repository`,
      `activity_service`. All default to `None` and are resolved to the real implementation,
      so production constructs with no arguments and tests inject stubs.
- [x] **Provider resolution is lazy** (`provider` property), so constructing the service never
      depends on provider-registration import order, and one adapter instance — therefore one
      rate limiter — is reused across a run.
- [x] **Returns `{found, imported, merged, duplicates, failed}`** exactly, via
      `DiscoverySummary.to_dict()`. Diagnostics (per-stage counts, created/merged lead ids,
      error lines) are attributes and `to_detailed_dict()`, so the five-key contract is not
      widened.
- [x] **The counters reconcile**: `imported + merged + duplicates + failed == found`, exposed
      as `summary.reconciles`, logged at ERROR when it fails, and asserted on every scenario
      in the suite.
- [x] **Stages run as whole-batch passes**, so `discover_many` and `extract_many` fan out
      under their own semaphores instead of serialising a hundred round trips.
- [x] **Enrichment is best-effort, persistence is not.** Discovery and extraction never raise
      by contract and are not wrapped in a mask; a failed *write* is caught per record, the
      session rolled back, and the record counted in `failed`.
- [x] **A source-level provider fault propagates** rather than being reported as `found: 0` —
      "Overpass was unreachable" and "this city has no photographers" must not look identical.
- [x] **Operator switches** — `discover_websites=False` / `extract_contacts=False` skip the
      two network-touching stages for a re-run over an already-enriched city.
- [x] Integration suite `tests/test_lead_discovery.py` — 8 sections, real database, real
      deduplication and persistence, stubs for the three network stages.
- [x] `walkthrough.md` and `task.md` updated.

### Files

| File | Change |
|---|---|
| `app/services/lead_discovery.py` | **New** — the orchestrator, `DiscoverySummary`, `StageStats`. |
| `tests/test_lead_discovery.py` | **New** — 8-section integration suite. |

Every provider, `base.py`, `normalized.py`, `website_discovery.py`, `contact_extractor.py`,
`contact_normalization.py`, `lead_deduplication.py`, `lead_import.py`, all models, all schemas
and all endpoints are **unchanged**. No new dependency, no config change.

### Design decisions

1. **Orchestration-only is enforced, not requested.** Section 7 of the suite parses the module
   with `ast` and fails if it imports `httpx`, `requests`, `bs4`, `urllib`, `aiohttp`,
   `selenium` — or even `re`. A comment saying "no scraping here" is worth nothing the first
   time someone needs "just one regex"; a failing test is worth something. The same section
   asserts the module *does* call `discover_many`, `extract_many`, `normalize_lead`,
   `deduplicate` and `collect_normalized`, so the stages are delegated rather than reimplemented.
2. **Both normalisation passes run, and neither is redundant.**
   `ContactNormalizationService.normalize_lead` canonicalises *values* (E.164 phones,
   lowercased emails, bare handles); `NormalizedLead.normalize()` enforces the *record's*
   shape (column length caps, coordinate ranges, ordered phone de-duplication). Deduplication
   derives its comparison keys from both, so both must precede stage 5.
3. **Deduplication returns a plan; this service applies it.** `LeadDeduplicationService`
   performs no writes by design, so the transaction shape stays with the caller. This
   orchestrator writes per record — one unwritable row costs one row, not the run.
4. **A vanished merge target is a failure, not a re-create.** If the lead a record matched is
   deleted between planning and writing, the record is counted in `failed` with a reason.
   Re-creating it would resurrect a lead someone deliberately removed.
5. **`found` is the denominator, counted before any filtering.** Invalid records (no business
   name, no phone) are counted in `failed` rather than quietly dropped, which is what makes
   the reconciliation identity meaningful — a record cannot disappear between two stages
   without the totals disagreeing.
6. **Records are filtered for validity *before* deduplication**, so the stage does not spend a
   candidate query on a record that could never be stored.
7. **The provider is injected as an object, not resolved from the registry mid-run**, for the
   same reason `LeadImportService.run_import` accepts a `provider` argument: a service that
   reaches into a global registry during a run cannot be tested without mutating that global.

### Testing

`tests/test_lead_discovery.py` — 8 sections, run with `python tests/test_lead_discovery.py`.

It is an **integration** suite: the database is real, and four of the six stages are real
(normalization, deduplication, persistence, activity logging). Only the three
network-touching collaborators are stubbed, each implementing its port — `StubProvider`
(a real `LeadProvider`), `StubDiscovery`, `StubExtractor`. Those three have their own
dedicated suites already; what is under test here is the orchestration.

Covered: DI and defaults · stage order and hand-off (proven by recording harnesses, including
that extraction receives the website discovery found) · the five-key contract and its
reconciliation against rows actually in the database · enrichment reaching the saved `Lead` ·
merge / duplicate / within-batch-duplicate · invalid records, a failing write, a source fault,
and a refused request · the structural orchestration-only assertions · empty results and the
two stage toggles.

All rows are hard-deleted in a `finally` block (repository writes commit immediately, so a
session rollback would not undo them), matched by a per-run marker so a mid-suite failure
still cleans up. Neighbouring suites re-run green: `test_lead_deduplication`,
`test_website_discovery`, `test_contact_extractor`, `test_contact_normalization`,
`test_overpass_import`.

### Known gaps / follow-ups

1. **No endpoint yet.** The service is callable but unexposed; a `POST /leads/discover` taking
   a city belongs in a follow-up together with an RBAC permission and a decision about whether
   a long run should be backgrounded. A city-wide run issues one search and one site visit per
   lead found, so it is a slow request, not a snappy one.
2. **No `ImportJob` row.** `LeadImportService` records every run as an auditable job with a log
   array; this pipeline returns its summary in-process and leaves no trace beyond the leads and
   their activities. The two should converge — most naturally by having this service create an
   `ImportJob` too, rather than by adding a second audit shape.
3. **Overlap with `LeadImportService`.** `_create_lead`, `_resolve_source` and `_build_remarks`
   are close relatives of that service's versions. Left duplicated rather than hoisted, because
   the two differ where it matters (remarks wording, merge source) and a premature shared base
   class would couple two use cases that are still moving. Worth extracting once the endpoint
   above fixes their shapes.
4. **Single city per run.** Multi-city is a loop over `run()` by the caller; batching the
   geocode step across cities would be faster but is not needed until there is a scheduler.
5. **`radius_km` is passed through untouched** in `options`. Fine for Overpass; a second
   provider with a different geographic parameter would want a typed request object rather
   than a free-form dict.

---

# Phase — Production-Readiness of the Lead Discovery Workflow

## Objective

Make the end-to-end path — **city search → real businesses → contact information → clean
leads → CRM** — reliable, and make what it collected visible to the operator who has to act
on it. Not a rewrite: the six stages already existed and are largely untouched. This phase
audited the pipeline for silent data loss, fixed what it found, and surfaced the result.

## The audit, and what it found

Traced `POST /api/v1/leads/discover` → Overpass → website discovery → contact extraction →
normalization → deduplication → persistence. Stage order was correct, the counters
reconciled, and the two enrichment toggles were already wired end to end. Four real defects
came out of it:

1. **YouTube was collected and then discarded.** `ContactExtractorService` extracts YouTube
   URLs from business websites and carries them through `NormalizedLead.youtube`, but `Lead`
   had no `youtube` column, neither `_create_lead` mapped it nor `MERGEABLE_FIELDS` merged
   it. Every YouTube link the pipeline found died at the persistence boundary. This is the
   one genuine missing persisted field, so the `Lead` model gained a column and a migration.
2. **A plain phone number was treated as a WhatsApp number.** `whatsAppHref` fell back to
   `lead.phone` when `whatsapp` was empty, producing a `wa.me` link for numbers nothing had
   confirmed were on WhatsApp. Removed: the link is now built from the `whatsapp` column
   alone.
3. **The results table could not show what was collected.** `DiscoveryRecord` carried only
   name/phone/email/city/website, so WhatsApp, Instagram, Facebook and source were invisible
   to the operator even though they had been stored.
4. **No enrichment statistics existed.** The response reported the five counters but nothing
   about how much contact information a run actually landed.

Everything else the audit checked — website URLs not being overwritten, duplicates not
creating rows, per-record failure isolation — was already correct and was left alone.

## What changed

**Persistence.** `Lead.youtube` (`String(500)`, nullable) plus migration `5fa580580353`.
Mapped in `LeadDiscoveryService._create_lead` and `LeadImportService._create_lead` (the CSV
path had the same gap), added to `MERGEABLE_FIELDS`, and exposed on `LeadBase`/`LeadUpdate`
with the same URL validation `website` and `facebook` use.

**Enrichment statistics.** New `EnrichmentStats` on `DiscoverySummary`, computed once after
persistence by `compute_enrichment()` and projected as the `enrichment` key. The contact
counters are measured **over the leads actually written**, not over what a stage claimed to
find — a phone extracted but then dropped because the lead already had one is not a phone
this run delivered. No schema change: nothing here is persisted.

**Contact quality and WhatsApp readiness.** Both are derived properties on
`DiscoveredLeadRecord`, never columns. Quality is HIGH (number + second channel) / MEDIUM
(number only) / LOW (web or social only) / NONE. Readiness is true only when the `whatsapp`
column holds a number.

**UI.** The results table gained WhatsApp, Instagram, Facebook, Source and Quality columns,
`tel:` and `wa.me` links, truncation with the full value on hover, and
`rel="noopener noreferrer"` on every external link. Lead Details renders Facebook and
YouTube; the pipeline card badges WhatsApp-ready leads. Cache invalidation on
`leadKeys.all` after a run already existed and was verified.

## Testing

`tests/test_lead_discovery.py` gained section 9: every channel persists; an ordinary phone is
never read as WhatsApp; statistics are counted over what was written; a populated field
survives a weaker source while empty ones are filled; a failed enrichment saves the lead
unenriched. That last one drives the **real** `ContactExtractorService` against an
RFC 2606 `.invalid` host rather than a raising stub — the guarantee under test is the
extractor's own "never raises" contract, and a stub that throws would only prove the stub
throws. No test makes a real external request.

`tests/test_lead_discovery_endpoint.py` pins the response shape key-for-key; both pins were
widened deliberately for `enrichment` and the new record fields.

## Known gaps / follow-ups

1. **ESLint is not installed**, so `npm run lint` cannot run. Not installed here on
   instruction — the `package.json` script is unchanged and will work once a version is
   chosen deliberately.
2. **Discovery is still synchronous** and writes no `ImportJob` row, so the progress panel
   remains an elapsed-time estimate. Unchanged this phase; the polling seam is still in
   `discoveryHooks.ts`.
3. **`contact_quality` is computed in two places** — `DiscoveredLeadRecord.contact_quality`
   and `contactQualityOf` in `utils.ts` — because the pipeline card scores leads the backend
   never sent through discovery. The two are kept deliberately identical.
4. **WhatsApp readiness depends on sources labelling numbers.** A studio that publishes one
   number without marking it as WhatsApp is MEDIUM, not WhatsApp-ready, and will be missed by
   a campaign filter even if the number does work on WhatsApp. Deliberate: the alternative is
   guessing.
