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
