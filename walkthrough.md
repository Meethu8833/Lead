# Orders Module — Walkthrough

This document explains how the Orders foundation phase was built: architecture, component
hierarchy, data flow, validation, RBAC, responsive/loading strategy, and how it was verified.
It complements `task.md` (checklist + known gaps) and `CLAUDE.md` (repo-wide conventions).

## 1. Architecture

The module lives entirely under `src/features/orders/`, following the same shape as the
existing `src/features/dashboard/` module:

```
src/features/orders/
├── api.ts            # axios calls against the existing FastAPI /orders endpoints
├── hooks.ts           # TanStack Query wrappers (queries + mutations) over api.ts
├── types.ts            # TS types mirroring app/schemas/order.py & order_item.py
├── validation.ts        # Zod schemas for the order form and add-item dialog
├── components/
│   ├── OrdersTable.tsx
│   ├── OrderFilters.tsx
│   ├── OrderForm.tsx
│   ├── OrderItemsTable.tsx
│   ├── AddItemDialog.tsx
│   ├── OrderSummaryCard.tsx
│   ├── DeleteOrderDialog.tsx
│   ├── OrderStatusBadge.tsx      # OrderStatusBadge, ProductionStageBadge, PaymentStatusBadge
│   └── OrderSkeleton.tsx        # OrdersListSkeleton, OrderDetailsSkeleton, OrderFormSkeleton
└── pages/
    ├── OrdersPage.tsx
    ├── OrderDetailsPage.tsx
    ├── CreateOrderPage.tsx
    └── EditOrderPage.tsx
```

No existing UI primitives, hooks, or stores were duplicated. Every visual element is built from
`src/components/ui/*` (`DataTable`, `Select`, `Input`, `NumberInput`, `CurrencyInput`,
`Textarea`, `Dialog`, `ConfirmationDialog`, `Card`, `Badge`, `StatusBadge`, `Skeleton`,
`EmptyState`, `ErrorState`, `PageContainer`/`PageHeader`/`FilterBar`/`Section`, `Timeline`), the
shared axios instance (`src/services/api.ts`), the Zustand stores (`useAuthStore`,
`useNotificationStore`), and the RBAC helpers (`checkPermission`, `ProtectedRoute`).

## 2. Backend integration

Routes consumed (all already existed in `app/api/v1/endpoints/orders.py` and
`order_items.py` — nothing was added to the backend):

| Method | Path | Used by |
|---|---|---|
| GET | `/orders?skip&limit` | `useOrders` |
| GET | `/orders/{id}` | `useOrder` |
| POST | `/orders` | `useCreateOrder` |
| PUT | `/orders/{id}` | `useUpdateOrder` |
| DELETE | `/orders/{id}` | `useDeleteOrder` |
| POST | `/orders/{id}/items` | `useAddOrderItem` |
| PUT | `/order-items/{id}` | `useUpdateOrderItem` |
| DELETE | `/order-items/{id}` | `useRemoveOrderItem` |
| GET | `/photographers?skip&limit` | `usePhotographersLookup` (form/filter select) |
| GET | `/products/search?is_active=true` | `useActiveProductsLookup` (Add Item select) |

Three backend realities shaped the frontend design (all documented in `task.md`'s "Known gaps"
section, and confirmed with the project owner where they changed the spec's literal wording):

1. **No `Customer` entity** — `Photographer` is this CRM's client/lead entity and doubles as
   the order's customer, so "Photographer" and "Customer" are rendered as one combined field.
2. **No `priority` column on `Order`** — omitted from the form rather than silently discarding
   user input the backend would never persist.
3. **Items are a sub-resource** — `OrderCreate`/`OrderUpdate` don't accept an items array, and
   `total_amount` is always server-recalculated from item subtotals
   (`OrderService.update_order`, `recalculate_order_totals`). So `CreateOrderPage` only ever
   submits order-level fields; `OrderItemsTable` + `AddItemDialog` only become active once an
   order id exists (i.e. in `EditOrderPage`, reached automatically right after create).
4. **No total count / limited filters server-side** — `GET /orders` returns a bare array with
   no pagination metadata, and `search` only supports `order_number`/`job_name`/`status`.
   Sorting, pagination, and the remaining filters (payment status, photographer, date ranges)
   run client-side over a `limit=200` fetch — the same approach the existing dashboard module
   already uses for the same reason.

## 3. Component hierarchy

```
OrdersPage
├── PageHeader (title, "Create Order" button gated by orders:create)
├── OrderFilters (search, status, payment status, photographer, date ranges, clear)
├── OrdersTable (DataTable: sort, client pagination, sticky header, empty/loading state)
│   └── Actions column → View (always) / Edit (orders:update) / Delete (orders:delete)
└── DeleteOrderDialog (ConfirmationDialog wrapper)

CreateOrderPage
└── OrderForm (mode="create")
    └── (Order Items section shows a "save first" hint — no order id yet)

EditOrderPage
├── OrderForm (mode="edit", order=...)
│   └── OrderItemsTable (editable: inline quantity/unit price, remove, grand total)
└── AddItemDialog (product select, quantity, unit price override, discount, remarks)

OrderDetailsPage
├── OrderSummaryCard (order fields, photographer/customer, totals, status badges)
├── OrderItemsTable (editable=false, read-only)
└── Timeline + "Related Sections" placeholder (payments/invoices/deliveries — later phase)
```

`OrderForm` is the one component reused by both `CreateOrderPage` and `EditOrderPage` (per the
spec's "reusable OrderForm" requirement) — it branches internally on `mode`/`order` presence to
decide whether the Order Items section is interactive.

## 4. TanStack Query integration

All server state lives in `src/features/orders/hooks.ts`. Query keys:

- `['orders', 'list', skip, limit]` — order list
- `['orders', 'detail', id]` — single order (with items)
- `['orders', 'lookup', 'photographers']` / `['orders', 'lookup', 'products']` — form selects

Optimistic updates:
- **Update order** (`useUpdateOrder`) — patches the detail cache immediately in `onMutate`,
  rolls back on error, reconciles via `invalidateQueries` in `onSettled` (necessary since the
  backend recomputes `total_amount`/`payment_status` server-side).
- **Delete order** (`useDeleteOrder`) — removes the row from every cached list page in
  `onMutate`, restores it on error.
- **Add/update/remove item** (`useAddOrderItem` / `useUpdateOrderItem` / `useRemoveOrderItem`) —
  patch the parent order's `items` array optimistically, then invalidate both the order detail
  and the orders list (list totals depend on items too).

## 5. Form validation

`react-hook-form` + `zod` (`@hookform/resolvers/zod`), matching the one existing example in the
codebase (`src/pages/auth/Login.tsx`), but using the shared `Input`/`Select`/`NumberInput`/
`CurrencyInput`/`Textarea` components (which already render their own error text) instead of
raw `<input>` elements.

- `orderFormSchema` — requires `photographer_id`, `job_name`, `booking_date`; validates
  `advance_paid >= 0`; cross-field refine ensures `expected_delivery_date >= booking_date`,
  mirroring the backend's own `model_validator` in `app/schemas/order.py`.
- `addItemSchema` — requires `product_id` and `quantity >= 1`; `unit_price`/`discount` validated
  non-negative when provided, mirroring `app/schemas/order_item.py`.

## 6. RBAC

Enforced at two levels, matching the existing pattern:

- **Route level** (`src/App.tsx`) — `/orders` → `orders:view`, `/orders/new` → `orders:create`,
  `/orders/:id` → `orders:view`, `/orders/:id/edit` → `orders:update`, each wrapped in
  `ProtectedRoute`.
- **Element level** — `OrdersTable`'s Edit/Delete buttons and `OrdersPage`'s "Create Order"
  button are computed via `checkPermission(permissions, 'orders:update'|'orders:delete'|'orders:create', user?.role?.name)`
  and conditionally rendered, exactly like `DashboardPage.tsx` does for its own sections.
  `OrderDetailsPage` applies the same gating to its Edit/Delete buttons.

## 7. Responsive design

- `PageContainer` caps content width and applies responsive horizontal padding.
- `OrdersTable`/`OrderItemsTable` use `DataTable`, whose outer wrapper is
  `overflow-x-auto` — the table scrolls horizontally on narrow viewports instead of the page
  breaking layout.
- `OrderFilters` and the KPI-style Card grids in `OrderSummaryCard` use `flex-wrap` /
  responsive `grid-cols-*` breakpoints (`sm:`, `lg:`), matching the dashboard's existing layout
  conventions.
- Column resizing was **not** implemented — the shared `DataTable` component has no resize
  affordance, and adding one was judged out of scope for this phase (see `task.md`).

## 8. Loading strategy

- **List/details/form loading** — dedicated skeleton components
  (`OrdersListSkeleton`, `OrderDetailsSkeleton`, `OrderFormSkeleton`) built from the shared
  `Skeleton` primitive, shown while the initial query is in flight.
- **Refetch-in-place** — `OrdersTable` passes `loading={ordersQuery.isRefetching}` into
  `DataTable`, which renders skeleton rows without unmounting the page (used after filter
  changes / retries).
- **Mutation loading** — `Button`'s `isLoading` prop drives spinners on Create/Save/Delete/Add
  Item actions; `ConfirmationDialog` handles its own loading state for the delete confirm button.
- **Errors** — every page-level query failure renders the shared `ErrorState` with a `Try Again`
  button wired to `refetch()`.

## 9. Testing summary

`src/tests/orders.test.tsx` (14 tests, all passing) follows the same conventions as
`src/tests/dashboard.test.tsx`: a fresh `QueryClient` per test (`retry: false`), `vi.spyOn` on
`ordersApi`/`ordersLookupApi` methods instead of mocking axios directly, and real `useAuthStore`
state for RBAC (`login()` + `loadProfile(employee, permissions)`).

Covered: loading skeleton, list success + column rendering, error state + retry, search filter,
status filter + clear filters, RBAC-hidden vs RBAC-visible actions, delete confirm (calls API)
and delete cancel (does not call API), create-form required-field validation, full create →
redirect-to-edit flow, edit-page prefill + submit (asserts the update payload including
optimistic-lock `version`), add-item dialog flow, and order details rendering (summary + items +
RBAC-hidden edit/delete).

## 10. Build verification

```
npm run test    # 9 test files, 129/129 passing (includes the 14 new Orders tests)
npm run build   # tsc (zero errors) && vite build — succeeds
```

`npm run lint` could not be run in this environment (`eslint` binary is not installed in
`node_modules/.bin` here) — this is a pre-existing environment gap, not something introduced by
this change; `tsc`'s zero-error pass is the enforced type-safety bar per the task requirements.

---

# Lead Management Module — Backend Foundation Walkthrough

This document explains how the Lead Management backend foundation was built: architecture,
data model, RBAC, validation, and how it was verified. It complements `task.md` (checklist +
known gaps) and `CLAUDE.md` (repo-wide conventions). **No frontend work was done in this
phase** — this is backend-only, matching the explicit scope of the request.

## 1. Architecture

The module follows the exact same five-layer shape as every other entity in `app/` (see
`app/models/order.py` as the reference model, per `CLAUDE.md`):

```
app/models/lead.py               # Lead ORM model + LeadStatus/LeadSource enums
app/schemas/lead.py               # LeadCreate / LeadUpdate / LeadResponse / LeadListResponse
app/repositories/lead.py           # LeadRepository (+ AdminLeadRepository for soft-deleted rows)
app/services/lead.py               # LeadService — business rules, orchestration
app/api/v1/endpoints/leads.py       # 5 REST endpoints, each RBAC-gated
```

Wired in exactly like every other module:
- `app/models/__init__.py` — registers `Lead`, `LeadStatus`, `LeadSource` on `Base.metadata`.
- `app/schemas/__init__.py`, `app/repositories/__init__.py`, `app/services/__init__.py` — export
  the new classes alongside the existing ones.
- `app/api/deps.py` — adds `get_lead_service()` DI provider.
- `app/api/v1/router.py` — mounts `leads.router` under `/leads`.
- `scripts/seed_roles.py` — adds `leads:create/update/delete/view/*` permissions, grants
  `leads:*` to `Manager` and `Reception` (mirroring their existing `photographers:*` grant), and
  `Viewer`'s existing `*:view` wildcard automatically covers `leads:view`.

No existing ERP module (`Order`, `Payment`, `Inventory`, `Production`, `Delivery`, `Invoice`,
`Photographer`) was modified.

## 2. Data model (`app/models/lead.py`)

`Lead` is a **new, standalone entity** — it does not reuse or extend `Photographer` (which
already has its own separate `LeadStatus`/`LeadPriority`/`ContactMethod` CRM fields from an
earlier phase; see `app/models/photographer.py`). Keeping them separate was necessary, not just
tidy: the task specified a different `LeadStatus` value set (`MESSAGE_SENT`, `REPLIED`,
`NEGOTIATION`, `LOST`, ...) than `Photographer.LeadStatus` already uses
(`NEGOTIATING`, `INACTIVE`, `REJECTED`, ...), so reusing the name would have collided both at
the Python class level and at the PostgreSQL enum-type level. The new enums are named
`lead_status` / `lead_source` in Postgres (underscored) specifically to avoid clashing with the
pre-existing `leadstatus` enum type already owned by the `photographers` table.

Fields exactly as specified: `id` (UUID PK), `business_name` (required), `contact_person`,
`phone` (required, unique, indexed), `whatsapp`, `email`, `instagram`, `facebook`, `website`,
`address`, `city`, `district`, `state`, `country`, `latitude`/`longitude` (`Float`, optional),
`source` (`LeadSource`, default `MANUAL`), `status` (`LeadStatus`, default `NEW`),
`assigned_employee_id` (nullable FK → `employees.id`, `ON DELETE SET NULL` — a lead must survive
its assignee being removed), `remarks`, `is_converted` (bool, default `False`), plus the
standard `is_deleted`/`deleted_at`/`version`/`created_at`/`updated_at` quartet with
`__mapper_args__ = {"version_id_col": version}` for optimistic locking — copied verbatim from
`Order`/`Photographer`.

`status`, `source`, `city`, `district`, and `assigned_employee_id` are individually indexed
since they're the module's filter columns.

## 3. Validation (`app/schemas/lead.py`)

Validators mirror `app/schemas/photographer.py` exactly (same regexes for phone/email/URL/
Instagram-handle), since that's the closest existing precedent for this kind of contact-heavy
entity:
- `business_name` — required, whitespace-only rejected.
- `phone` — required, digits/`+`/`-`/`()`/spaces only, ≥7 digits, enforced unique by the service
  layer (`LeadRepository.get_by_phone`).
- `whatsapp`, `email`, `instagram`, `facebook`, `website` — all optional; format-validated only
  when present.
- `latitude`/`longitude` — optional, range-constrained (`-90..90` / `-180..180`) via Pydantic
  `Field(ge=..., le=...)`.
- `source` defaults to `MANUAL`, `status` defaults to `NEW` — and `LeadService.create_lead`
  **forces** `status=NEW` server-side regardless of what the client sends, the same pattern
  `PhotographerService.create_photographer` uses for `lead_status`.
- `LeadUpdate` — every field optional (partial update) plus a `version` field for optimistic
  locking, matching `PhotographerUpdate`/`OrderUpdate`.

## 4. Repository & filtering (`app/repositories/lead.py`)

`LeadRepository.get_all()` is the single query path behind both "List Leads" and "Search Leads"
— there's no separate `/leads/search` route (see §6); filters and the search keyword compose
together via one shared `_apply_filters()` helper used for both the page query and a parallel
`COUNT(*)` query, so `LeadListResponse.total` reflects the full filtered/searched result set,
not just the current page.

- **Filters**: `status`, `source`, `district` (partial, case-insensitive), `city` (partial,
  case-insensitive), `assigned_employee_id` (exact), `created_from`/`created_to` (range on
  `created_at`).
- **Search**: one `search` keyword OR-matched across `business_name`, `contact_person`, `phone`,
  `whatsapp`, `email` (all `ILIKE '%keyword%'`).
- **Soft delete**: every read path defaults to `is_deleted == False`; `AdminLeadRepository`
  (`include_deleted=True` by default) exists for admin/audit access to deleted rows, mirroring
  `AdminOrderRepository`/`AdminPhotographerRepository`.

## 5. RBAC

Unlike the existing `photographers`/`orders`/`inventory` endpoints (which have permission
*infrastructure* — `RequirePermission` in `app/api/deps.py` — but don't actually apply it to any
route), every `leads` endpoint is gated with
`dependencies=[Depends(RequirePermission("leads:<action>"))]`:

| Route | Permission |
|---|---|
| `POST /leads` | `leads:create` |
| `GET /leads`, `GET /leads/{id}` | `leads:view` |
| `PUT /leads/{id}` | `leads:update` |
| `DELETE /leads/{id}` | `leads:delete` |

This was a deliberate choice to satisfy the task's explicit "Use existing RBAC" requirement
literally and make it testable, rather than adding permission definitions that nothing enforces.
`RequirePermission` already supports wildcard matching (`leads:*`, `*:view`, `*:*`) and
`Administrator`/`is_system` role bypass — no changes were needed there.

## 6. API surface

Exactly the 5 routes specified — filtering/search/pagination are all query parameters on the
list route, not separate endpoints:

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/leads` | `leads:create` |
| `GET` | `/api/v1/leads` | `leads:view`. Query params: `skip`, `limit`, `status`, `source`, `district`, `city`, `assigned_employee_id`, `created_from`, `created_to`, `search`. Returns `LeadListResponse` (`items` + `total` + `skip` + `limit`) |
| `GET` | `/api/v1/leads/{id}` | `leads:view` |
| `PUT` | `/api/v1/leads/{id}` | `leads:update`. Enforces `version` optimistic lock when provided |
| `DELETE` | `/api/v1/leads/{id}` | `leads:delete`. Soft delete only |

`LeadListResponse` (a new envelope, not used elsewhere in the codebase) was added specifically
so pagination has an actual total count to page against — every other list endpoint in this
codebase (`GET /orders`, `GET /photographers`) returns a bare array with no count, which the
task's explicit "Pagination" requirement called out as needing more than.

## 7. Audit logging & optimistic locking

Both are automatic — no Lead-specific code was needed:
- The `before_flush` listener in `app/core/database.py` audits every `Lead` insert/update/delete
  the same as any other model. One subtlety verified by the test suite: because `Lead.status` is
  literally named `status` (one of the listener's special-cased `status_fields`), a status change
  is tagged `AuditAction.STATUS_CHANGE`, not a generic `UPDATE` — same as `Order.status` changes.
- `__mapper_args__ = {"version_id_col": version}` plus `LeadService.update_lead`'s explicit
  `schema.version != lead.version` check gives the same two-layer optimistic-lock protection
  (`ConflictException` / HTTP 409) as `Order` and `Photographer`.

## 8. Testing (`tests/test_leads.py`)

Follows this repo's non-pytest, direct-`asyncio.run()` integration-test convention (see
`CLAUDE.md` — there is no `pytest.ini`/`conftest.py`). Talks to the real configured database.
Covers, in order: create + enforced defaults (`status=NEW` even when a different status is
requested, `source=MANUAL` default), duplicate-phone rejection, blank-`business_name` schema
rejection, update + optimistic-lock conflict, filters (status/source/city/district/assigned
employee/created-date-range), search (all 5 searchable fields), pagination (skip/limit + total
count across two pages), soft delete (excluded from normal reads, still visible via
`AdminLeadRepository`, 404 on delete of a non-existent/already-deleted id), audit log rows for
CREATE/STATUS_CHANGE/DELETE, and RBAC (`Viewer` role allowed only on `leads:view` via its
`*:view` wildcard, `Designer` role blocked on all four `leads:*` actions since it has no leads
grant, `Administrator` bypasses everything).

Because every repository write commits immediately (same as `PhotographerRepository`/
`OrderRepository` — there is no session-level rollback safety net), the test explicitly
hard-deletes every `Lead`/`Employee` row it created in a `finally` block, rather than relying on
`db.rollback()` at the end (which several existing suites do, but which does not actually undo
already-committed writes — verified this is a pre-existing, documented characteristic of this
test harness, not something specific to this suite).

## 9. Verification results

```
python -m alembic upgrade head        # 2dcb418e93d7 (head) — leads table created cleanly
python scripts/seed_roles.py           # leads:create/update/delete/view/* permissions seeded,
                                        # idempotent re-run confirmed
python tests/test_leads.py             # ALL 10 sections passed
```

Full existing suite re-run for regressions (`tests/test_*.py`, one process per file):

| Suite | Result |
|---|---|
| `test_audit.py` | PASS |
| `test_dashboard.py` | PASS |
| `test_inventory.py` | PASS |
| `test_leads.py` (new) | PASS |
| `test_permissions.py` | PASS |
| `test_roles.py` | PASS |
| `test_search.py` | PASS |
| `test_auth.py` | PASS in isolation; fails inside the full sequential run at its own final
  assertion (`assert cleaned == 1`, expired-session-cleanup count) — pre-existing ordering
  sensitivity in that suite, reproduced identically on `main` before this change, unrelated to
  Lead code (Lead touches no auth/session tables) |
| `test_erp.py`, `test_production.py`, `test_delivery_payment.py` | Fail deterministically, both
  with and without this change, because the shared dev database already contains one
  permanently soft-deleted `Photographer` row (`ab3dd978-...`) that these suites' "grab any
  existing photographer" fixture logic doesn't filter by `is_deleted`. Reproduced by running
  `test_erp.py` completely alone, immediately after only `test_audit.py`/`test_dashboard.py` —
  no Lead code involved at all. Root cause pre-dates this session (confirmed the row was already
  `is_deleted=True` before any Lead-related test ran) and lives entirely in `Order`/`Photographer`
  test fixtures, which are out of scope per this task's "do not modify existing ERP modules"
  constraint. |

`npm run build` (`tsc && vite build`) — fails with 3 pre-existing TypeScript errors in
`src/features/orders/components/AddItemDialog.tsx` / `OrderItemEditor.tsx`
(`ProductSelectorProps.products` missing). Confirmed pre-existing and unrelated: this phase
touched zero frontend files (`git status` shows those files were already modified/untracked
before this session started, from the prior Orders-module work), and the task explicitly scoped
this phase to backend-only ("Do not begin frontend implementation").

---

# Lead Activity & Notes Module — Walkthrough

This document explains how the Lead Activity & Notes phase was built: the two new entities,
where automatic activities are emitted, the API surface, RBAC, and how it was verified.
It complements `task.md` (checklist + known gaps) and `CLAUDE.md` (repo-wide conventions).

## 1. Objective

Every interaction with a lead should be recorded chronologically, so the Lead Details page can
eventually render a complete timeline of everything that happened with that lead.

This phase delivers the backend for that timeline. WhatsApp automation, follow-ups, campaigns,
CSV import, and all frontend work are explicitly out of scope.

## 2. Two entities, one feature

The module deliberately splits the timeline into two tables rather than one:

| | `LeadActivity` | `LeadNote` |
|---|---|---|
| Written by | The system, as a side effect of domain events | A human, explicitly |
| Editable | **No** — append-only | Yes |
| Deletable | **No** through the API | Yes (soft delete) |
| Purpose | Faithful history of what happened | Working commentary |

The reasoning: a timeline that can be rewritten is not an audit trail. Notes need to be
editable (people fix typos and add detail); history must not be. Keeping them apart means
editing a note never mutates the historical record that a note *was written* at that moment.

Adding a note emits a `NOTE` activity carrying `metadata.note_id`, so the note still appears
on the timeline and the frontend can link the entry back to the live note body.

Consequently, **deleting a note does not delete its `NOTE` activity.** The timeline records
that a note was written then, which remains true regardless of the note's later fate.

## 3. Data model (`app/models/lead_activity.py`)

`LeadActivity`:

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | UUIDv4, house convention |
| `lead_id` | `UUID` FK → `leads.id` | `ON DELETE CASCADE` |
| `activity_type` | `Enum(lead_activity_type)` | indexed, 12 members |
| `title` | `String(255)` | short headline |
| `description` | `Text` nullable | longer detail |
| `created_by_employee_id` | `UUID` FK → `employees.id` nullable | `ON DELETE SET NULL` |
| `metadata` | `JSONB` nullable | structured payload |
| `created_at` | `DateTime(tz)` | `server_default=now()`, indexed |

`LeadNote`: `id`, `lead_id`, `note` (Text), `created_by_employee_id`, `is_deleted`/`deleted_at`,
`created_at`, `updated_at`.

Three decisions worth calling out:

1. **`metadata` is mapped as `activity_metadata` in Python.** `metadata` is reserved by
   SQLAlchemy's declarative base (it holds the `MetaData` registry), so the attribute is renamed
   while the DB column keeps the specified name `metadata`. `LeadActivityResponse` uses Pydantic
   `validation_alias`/`serialization_alias` to read `activity_metadata` off the ORM object and
   emit `metadata` on the wire — so the API contract is exactly as specified.
2. **No `version` column on either table.** Activities are append-only, so there is nothing to
   concurrently update. Notes are short single-author free text where last-write-wins is the
   expected behaviour and there is no derived financial/workflow state to protect (unlike
   `Lead`/`Order`). This is a deliberate divergence from `Lead`, not an oversight.
3. **Composite index `(lead_id, created_at DESC)`.** The one hot query on this table is
   "newest N activities for one lead"; this index serves it directly.

The `ActivityType` enum carries all 11 specified members plus `DELETED`. The four `WHATSAPP_*`
members exist so the schema is stable before the messaging integration lands, but **nothing in
this phase emits them** — verified by a test asserting `WHATSAPP_SENT` returns zero rows.

## 4. Where automatic activities come from

`LeadActivityService` is the single writer of the timeline: every automatic activity funnels
through its `record()` method, so the shape of an entry is defined in exactly one place.
`LeadService` calls the `log_*` helpers and stays unaware of the timeline's internals.

| Domain event | Activity emitted | Where |
|---|---|---|
| Lead created | `CREATED` | `LeadService.create_lead` |
| Lead updated | `UPDATED` (with an old→new field diff) | `LeadService.update_lead` |
| Status changed | `STATUS_CHANGED` **in addition to** `UPDATED` | `LeadService.update_lead` |
| Lead converted | `CONVERTED` | `LeadService.update_lead` |
| Lead deleted | `DELETED` | `LeadService.delete_lead` |
| Note added | `NOTE` | `LeadNoteService.create_note` |

Three behaviours here are non-obvious and are each pinned by a test:

- **A no-op update writes nothing.** `update_lead` snapshots the affected fields *before* the
  repository mutates the instance and drops any field whose submitted value equals the current
  value. Re-sending unchanged data is not a change and must not pollute the timeline. The diff
  also excludes bookkeeping columns (`version`, `updated_at`, …) so the entry reads
  "Updated field(s): city, contact_person", not a wall of noise.
- **A status change emits two entries** — the generic `UPDATED` and the specific
  `STATUS_CHANGED`. "Who moved this lead to NEGOTIATION and when" is the most-queried fact in
  the timeline and deserves its own filterable type.
- **`CONVERTED` fires on the transition, not the state.** Either `is_converted` flipping to
  `True` or `status` arriving at `CUSTOMER` counts; re-saving an already-converted lead does
  not append a duplicate.

Activities are written after the domain write succeeds, so a rejected create (duplicate phone)
or a rejected update (stale version) leaves no orphan entry — also covered by tests.

## 5. Actor attribution — and one real bug this caught

Activities record who acted via `created_by_employee_id`, resolved from the request-scoped
`audit_context` ContextVar — the same source the automatic audit-log listener uses, so an
activity and its audit row always agree on the actor, with no `employee_id` parameter threaded
through every service signature.

**The catch:** `audit_middleware` populates that context from the `x-user-id` / `x-performed-by`
request headers, which are *not authenticated* and may contain any string. `AuditLog.performed_by`
is free text and tolerates that, but `created_by_employee_id` is a real FK. The first version of
this module wrote the header value straight into the FK column, which meant **any request with a
bogus `x-user-id` header would have 500'd every lead write** with a `ForeignKeyViolationError`.

The existing `tests/test_leads.py` caught it immediately (it sets the context to a random UUID).
The fix is `resolve_actor_employee_id()`, which confirms the parsed UUID against the `employees`
table before use and falls back to `None` (a system-generated entry) when it does not resolve —
degrading attribution rather than failing the operation being recorded.

## 6. API surface

All five specified routes, in `app/api/v1/endpoints/lead_activities.py`:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/leads/{id}/notes` | `leads:view` | paginated, newest first |
| POST | `/api/v1/leads/{id}/notes` | `leads:update` | also emits the `NOTE` activity |
| PUT | `/api/v1/lead-notes/{id}` | `leads:update` | edits the body only |
| DELETE | `/api/v1/lead-notes/{id}` | `leads:update` | soft delete, 204 |
| GET | `/api/v1/leads/{id}/activities` | `leads:view` | paginated, newest first, `activity_type` filter |

Two routing details:

- The router is mounted with an **empty prefix** because its paths straddle two resource roots
  (`/leads/{id}/...` and `/lead-notes/{id}`), mirroring how `order_items.py` handles the same
  `/orders/{id}/items` + `/order-items/{id}` split.
- It is registered **before** the `leads` router in `app/api/v1/router.py`, so the literal
  `/leads/{id}/notes` and `/leads/{id}/activities` paths are matched ahead of `/leads/{id}`.

There is intentionally **no create/update/delete route for activities**, and
`LeadActivityRepository` exposes no `update`/`delete` method at all — the absence of those
methods is what enforces append-only at the data-access layer. A test asserts this.

Both list endpoints 404 on an unknown or soft-deleted lead, so they cannot be used to probe for
the existence of lead IDs.

## 7. Pagination & ordering

Both collections page with `skip`/`limit` and return `{items, total, skip, limit}` — `total`
being the count of *all* matching rows, independent of the page window.

Ordering is `created_at DESC, id DESC`. **The `id` tiebreaker matters:** several activities
emitted inside one transaction share an identical `created_at` (Postgres `now()` is fixed for
the whole transaction), and without a deterministic secondary sort those rows could shuffle
between pages, causing duplicates and gaps. The test suite pages through an 11-entry timeline in
pages of 3 and asserts the collected ids are complete, unique, and in the same order as the
unpaginated read.

## 8. Audit logging

Nothing new was wired. The `before_flush` listener in `app/core/database.py` already audits every
model except `AuditLog` itself, so `LeadActivity` and `LeadNote` are covered automatically —
verified by tests asserting `CREATE`/`UPDATE`/`DELETE` rows with correct `entity_name`,
`performed_by`, `ip_address`, and old→new note bodies.

This is also why **editing a note does not emit a new activity**: the timeline records that a
note was written; the audit log already captures the reword at the right level of detail.

## 9. Testing (`tests/test_lead_activities.py`)

16 sections, matching the house standalone-async-script convention (no pytest):

| # | Section | # | Section |
|---|---|---|---|
| 1 | `CREATED` activity + attribution | 9 | Pagination (activities + notes) |
| 2 | `UPDATED` diff + no-op suppression | 10 | Activity-type filtering |
| 3 | `STATUS_CHANGED` old/new metadata | 11 | Timeline immutability |
| 4 | `CONVERTED`, transition-only | 12 | JSONB round-trip + `metadata` aliasing |
| 5 | Note creation + emitted `NOTE` | 13 | `DELETED` on lead soft delete |
| 6 | Note editing | 14 | Audit-log reuse |
| 7 | Note listing + soft delete | 15 | RBAC |
| 8 | Timeline ordering | 16 | Regression: existing Lead CRUD |

Cleanup hard-deletes every created row in a `finally` block; deleting the parent `Lead` cascades
its activities and notes away.

## 10. Verification results

```
python -m alembic upgrade head          # 504f5c5d4a31 (head) — 2 new tables, applied cleanly
python -m alembic downgrade -1 && upgrade head   # round-trip verified
python -m alembic revision --autogenerate        # empty — no model/schema drift
python tests/test_lead_activities.py    # ALL 16 sections passed
python tests/test_leads.py              # ALL 10 sections passed (existing suite, still green)
```

Autogenerate detected **only** `lead_activities` + `lead_notes` and their indexes — **zero
changes to the `leads` table or any existing ERP table**, confirming the "do not modify" rules
were respected.

Full suite re-run for regressions (one process per file):

| Suite | Result |
|---|---|
| `test_audit.py`, `test_auth.py`, `test_dashboard.py`, `test_inventory.py`, `test_permissions.py`, `test_roles.py`, `test_search.py` | PASS |
| `test_leads.py` | PASS |
| `test_lead_activities.py` (new) | PASS |
| `test_erp.py`, `test_production.py`, `test_delivery_payment.py` | FAIL — **pre-existing**, see below |

The three ERP failures are the ones already documented in the previous phase: the shared dev
database contains a permanently soft-deleted `Photographer` (`ab3dd978-...`) that those suites'
"grab any existing photographer" fixture doesn't filter by `is_deleted`. This was **proven
pre-existing this phase** by `git stash`-ing all changes and re-running `test_erp.py` on the
clean tree — identical failure, identical photographer ID. The root cause lives in
`Order`/`Photographer` test fixtures, which the "do not modify existing ERP modules" constraint
puts out of scope.

---

# WhatsApp Campaign Management Module — Walkthrough

Backend-only phase. Pivots the product from a generic photographer ERP toward a **Lead
Generation CRM**: leads stop being rows in a table and start being messaged, tracked, and
re-categorised automatically. No ERP module was modified.

## 1. Objective

Build bulk WhatsApp outreach end to end — reusable templates, campaigns over many leads,
per-message delivery tracking, scheduling, reply recording, and automatic lead-status updates —
**without committing to a WhatsApp vendor**. Every design decision below that looks
over-engineered is paying for that last constraint.

## 2. The provider abstraction (the load-bearing decision)

`app/services/whatsapp_provider.py` defines the *port*; vendors will be *adapters*.

```python
class WhatsAppProvider(ABC):
    name: str
    async def send_message(self, phone, message, *, template_name=None, language="en") -> ProviderSendResult
    async def health_check(self) -> bool
```

**Why the interface is this narrow.** `send_message` takes a destination and an
**already-rendered string**. It deliberately does *not* take a template ID, a component array,
or any vendor payload shape, because those differ irreconcilably: Meta wants a registered
template name plus positional components, Twilio wants a `Body` string, Interakt wants its own
campaign JSON. Rendering in our own service and handing every provider a plain string is the
only contract all four can satisfy.

**The failure contract matters as much as the signature.** An adapter must **not raise** for an
ordinary per-message rejection (invalid number, opted out, rate limited) — it returns
`ProviderSendResult(success=False, error=...)` so the run marks that one recipient `FAILED` and
carries on. Raising is reserved for campaign-wide faults, which the dispatch loop catches per
recipient anyway so one poisoned row cannot abort a 10,000-lead send.

`NoOpWhatsAppProvider` is the default: it logs, fabricates a syntactically plausible
`noop-<uuid>` message ID, and reports success. That synthetic ID is deliberate — it means the
webhook-matching path (`provider_message_id` lookup) is genuinely exercised in tests rather
than bypassed. Adopting a real vendor changes exactly one thing: what
`get_whatsapp_provider()` returns. An unknown provider name **falls back to no-op with a
WARNING** rather than raising, so a misconfiguration degrades a campaign to a simulated,
fully-visible send instead of taking the API down.

A test asserts the campaign service source contains no reference to `twilio`, `interakt`,
`aisensy` or `graph.facebook.com`.

## 3. Data model (`app/models/whatsapp.py`)

Three entities, three layers of one feature:

| Entity | Role | Soft delete | `version` |
|---|---|---|---|
| `WhatsAppTemplate` | the *what* — reusable body with `{{variables}}` | yes | yes |
| `WhatsAppCampaign` | the *when / to whom* — one send of one template | yes | yes |
| `CampaignRecipient` | the *what actually happened* — per-lead delivery record | no | **no** |

Decisions worth stating:

- **`CampaignRecipient` has no `version` column** — a deliberate divergence from the house
  convention. Recipient rows are written by webhook callbacks that arrive concurrently and out
  of order; optimistic locking would turn a benign race into a 409. Ordering is instead enforced
  semantically by `MESSAGE_STATUS_RANK`, which is idempotent and commutative under retries.
- **`phone` and `rendered_message` are snapshotted onto the recipient row.** The number a
  message was sent to and the text that was sent are historical facts. If the lead later
  corrects their number, or an operator edits the template, the delivery record must not
  silently rewrite itself.
- **`template_id` uses `ON DELETE RESTRICT`**, not CASCADE or SET NULL. A campaign's audit value
  depends on knowing what was actually sent.
- **Partial unique index on template name** (`WHERE is_deleted = false`) — a name is unique
  among *live* templates, so soft-deleting one frees its name for reuse. A plain
  `UniqueConstraint` cannot express this.
- **`(campaign_id, lead_id)` unique constraint** — the database-level backstop behind the
  service's de-duplication, making "add recipients" idempotent.

One change to an existing table: **`Lead.last_contacted_at`** (nullable, indexed). The spec
requires updating it on reply and the column did not exist. It is indexed because "leads not
contacted since X" is the follow-up worklist query.

## 4. Status is monotonic, not last-write-wins

```python
MESSAGE_STATUS_RANK = {PENDING:0, QUEUED:1, SENT:2, DELIVERED:3, READ:4, FAILED:5, REPLIED:6}
```

Providers retry and reorder webhooks. A "delivered" callback arriving *after* a "read" one must
be a no-op, not a regression — so a status may only be overwritten by one of strictly greater
rank, and the matching timestamp is stamped only on a real forward transition. **This is what
makes the webhook endpoints idempotent under replay**, which is the property webhook delivery
actually needs.

`FAILED` and `REPLIED` sit *above* the delivery ladder because both are terminal outcomes that
must not be clobbered by a late "delivered" arriving after the lead already answered.

Pinned by a test that applies `DELIVERED` → `READ` → `DELIVERED` and asserts both the status
and the original `read_at` are untouched.

## 5. Counters are recomputed, never incremented

All six `total_*` columns on a campaign are derived from **one grouped query** over the
recipient rows (`_recompute_counters`). Incrementing them per transition would let a single
missed webhook desynchronise them permanently; recomputing makes drift impossible by
construction. `GET /statistics` recomputes independently from the same source, so the
denormalized columns are a display cache and never a correctness dependency — a test asserts
the two agree.

**Counts are cumulative, not exclusive.** A lead who replied also received and read the message,
so `total_delivered` means "reached DELIVERED **or beyond**". Counting them only under "replied"
would make the delivery rate understate reality. Asserted directly: one READ recipient out of
four ⇒ `delivery_rate == read_rate == 25.0`.

## 6. Rendering, and why unmatched placeholders survive

`WhatsAppTemplateService.render` substitutes `{{placeholder}}` in a **single regex pass** and
returns `(rendered, missing)`.

- A value that itself contains `{{...}}` **cannot be re-expanded** — one pass, no recursion, so
  there is no template-injection vector through variable values. Tested.
- **Unmatched placeholders are left verbatim**, not replaced with an empty string. `"Hi {{name}}"`
  is an obvious bug a reviewer catches; `"Hi "` looks deliberate and would ship.
- A template's `variables` column is **derived from the body on every write**, never accepted
  from the client, so the two can never drift. `WhatsAppTemplateCreate` has no `variables` field.

## 7. Dispatch (`POST /campaigns/{id}/start`)

The whole run is **one transaction**, and per recipient it: renders from the lead record →
calls the provider → records the outcome → appends a `WHATSAPP_SENT` activity → stamps
`Lead.last_contacted_at`.

Rules that matter:

- The campaign is marked `RUNNING` **before** the loop, so a concurrent second Start is rejected
  by the transition table rather than double-sending.
- **Only `PENDING` recipients are dispatched**, so re-running a partially-failed campaign never
  double-sends to a lead that already received the message.
- The template is **re-validated as active at dispatch time**, so deactivating a template does
  stop a scheduled campaign going out.
- One recipient's failure never aborts the run — a provider exception is caught per recipient,
  recorded as `FAILED` with its reason, and the loop continues.
- Two queries, not N: the audience's leads are loaded in one `IN` query, and enrolment
  de-duplicates in memory against one existing-recipients query.

`lead.last_contacted_at` is assigned on the loaded instance rather than through
`LeadRepository.update`, because that method commits unconditionally and would break the run's
single-transaction guarantee.

## 8. Replies — the CRM automation

`CampaignReplyService` is separated from the campaign service because the two have opposite risk
profiles: the outbound side talks to a third party and may fail per message; this side mutates
CRM state the sales team relies on and must be conservative about what it overwrites.

One transaction does five things: recipient → `REPLIED` (body + timestamp); a
`WHATSAPP_REPLIED` timeline entry; `Lead.last_contacted_at`; the status automation; counter
recompute. Committing them together is the point — *a lead whose status says NEGOTIATION but
whose timeline has no reply explaining why is exactly the inconsistency that erodes trust in a
CRM.*

The mapping is **data, not branching** (`REPLY_TYPE_TO_LEAD_STATUS`):

| `reply_type` | New `Lead.status` |
|---|---|
| `interested` | `NEGOTIATION` |
| `not_interested` | `LOST` |
| `need_details` | `REPLIED` |

Three guards, each tested:

1. An explicit `lead_status` in the payload **overrides** the mapping — a human classification is
   better evidence than a keyword rule.
2. An **unrecognised** `reply_type` maps to nothing rather than to a default, so a new intent
   label added upstream cannot silently reclassify leads.
3. A lead at `CUSTOMER` is **never** re-categorised. Without this, a stray "thanks!" after
   conversion would demote a customer back to `NEGOTIATION`.

Matching prefers `provider_message_id` (pins the reply to an exact outbound message) and falls
back to `phone` against that number's **most recent dispatch** — the best available correlation
when a provider gives us nothing else, and how a human reads the conversation.

## 9. Timeline integration — emitting what was already reserved

The Lead Activity module defined `WHATSAPP_SENT` / `DELIVERED` / `READ` / `REPLIED` in a
previous phase specifically for this integration, with nothing writing them. This module adds
**no new timeline concepts** — it finally emits the ones that were waiting. Dispatch writes
`WHATSAPP_SENT`, status callbacks write `WHATSAPP_DELIVERED` / `WHATSAPP_READ`, replies write
`WHATSAPP_REPLIED` plus a `STATUS_CHANGED` when the automation moves the lead.

## 10. RBAC

A **dedicated `whatsapp:*` permission set**, not a reuse of `leads:*`. Editing a lead record and
blasting a campaign to thousands of leads are different capabilities with different blast radii
— a receptionist who may correct a phone number should not thereby be able to message everyone.
(This is the opposite call from lead *notes*, which correctly reuse `leads:*` because a note is
commentary on a lead, not a new capability.)

Seeded to **Manager** (`whatsapp:*`) and **Reception** (view/create/update — runs outreach daily
but may not delete campaign history). Tested positively (Administrator bypass, Manager granted)
and negatively (a Designer, who holds orders/production permissions, is refused all four).

## 11. API surface

19 routes under `/api/v1/whatsapp`, every one behind `RequirePermission`:

| Method | Path | Permission |
|---|---|---|
| GET / POST | `/templates` | `whatsapp:view` / `create` |
| GET / PUT / DELETE | `/templates/{id}` | `view` / `update` / `delete` |
| POST | `/templates/{id}/preview` | `whatsapp:view` |
| GET / POST | `/campaigns` | `view` / `create` |
| GET / PUT / DELETE | `/campaigns/{id}` | `view` / `update` / `delete` |
| POST | `/campaigns/{id}/start` | `whatsapp:update` |
| POST | `/campaigns/{id}/cancel` | `whatsapp:update` |
| GET | `/campaigns/{id}/statistics` | `whatsapp:view` |
| GET / POST | `/campaigns/{id}/recipients` | `view` / `update` |
| DELETE | `/campaigns/{id}/recipients/{recipient_id}` | `whatsapp:update` |
| POST | `/webhook/reply` | `whatsapp:update` |
| POST | `/webhook/status` | `whatsapp:update` |

On the webhooks: a real provider cannot present a JWT and will need signature verification
(`X-Hub-Signature-256` / `X-Twilio-Signature`) instead. That check is provider-specific and is
deferred with the adapter. Leaving them behind RBAC meanwhile is the safe default — an
unauthenticated webhook with no signature check would let anyone on the internet rewrite lead
statuses.

## 12. Lifecycle state machine

```
DRAFT     -> SCHEDULED | RUNNING | CANCELLED
SCHEDULED -> SCHEDULED | RUNNING | CANCELLED | DRAFT
RUNNING   -> COMPLETED | CANCELLED
COMPLETED -> (terminal)
CANCELLED -> (terminal)
```

Anything unlisted is a 400, so a campaign cannot be restarted after completion. `SCHEDULED →
SCHEDULED` is legal because re-scheduling to a different time is an ordinary operation, not a
state change — **this was a bug the test suite caught** (see §14).

Only `DRAFT`/`SCHEDULED` campaigns are editable or accept new recipients; once dispatch begins
the campaign is a historical record. Only `PENDING` recipients can be removed — anything queued
or sent is a delivery record, and deleting it would erase evidence a lead was contacted.

## 13. Testing (`tests/test_whatsapp.py`)

15 sections, following the house standalone-async-script convention (no pytest). Three provider
doubles exercise the port: `RecordingProvider` (captures exactly what was sent),
`FailingProvider` (rejects without raising), `ExplodingProvider` (raises on the 2nd message, to
prove one poisoned recipient does not abort the run).

Beyond the required coverage, it pins: no double-send on restart, empty-campaign refusal,
template-injection resistance, webhook replay idempotency, cumulative-rate arithmetic,
denormalized-vs-recomputed counter agreement, converted-lead protection, and the negative RBAC
case.

## 14. Two real bugs the suite caught

1. **`SCHEDULED → SCHEDULED` was missing from the transition table**, so rescheduling an
   already-scheduled campaign raised a 400 — an operator would have had to bounce it back to
   `DRAFT` just to move it by an hour. Added as legal.
2. **`error_text` was assigned only inside the dispatch loop's `except` branch**, so a stale
   failure reason from an earlier recipient could be attributed to a later one. Now reset per
   iteration.

A third failure was the *test's* fault, and is worth recording: recipient **list position is not
stable across reads**, because bulk enrolment writes every row in one transaction (identical
`created_at`, Postgres `now()` being fixed per transaction) so ordering falls to the random-UUID
`id` tiebreaker. The repository ordering is correct; the test now keys recipients by `lead_id`.

## 15. Verification results

```
python -m alembic upgrade head                   # 3f2dfbe6340d — 3 tables + leads.last_contacted_at
python -m alembic downgrade -1 && upgrade head   # round-trip verified (incl. explicit DROP TYPE)
python scripts/seed_roles.py                     # whatsapp:* seeded, idempotent
python tests/test_whatsapp.py                    # ALL 15 sections passed, x3 consecutive runs
```

The migration needed one hand-edit autogenerate cannot produce: **explicit `DROP TYPE` for the
three new enums in `downgrade()`**. Postgres keeps an ENUM after the only table using it is
dropped, so without it a downgrade-then-re-upgrade fails with "type already exists" — the same
fix the `lead_activities` migration (`504f5c5d4a31`) carries.

Full suite re-run for regressions (one process per file):

| Suite | Result |
|---|---|
| `test_whatsapp.py` (new) | **PASS** |
| `test_leads.py`, `test_lead_activities.py` | PASS |
| `test_audit.py`, `test_auth.py`, `test_permissions.py`, `test_roles.py` | PASS |
| `test_dashboard.py`, `test_inventory.py`, `test_search.py` | PASS |
| `test_erp.py`, `test_production.py`, `test_delivery_payment.py` | FAIL — **pre-existing** |

The three ERP failures are the ones documented in both previous phases: the shared dev database
holds a permanently soft-deleted `Photographer` (`ab3dd978-f407-44a9-8e6f-b18b2873fa1f`) that
those suites' "grab any existing photographer" fixture does not filter by `is_deleted`.
Identical error and identical photographer ID as before this phase. The root cause lives in
`Order`/`Photographer` test fixtures, which the "do not modify unrelated ERP modules" constraint
puts out of scope.

---

# Lead Collection Engine — Walkthrough

## 1. Objective

Collect photographer leads from many different sources into the existing `leads` table,
without ever creating a duplicate, and make adding the *next* source a change that touches
no existing file.

Scope was strictly the collection path. Orders, Inventory, Production, Payments, Dashboard
and every other ERP module are untouched; the `Lead` model itself is untouched. The one
schema addition is a new `import_jobs` table.

Explicitly out of scope, by instruction: **real scraping**. What ships is the provider
architecture, one working `MockProvider`, and a working CSV importer.

## 2. What was built

| Layer | File | Role |
|---|---|---|
| Model | `app/models/import_job.py` | `ImportJob` + `ImportJobStatus`, the audit record of one run |
| Provider port | `app/services/lead_providers/base.py` | `LeadProvider` ABC, `ProviderContext`, the registry |
| Normalized DTO | `app/services/lead_providers/normalized.py` | `NormalizedLead` + the key-derivation functions |
| Adapter | `app/services/lead_providers/mock.py` | `MockLeadProvider` — deterministic offline fixtures |
| Adapter | `app/services/lead_providers/csv_provider.py` | `CsvLeadProvider` — alias-mapped CSV upload |
| Adapters | `app/services/lead_providers/planned.py` | 6 declared-but-unimplemented sources |
| Repository | `app/repositories/import_job.py` | Job CRUD, log append, SQL statistics |
| Repository | `app/repositories/lead.py` | **+ `find_duplicate_candidates`** (the only edit to an existing repo) |
| Service | `app/services/lead_import.py` | `LeadImportService` — dedup, enrichment, lifecycle, retry |
| Schemas | `app/schemas/import_job.py` | Request/response DTOs |
| Endpoints | `app/api/v1/endpoints/lead_imports.py` | 7 routes |
| Migration | `alembic/versions/21a40470e494_*.py` | `import_jobs` table |
| Tests | `tests/test_lead_import.py` | 8-section integration suite |

## 3. The provider contract

`search(query)` → `collect()` → `normalize()`, exactly as specified.

The split matters. `search()` **validates and returns a `ProviderContext`** rather than
doing work, so a bad request (missing query, missing file, unimplemented source) fails
*before* an `ImportJob` row exists — no misleading FAILED job is left behind. `collect()` is
the only method that touches the outside world and the only `async` one. `normalize()` is
pure mapping, which is the part that differs most per source and the part testable with no
network at all.

Run-specific state lives on the `ProviderContext`, never on the provider instance, so two
concurrent imports through one provider cannot read each other's query.

**Failure contract**, mirroring `WhatsAppProvider`: `normalize()` must not raise for a merely
bad record — it returns a record failing `is_valid()`, the run counts one failure and
carries on. Raising is reserved for source-level faults, which fail the whole run.
`collect_normalized()` contains a contract violation anyway, so a provider that *does* raise
costs one record rather than the run.

## 4. Why `NormalizedLead` carries lists

`phone_numbers` and `emails` are lists while `leads` stores a single unique `phone` plus one
`whatsapp`. That mismatch is deliberate and is the single most important design decision here.

A Google Maps or Justdial listing routinely exposes a landline *and* a mobile. If the DTO
flattened to one number early, the extras would be discarded **before deduplication ran** —
and deduplication is exactly what needs them. A business first captured under its landline
and later re-scraped under its mobile is only caught as a duplicate if every number the new
record carries is checked against every number the CRM holds. Flattening happens once, at the
persistence boundary in `LeadImportService`, not in the DTO.

Ordering is preserved through normalisation for the same reason it matters: providers list
the primary contact first, so `phone_numbers[0]` becomes `phone` and `[1]` becomes
`whatsapp`. Sorting would silently promote an arbitrary landline to the headline number.

## 5. Deduplication

All three rules run in **one OR'd SQL query**, not three sequential queries short-circuiting
on the first hit:

```sql
phone_key(phone) IN (:keys) OR phone_key(whatsapp) IN (:keys)
  OR lower(trim(email)) IN (:emails)
  OR (name_key || '|' || city_key) = :business_key
```

One query because the rules can **disagree**: a record's phone can match lead A while its
name+city matches lead B (the same studio captured twice under two numbers). Short-circuiting
would hide that pre-existing duplicate pair. The service then ranks candidates by confidence
— **phone > email > business_name+city** — and picks the winner.

Phone ranks highest because it is the CRM's unique key and the channel actually used.
Name+city ranks lowest because it is the only rule that can match two genuinely different
businesses (a chain with two branches in one city), so it must never override a contact-level
match. `normalize_business_key` returns `None` unless **both** name and city are present:
matching on a bare business name is precisely what produces false merges.

Matching is normalised **in SQL** (`regexp_replace` on digits, `right(…, 10)`) so it survives
formatting already in the stored data, not just in the incoming record.

**Within-batch dedup** runs too. One scrape routinely returns the same studio twice under two
phone formats; without it, the second occurrence would either violate the `phone` unique
constraint or slip through under a different number and create the duplicate this module
exists to prevent.

## 6. Enrichment, not overwrite

A match **fills empty fields only**. A collected record never overwrites data already in the
CRM, because the existing value may have been typed by a human who phoned the business, and a
scraped listing is not evidence strong enough to discard that. `phone` is excluded entirely
(it is the unique key and the thing matched on); `status`, `is_converted` and
`assigned_employee_id` are excluded because they are CRM workflow state no external source
should touch.

One deliberate exception, documented in `_build_enrichment`: if the lead has no WhatsApp
number and the incoming primary phone differs from the stored one, that second number is
recorded as `whatsapp` — otherwise a genuinely new contact number would be thrown away.

If a match carries **nothing** new, no write happens and the record counts as a *duplicate*
rather than an *update*. That is what makes re-running an import a true no-op instead of
version-number churn — verified in the suite by asserting `lead.version` is unchanged.

## 7. Job lifecycle and why `PARTIAL` exists

```
PENDING → RUNNING → COMPLETED | PARTIAL | FAILED
```

`PARTIAL` is neither success nor failure: a hundred-record run with three malformed records
has ninety-seven good leads already in the CRM that must not be re-imported wholesale, but
still needs flagging. Retrying a `PARTIAL` run is safe *precisely because* deduplication makes
re-importing the ninety-seven a no-op — asserted directly in the suite.

Each record commits on its own. Record 150 failing must not roll back the 149 already
imported, because the operator's only alternative is re-running the whole scrape. A failed
write also rolls the session back before continuing, so one poisoned record cannot leave the
transaction unusable for the rest.

A run that collected **zero** records is `COMPLETED`, not `FAILED` — "this query matched
nothing" is a correct answer.

**Retry creates a new row** linked by `retry_of_job_id` rather than resetting the original,
because overwriting would destroy the record of the first failure, which is the main thing an
operator wants when diagnosing why a retry was needed. CSV jobs are refused for retry: the
uploaded bytes are not retained (storing them would turn the CRM into a document store), so
the operator is directed to re-upload.

The four counters are **stored, not derived** — they cannot be recomputed later. A lead
enriched by a run is indistinguishable afterwards from one a human edited, and a failed record
leaves no row at all. `duplicate_leads` is tracked separately so
`found = new + updated + duplicates + failed` always reconciles; the suite asserts it.

## 8. Extensibility — the actual requirement

`ImportJob.provider` is a **`String`, not an enum**. An enum would force a migration and an
`ALTER TYPE` for every new provider, directly contradicting the requirement. The valid set is
owned by the registry and validated at the service boundary.

The six unimplemented sources ship as registered `PlannedProvider` subclasses rather than TODO
comments, so they are discoverable via `GET /leads/import/providers`, the API validates
against the full set (a client naming `google_maps` gets "declared but not yet implemented",
not "unknown provider" which reads like a typo), and each source's `LeadSource` attribution is
decided now so later imports tag consistently.

Adding a provider is: one new module, one `@register_provider` decorator, one import line.
**The test suite proves this** — it defines an `AdHocProvider` inline, registers it, and runs
a real import through it with zero changes to `LeadImportService`.

Unlike `get_whatsapp_provider`, an unknown key **raises rather than falling back**. Silently
substituting a provider is fine when the outcome is a simulated message; it is not fine when
the outcome is writing rows into the CRM under the wrong `source` attribution.

## 9. CSV import

Headers are matched **case- and punctuation-insensitively against alias lists** ("Business
Name" / "business_name" / "Studio" / "NAME" all map to `business_name`), because forcing
operators to reshape their file in a spreadsheet is exactly where leads get mangled. Several
columns can feed one field — a file with both "Phone" and "Alternate Phone" contributes both,
leftmost becoming primary. Unrecognised columns are preserved in `raw` rather than discarded.

Multi-value cells split on `, ; | /` — but **only for columns mapped to multi-value fields**.
"+91 98765 43210, 080-2345-6789" and "Bengaluru, Karnataka" are both comma-bearing cells;
splitting everything would corrupt the second.

Delimiter is sniffed (comma/semicolon/tab/pipe). Decoding tries UTF-8-with-BOM then falls back
to latin-1, which cannot fail — Excel on Windows still emits cp1252, and refusing those files
would make the feature useless to the operators most likely to need it. Blank rows are skipped
rather than counted as failures. Failures are reported **by row number**.

File-level faults (empty, no header, no mappable column, header with no data rows) fail the
run once instead of producing N identical row errors.

## 10. Route ordering

`lead_imports.router` is registered **before** `leads.router` at the root prefix. Otherwise
`GET /leads/imports` is swallowed by `GET /leads/{id}` and fails as an invalid UUID — the same
constraint already documented for `lead_activities.py`. `/leads/imports/statistics` likewise
precedes `/leads/imports/{id}`.

Import routes require **`leads:import`**, a new permission distinct from `leads:create`:
bulk-importing hundreds of leads has a different blast radius from adding one by hand, so a
role can hold one without the other. `leads:*` covers it via the existing wildcard matcher, so
Manager and Reception inherit it without a mapping change.

## 11. A real bug the suite caught

**`limit=0` was silently accepted as `limit=100`.** `LeadProvider.search` read
`kwargs.get("limit") or 100`, and `0 or 100` is `100` in Python — so the `if limit < 1` guard
directly below it was unreachable and an explicit `limit=0` became a full-size import. Fixed
to `if limit is None`. This is the classic falsy-vs-None bug and it was caught only because the
suite asserted the *rejection* rather than just the happy path.

## 12. Verification results

```
alembic upgrade head                            # 21a40470e494 — import_jobs
alembic downgrade -1 && alembic upgrade head    # round-trip verified (incl. explicit DROP TYPE)
python scripts/seed_roles.py                    # leads:import seeded, idempotent
python tests/test_lead_import.py                # ALL 8 sections passed
```

Autogenerate needed the same hand-edit as previous phases: **explicit `DROP TYPE` for
`import_job_status` in `downgrade()`**, since Postgres keeps an ENUM after the only table using
it is dropped and a downgrade-then-re-upgrade would fail with "type already exists". Verified by
actually running the round-trip.

The autogenerated diff contained **only** `import_jobs` — no drift into any other module,
confirming nothing existing was disturbed.

Full suite re-run for regressions (one process per file):

| Suite | Result |
|---|---|
| `test_lead_import.py` (new) | **PASS** |
| `test_leads.py`, `test_lead_activities.py`, `test_whatsapp.py` | PASS |
| `test_audit.py`, `test_auth.py`, `test_permissions.py`, `test_roles.py` | PASS |
| `test_dashboard.py`, `test_inventory.py`, `test_search.py` | PASS |
| `test_erp.py`, `test_production.py`, `test_delivery_payment.py` | FAIL — **pre-existing** |

The three ERP failures are the same ones documented in all three previous phases: the shared
dev database holds a permanently soft-deleted `Photographer`
(`ab3dd978-f407-44a9-8e6f-b18b2873fa1f`) that those suites' "grab any existing photographer"
fixture does not filter by `is_deleted`. Confirmed identical error and identical photographer
ID, and confirmed they fail **in isolation** on the Orders creation path, which this module
never touches.

Worth recording: an initial regression sweep mis-reported `test_whatsapp.py` as failing. It
does not — that suite deliberately logs a `RuntimeError("Simulated provider outage")` traceback
while testing its own per-recipient error isolation, and a grep-based pass/fail check picked up
the logged traceback. The detection was wrong, not the suite.

## 13. Isolation check

The suite asserts this directly rather than assuming it: a control `Lead` is created with a
non-default status, a full import is run, and the control lead is verified to have an unchanged
`version`, `status` and `contact_person`. Imported leads are asserted to start at `NEW`,
never pre-converted, and to receive a `CREATED` timeline activity — so collected leads enter
the existing CRM pipeline exactly as hand-entered ones do.

---

# Google Maps Lead Provider — Walkthrough

## 1. Objective

Implement the first *real* lead source behind the Lead Collection Engine's provider interface:
Google Maps. A user searches "Wedding Photographer Thrissur" and photography businesses land in
the `leads` table — deduplicated, enriched, audited — without a single line of the import
service changing.

The previous phase built the engine and deliberately shipped Google Maps as a `PlannedProvider`
stub: registered and discoverable, but refusing to run. Its docstring claimed that implementing
it would be "provably a closed change: replace the class body, drop `is_available = False`.
Nothing in the service, the endpoints, the schemas or the database is touched." This phase is
the test of that claim.

## 2. What the claim cost

It held, with one deliberate refinement.

**Untouched, as predicted:** `LeadImportService` (all 794 lines), every endpoint, every Pydantic
schema, the `ImportJob` model, the `Lead` model, `NormalizedLead`, and the database — **no
migration was generated or needed**. `LeadSource.GOOGLE_MAPS` already existed. `POST
/api/v1/leads/import` was reused verbatim; the route list is byte-identical.

**Added:** one module, `app/services/lead_providers/google_maps.py`.

**Changed, and worth explaining:** three small things the stub's prediction did not anticipate.

1. The class was *deleted* from `planned.py` rather than edited in place, because a real
   provider does not belong in a file whose entire purpose is declaring unimplemented ones.
2. `LeadProvider.unavailable_reason` was added as an overridable property (see §5) — a genuine
   interface gap the stub could not have surfaced, because a planned provider only ever has one
   reason for being unavailable.
3. `tests/test_lead_import.py` asserted google_maps was an unimplemented stub, so those
   assertions were inverted.

That is the honest accounting: the architecture delivered what it promised, and the one
interface change was a real improvement rather than a workaround.

## 3. Two API calls, and why the order matters

Google's Text Search answers "what places match this query" but returns **neither a phone
number nor a website**. Both come only from Place Details, a second call keyed by `place_id`.
Since `NormalizedLead.is_valid()` rejects any record without a phone, a Text-Search-only adapter
would produce a run in which *every record failed*.

So collection is N+1 calls for N businesses — and Details is billed **per call**. That single
fact drives the three main decisions in this module:

**`context.limit` is applied before the Details fan-out.** Text Search returns 20 results per
page and paginates to 60. Applying the limit after collecting search pages would make `limit=5`
cost 20 Details calls — a 4× overcharge invisible in the returned data. The limit is applied to
the search results first, so asking for 5 businesses costs exactly 5 Details calls.

This is asserted directly in the suite, by counting calls rather than records:

```
limit=5 over 20 available results cost exactly 5 Details calls — the limit is applied
before the billed fan-out.
```

Testing the returned records alone would pass either way. The cost model is the part that bites
in production, so it is tested as behaviour.

**Details calls are concurrent, bounded at 5 in flight.** Twenty sequential round-trips to
Google inside a synchronous HTTP request is the difference between a 2-second import and a
30-second one. Bounded rather than unbounded so a 60-result run does not open 60 sockets and
trip per-second quota limits.

**Permanently closed businesses are dropped before Details.** A closed studio is not a lead, and
filtering after the fan-out would mean paying to discover that.

## 4. The failure contract, which is the whole point

The engine already distinguishes a *run-level* fault (source unreachable, credentials rejected →
job FAILED, nothing collected) from a *record-level* one (this business is unusable → counted,
logged, run continues). A network-bound provider is where that distinction earns its keep, and
this adapter maps onto it deliberately:

| Google outcome | Treated as | Why |
|---|---|---|
| `REQUEST_DENIED` | Run-level → job FAILED | Bad/missing key; every remaining call fails identically |
| `OVER_QUERY_LIMIT` | Run-level → job FAILED | Quota gone; continuing burns time to no effect |
| HTTP 5xx / unparseable body | Run-level → job FAILED | Not attributable to one business |
| Details times out for one place | **Record-level** | The other 59 businesses are fine |
| Details returns `NOT_FOUND` | **Record-level** | One stale `place_id` |
| `ZERO_RESULTS` | **Success, empty** | "Nothing matched" is a correct answer |

The subtle one is a failed Details lookup. It is **not** discarded: the Text Search half is still
a real listing, so the record is kept with a `detail_error` breadcrumb in `raw` and simply lacks
the fields Details would have supplied. It then fails validation on its own merits — no phone —
and is counted and logged by the engine exactly like a CSV row with an empty phone column.

This is why `_fetch_details` returns `(payload, error)` instead of raising. At the point of
failure the adapter does not yet know whether the record is salvageable, and deciding that there
would duplicate a judgement `LeadImportService` already makes. The provider reports; the engine
decides.

The suite proves the guarantee end to end — five businesses, one timing out, one `NOT_FOUND`:

```
A timing-out and a NOT_FOUND business cost 2 records; the other 3 imported normally.
Status PARTIAL — one failure never stops the run.
```

## 5. Unavailable is not the same as unimplemented

The base class refused unavailable providers with a hardcoded message: *"declared but not yet
implemented, so it cannot be run."* Correct for a `PlannedProvider`. Actively misleading for
Google Maps, which is fully built and merely missing an API key — it sends an operator hunting
for a missing feature when the fix is one environment variable.

So `LeadProvider` gained an overridable `unavailable_reason` property, and `describe()` now
surfaces it to `GET /leads/import/providers`. Planned providers keep the original wording;
Google Maps names the setting:

```
google_maps      available=False  Google Maps lead collection is not configured:
                                  GOOGLE_MAPS_API_KEY is unset...
justdial         available=False  Provider 'justdial' (Justdial) is declared but not
                                  yet implemented...
```

`is_available` is itself a computed property here, not a class constant, because availability is
a *deployment* fact rather than a code fact: the same build is unavailable in a dev environment
with no key and available in production. Computing it means an unconfigured deployment gets a
clear 400 **before** the job row is created, rather than a 403 from Google partway through a run
already marked RUNNING.

## 6. Configuration — no key in code, anywhere

Every knob lives in `app/core/config.py`, read from the environment by Pydantic Settings:
`GOOGLE_MAPS_API_KEY`, `GOOGLE_MAPS_BASE_URL`, `GOOGLE_MAPS_REGION`, `GOOGLE_MAPS_LANGUAGE`,
`GOOGLE_MAPS_TIMEOUT_SECONDS`, `GOOGLE_MAPS_FETCH_DETAILS`, `GOOGLE_MAPS_MAX_PAGES`.

`GOOGLE_MAPS_API_KEY` defaults to `""` on purpose — an empty key disables the provider with a
clear message, which is strictly better than a placeholder that fails at request time with an
opaque 403. `GOOGLE_MAPS_BASE_URL` is configurable so a test or proxy can redirect the adapter
without patching it. `GOOGLE_MAPS_FETCH_DETAILS=false` turns the billed fan-out off entirely for
an operator who wants a cheap survey of what exists and accepts that most records will then
fail for want of a phone number.

`httpx` is imported **lazily**, inside `collect()`. The package `__init__` imports this module at
startup for its registration side effect, so a top-level `import httpx` would take the entire API
down on an image that never uses this provider. Absent, it becomes one clear run-level error.

## 7. Mapping Google's address shape onto the CRM

Google returns a flat list of typed `address_components`, not a structured address. Untangling it
is most of `normalize()`:

| CRM column | Google component types (in preference order) |
|---|---|
| `city` | `locality` → `postal_town` → `sublocality_level_1` → `sublocality` |
| `district` | `administrative_area_level_2` |
| `state` | `administrative_area_level_1` |
| `country` | `country` |
| `pincode` | `postal_code` |

The fallbacks are not decoration. Many Kerala studios sit in a `sublocality` rather than a
`locality`, and `administrative_area_level_2` is Google's own modelling of Indian districts —
which is why "Kozhikode" can legitimately be both the city and the district.

**The city fallback exists to protect deduplication.** `normalize_business_key` returns no key
unless *both* business name and city are present, so a record with no locality component
silently loses the business-name+city duplicate rule and re-imports next month as a new lead. A
last-resort parse derives the city from the formatted address (Indian addresses end
`..., City, State PIN, India`), returning `None` rather than guessing when the shape does not
match — a *wrong* city creates false merges, which is the more expensive error.

Phone ordering is also deliberate: the international form (`+91 495 276 5432`) is listed first
because it is what the CRM's phone normalisation collapses most reliably and what an operator
can dial from anywhere. Where the national form is genuinely different it follows as the second
number, so a business is never reduced to one contact route by our formatting preference alone.

Two fields are left deliberately empty. Google Places exposes **no email address** and **no owner
name**. `emails` stays `[]` rather than scraping the business website (a different integration
with different consent implications), and `owner_name` stays `None` rather than being guessed
from the business name — a guess would pollute the CRM's `contact_person` with something no
human said.

## 8. What the provider does *not* do

The brief's constraint was that no business logic may live in the provider, and that lead
creation, deduplication, enrichment and audit logging stay in the import service. Concretely,
`google_maps.py` contains **no** import of `Lead`, `LeadRepository`, `ImportJob`, or any session
type. It cannot write to the database; it has nothing to write with. It returns
`NormalizedLead` objects and the engine does the rest — which is why "reuses the existing
deduplication pipeline" is a structural fact here rather than a claim needing verification.

The suite asserts the observable half of this directly: the run's `new_leads` count is the
service's, and a Google listing matching a hand-entered lead **enriches** it rather than
duplicating it, without touching the human's data:

```
A Google listing matching a hand-entered lead by phone ENRICHED it (website filled)
without overwriting the human's data or its status.
```

## 9. Testing (`tests/test_google_maps_import.py`)

Seven sections, matching the brief: provider initialization, search execution, normalization,
import pipeline, duplicate handling, import statistics, error handling.

The provider runs against a **stub HTTP transport**, not the live API — so the suite needs no
API key, no network and no billing, and is deterministic. The stub speaks real Google response
shapes (`status` + `results`/`result`, `next_page_token`, typed `address_components`, both phone
forms), and `StubbedGoogleMapsProvider` overrides **only** `_import_httpx`. Pagination, the
Details fan-out, the merge and every error path are the production code; the stub replaces the
socket and nothing else.

The stub also *records* every request, which is what makes the cost assertions in §3 possible —
call counts are behaviour worth testing, not an implementation detail.

Notable cases beyond the happy path: the limit-before-fan-out cost guarantee; pagination across
3 pages for 45 results; permanently-closed businesses skipped before being billed for;
`ZERO_RESULTS` as an empty success; a Details lookup that times out and one that returns
`NOT_FOUND` in the same run; `REQUEST_DENIED`; `OVER_QUERY_LIMIT`; an HTTP 503; collecting with
no key at all; `normalize()` handed `{}` and other nonsense; two Google results for one business
collapsing within a batch; and a re-run of the identical search creating zero new leads.

## 10. Verification results

```
python tests/test_google_maps_import.py     # ALL 7 sections PASS
python tests/test_lead_import.py            # ALL 8 sections PASS (updated + re-run)
```

Full regression sweep, one process per file — **12 suites pass**: `test_audit.py`,
`test_auth.py`, `test_dashboard.py`, `test_google_maps_import.py`, `test_inventory.py`,
`test_lead_activities.py`, `test_lead_import.py`, `test_leads.py`, `test_permissions.py`,
`test_roles.py`, `test_search.py`, `test_whatsapp.py`.

`test_erp.py`, `test_production.py` and `test_delivery_payment.py` **FAIL — pre-existing**, on
the same soft-deleted `Photographer` (`ab3dd978-f407-44a9-8e6f-b18b2873fa1f`) documented in all
four previous phases. Re-confirmed here rather than assumed: the row was queried directly and is
`is_deleted=True` with a `created_at` predating this phase, and those suites' "grab any existing
photographer" fixture does not filter by `is_deleted`. They fail on the Orders creation path,
which this module never touches.

No migration was generated, because nothing schema-shaped changed.

## 11. Isolation check

The route table was diffed before and after: `/api/v1/leads/import`, `/leads/import/csv`,
`/leads/import/providers`, `/leads/imports`, `/leads/imports/statistics`,
`/leads/imports/{id}`, `/leads/imports/{id}/retry` — unchanged, no endpoint added, as required.

WhatsApp, Lead Management, ERP, Orders, Inventory, Payments, Production, Delivery, Dashboard and
Authentication were not modified. Outside the provider module and its test, the edits are:
`config.py` (settings block), `requirements.txt` (`httpx`), `planned.py` (stub deleted),
`lead_providers/__init__.py` (one import + one export), `base.py` (the `unavailable_reason`
hook), and `test_lead_import.py` (inverted assertions).

---

# Instagram Lead Provider — Walkthrough

## 1. Objective

Implement an Instagram lead provider that discovers photography businesses and imports them
through the existing Lead Collection Engine, following the existing `LeadProvider` interface
and the existing `ImportJob` workflow.

The brief was explicit that this phase is *only* the provider: the collection engine, the
ImportJob lifecycle, the Google Maps provider, deduplication and the registry were already
built. Nothing outside the collection path was to be touched, and no new API endpoint was to
be added.

## 2. The constraint that shaped everything: Instagram has no search

The Google Maps provider could take "Wedding Photographer Thrissur" and hand it almost
verbatim to Text Search. Instagram cannot. Its only sanctioned route to another business's
public profile is **Business Discovery**, and Business Discovery is shaped as:

> *my* IG Business account asks about *that exact username*

It takes a username. Not a query. There is no endpoint anywhere in the Graph API that accepts
"Wedding Photographer Kerala" and returns photographers.

The only query-shaped surface the API has is the **hashtag** endpoints. So discovery had to
become two phases:

```
"Wedding Photographer Kerala"
        │
        │  search()  — translate the query into hashtags
        ▼
#weddingphotographerkerala, #weddingphotographer, #keralaphotography, …
        │
        │  collect() phase 1 — ig_hashtag_search → top_media / recent_media
        ▼
candidate usernames:  sunrise_studio_klm, candid_by_arun, …
        │
        │  collect() phase 2 — business_discovery, one call per username
        ▼
full public profiles → normalize() → NormalizedLead
```

Phase 2 is one call per profile, which is the same N+1 cost shape the Google Maps adapter had,
and it is handled the same way — see §4.

## 3. Query → hashtag translation, and why the ordering is load-bearing

`search()` splits the operator's query into *intent* words ("wedding", "photographer") and
*place* words ("Kerala", "Kozhikode"), then recombines them into the hashtags a photographer in
that place would realistically use. All five search forms from the brief:

| Query | First hashtag | Inferred location |
|---|---|---|
| Wedding Photographer Kerala | `#weddingphotographerkerala` | — / Kerala |
| Photographer Kozhikode | `#photographerkozhikode` | Kozhikode / Kerala |
| Photography Studio Kochi | `#photographystudiokochi` | Kochi / Kerala |
| Wedding Photography Thrissur | `#weddingphotographythrissur` | Thrissur / Kerala |
| Pre Wedding Photography Kerala | `#preweddingphotographykerala` | — / Kerala |

The list is ordered **most-precise-first**, and that ordering does real work. Collection walks
the list only until it has enough candidates, so a run that fills its limit from
`#weddingphotographerkozhikode` never pays for the nationally-noisy `#weddingphotographer` at
all. Both forms are needed: the compound tag is precise but sparse, the bare tag is populated
but returns the whole country. A run searching only one of them would either find almost
nothing or find everything.

The inferred location is also recorded on the context, and `normalize()` uses it as a
**fallback** for profiles whose bio names no city — never as an override. A profile's own
stated city always wins, because it is the business's statement about itself.

## 4. The cost decision, again — limit before fan-out

Identical reasoning to the Google Maps provider, and the same assertion in the tests:

```python
selected = usernames[: context.limit]     # BEFORE any Business Discovery call
return await self._fetch_profiles(client, selected, context)
```

Hashtag pages happily yield 150 candidates. If the limit were applied after the fan-out, a
`limit=10` run would spend 150 Business Discovery calls against a rate-limited API to throw 140
away. The test asserts the cost model directly, not just the output:

```
Limit honoured before the fan-out: 40 discoverable, 10 requested, exactly 10 lookups spent.
```

Lookups run at bounded concurrency (`INSTAGRAM_CONCURRENCY`, default 5) rather than
sequentially — 20 sequential round-trips to Meta inside one HTTP request is the difference
between a 2-second import and a 30-second one.

Because a fraction of harvested usernames turn out to be personal accounts that Business
Discovery refuses, collection gathers `limit × 2` candidates (capped at 300) so a `limit=20`
run usually returns 20 profiles rather than 12. Kept small deliberately: every surplus candidate
that *does* resolve is a lookup spent past the limit.

## 5. Bio parsing — the riskiest code in the provider

Instagram exposes `biography`, `website`, `followers_count` and friends as structured fields.
It does **not** expose a phone number, an email, a WhatsApp number or an address as fields at
all. Photographers write them into the bio:

```
📸 Sunrise Wedding Studio
📍 Kozhikode, Kerala | 📞 +91 98470 12345 | WhatsApp 9847098765 | hello@sunrise.in
```

So `_parse_bio` does the job Google's `address_components` did for the previous provider —
except it is parsing free text written by humans with emoji, rather than a typed list. That
makes it the least certain code in the adapter, and every extraction in it is deliberately
**conservative: it returns nothing rather than guessing.**

The reason is that the costs are asymmetric. A missing phone number means one lead is skipped
and logged — recoverable, visible, and the operator can add it by hand. A *wrong* phone number
means the record silently merges onto an unrelated existing lead, because phone is the
highest-confidence duplicate rule, and quietly corrupts a row a human may have curated. **Under-
extraction is recoverable; over-extraction is not.**

Concretely, the four refusals, each with a test asserting it:

**Cities are matched against a known vocabulary, not parsed.** A bio reading
`"📍 Kozhikode | Destination weddings worldwide"` would give a general-purpose place parser
"Destination" or "Worldwide" as the city. A wrong city feeds the business-name+city duplicate
rule, so it can merge two unrelated studios or split one across two rows. An unrecognised place
yields **no city**, and the lead imports without one.

**A number is WhatsApp only when the bio says so** — in words ("WhatsApp: 9847012345") or as a
`wa.me` link. An unlabelled second number stays an ordinary phone, because promoting a studio's
landline into the `whatsapp` column would have the CRM's messaging features dial a number that
cannot receive messages.

**A 📍 marker does not by itself produce an address.** `"📍 Kozhikode, Kerala"` is a city and a
state the record already carries in structured form; copying it into `address` would duplicate
data rather than add any. A segment consisting *only* of known place names is rejected — a real
street address always carries something more:

```
"📍 Kozhikode, Kerala"                    → address = None      (city = Kozhikode)
"📍 3rd Floor, MG Road, Thrissur 680001"  → address = "3rd Floor, MG Road, Thrissur 680001"
```

**Pincode extraction strips phone-shaped substrings first**, so a 10-digit mobile cannot donate
six of its digits to a false pincode match.

Phone ordering is also deliberate: the studio's main line goes to `phone` and the labelled
WhatsApp number to `whatsapp`, matching what those two columns actually mean, rather than
leading with whichever appeared first in the text.

## 6. Dropped vs failed — the one place this differs from Google Maps

This is the design decision most worth understanding, because the two providers deliberately
diverge.

For Google Maps, a failed Place Details call still leaves a **real listing** worth keeping —
name, address, rating — so the record is retained with a `detail_error` breadcrumb and fails
validation on its own merits.

For Instagram, a failed Business Discovery leaves a **username and nothing else**: no name, no
bio, no contact route. There is nothing to import. And the common cause is not a fault at all —
it is a personal account, which Business Discovery refuses *by design*, and hashtag discovery
surfaces plenty of them (couples, guests, venues who tagged the same thing).

So those candidates are **dropped during collection and logged**, not carried forward as
guaranteed failed records. Counting every personal account as a `failed_record` would make that
counter useless as a signal that something is actually wrong. `failed_records` is reserved for
profiles that *were* collected and still could not become leads — a business profile with no
publishable phone number, for instance.

The tests assert both halves of this: a personal account is attempted then dropped
(`COMPLETED`, no failure counted), while a business profile with an empty bio is collected and
counted as a genuine failure (`PARTIAL`, `failed_records=1`, reason in the log).

## 7. The failure contract

`ProviderCollectionError` is raised **only** for faults that invalidate the whole run:

| Fault | Meta code | Outcome |
|---|---|---|
| Invalid / expired token | 190, subcode 463/467 | run FAILED, message names `INSTAGRAM_ACCESS_TOKEN` |
| Session expired | 102 | run FAILED |
| Rate limit reached | 4, 17, 32, 613 | run FAILED, message says wait for the window |
| Missing permission | 10, 200–299 | run FAILED, names the required scopes |
| Meta unreachable / 5xx | — | run FAILED |
| **Personal account** | 110 | **one record dropped, run continues** |
| **Per-profile timeout** | — | **one record dropped, run continues** |
| **Profile with no phone** | — | **one failed record, run continues** |

A rejected token fails the run rather than 200 individual records because it will apply
identically to every remaining profile — failing once with an actionable message beats failing
two hundred times with the same one.

One subtlety: **Meta reports its errors in the response body with HTTP 400**, so `_request`
parses the body *before* judging the status code. That is the only way to tell an expired token
(fatal) from a personal account (ordinary) — both arrive as a 400.

## 8. Configuration — no credential in code, anywhere

Nine settings in `app/core/config.py`, all read from the environment:

```
INSTAGRAM_ACCESS_TOKEN           (no default — empty disables the provider)
INSTAGRAM_BUSINESS_ACCOUNT_ID    (no default — empty disables the provider)
INSTAGRAM_GRAPH_BASE_URL         https://graph.facebook.com
INSTAGRAM_GRAPH_API_VERSION      v21.0
INSTAGRAM_TIMEOUT_SECONDS        15.0
INSTAGRAM_CONCURRENCY            5
INSTAGRAM_MAX_PAGES              3
INSTAGRAM_REQUIRE_CONTACT        true
INSTAGRAM_MIN_FOLLOWERS          0
```

**Both** credentials are required for `is_available`, because Business Discovery is issued *as*
an account — a token with no account id has nothing to ask on behalf of. And
`unavailable_reason` names exactly the setting(s) that are missing rather than listing both
generically:

```
INSTAGRAM_ACCESS_TOKEN="", INSTAGRAM_BUSINESS_ACCOUNT_ID=""
  → "…INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID are unset."

INSTAGRAM_ACCESS_TOKEN=set,  INSTAGRAM_BUSINESS_ACCOUNT_ID=""
  → "…INSTAGRAM_BUSINESS_ACCOUNT_ID is unset."
```

This matters because it sends the operator to the right environment variable. An unconfigured
deployment refuses at `search()` — a clear 400 *before* any job row is created — rather than a
Meta error 190 halfway through a run already marked RUNNING.

## 9. What the provider does *not* do

- **It does not scrape.** Discovery and collection both go through the official Graph API.
  A profile that the API will not disclose is not obtained by another route.
- **It does not import personal accounts.** They publish no contact route, so they are not
  leads.
- **It does not touch the `Lead` table.** It returns `NormalizedLead` objects;
  `LeadImportService` alone decides what becomes a row.
- **It does not reimplement deduplication.** The three existing rules (phone > email >
  name+city), the within-batch matching and the enrich-don't-overwrite policy are all reused
  untouched.
- **It does not add an endpoint.** `POST /api/v1/leads/import` was reused exactly as it stood.
- **It does not guess.** See §5.

## 10. Testing (`tests/test_instagram_import.py`)

Eight sections, run against a stub HTTP transport rather than the live Graph API — so the suite
needs no access token, no Meta app, no network, and is deterministic. The stub speaks real Graph
response shapes (`data` + `paging.cursors`, the nested `business_discovery` field, Meta's
`error.code`/`error_subcode` envelope), and `StubbedInstagramProvider` overrides **only**
`_import_httpx`, so `search()`, `collect()`, `normalize()`, hashtag pagination, the fan-out and
every error path under test are the production code. The stub replaces the socket, nothing else.

1. **Provider initialization** — registry resolution, no longer a `PlannedProvider`, capability
   description, both-credentials availability logic, refusal messages naming the exact missing
   setting.
2. **Search execution** — all five documented query forms, hashtag precision ordering, explicit
   city parameter, empty/unsearchable query rejection, limit clamping.
3. **Profile collection** — hashtag walk, **the limit honoured before the fan-out**, personal
   accounts dropped, pagination, zero-result handled as success.
4. **Normalization** — every public field mapped, bio parsing for phone/WhatsApp/email/city/
   state/pincode/address, and the four conservative refusals from §5 asserted individually.
5. **Import pipeline** — leads created through `LeadImportService`, tagged `INSTAGRAM`, at
   status `NEW`, with a timeline activity and extras in remarks.
6. **Duplicate detection** — a re-run creates nothing new; an Instagram record matching a
   hand-entered lead by phone enriches it (handle + email added) without rewriting its source or
   phone; two profiles sharing a number within one batch collapse onto one lead.
7. **Import statistics** — counters reconcile against `total_found`; provider and query recorded.
8. **Error handling** — one unusable profile does not stop the run (`PARTIAL`, reason logged);
   a per-profile timeout degrades one record only; expired token, rate limit and transport faults
   each fail the run with an actionable message.

## 11. Verification results

```
python tests/test_instagram_import.py       # ALL 8 sections PASS
python tests/test_lead_import.py            # ALL 8 sections PASS (updated + re-run)
python tests/test_google_maps_import.py     # ALL 7 sections PASS
```

Full regression sweep, one process per file — **13 suites pass**: `test_audit.py`,
`test_auth.py`, `test_dashboard.py`, `test_google_maps_import.py`, `test_instagram_import.py`,
`test_inventory.py`, `test_lead_activities.py`, `test_lead_import.py`, `test_leads.py`,
`test_permissions.py`, `test_roles.py`, `test_search.py`, `test_whatsapp.py`.

`test_erp.py`, `test_production.py` and `test_delivery_payment.py` **FAIL — pre-existing**, on
the same soft-deleted `Photographer` (`ab3dd978-f407-44a9-8e6f-b18b2873fa1f`) documented in all
five previous phases. They fail on the Orders creation path, which this module never touches.

`tests/test_lead_import.py` needed one update: it asserted `instagram` was an unimplemented
`PlannedProvider`. That assertion was inverted, exactly as the Google Maps phase did before it —
which is itself the evidence for §12.

No migration was generated, because nothing schema-shaped changed. `LeadSource.INSTAGRAM`
already existed from the Lead Management phase.

## 12. Isolation check

The route table was diffed before and after: `/api/v1/leads/import`, `/leads/import/csv`,
`/leads/import/providers`, `/leads/imports`, `/leads/imports/statistics`,
`/leads/imports/{id}`, `/leads/imports/{id}/retry` — **unchanged, no endpoint added**, as
required.

ERP, Orders, Inventory, WhatsApp Campaigns, Authentication and Lead Management were not
modified. Outside the new provider module and its test, the edits are:

| File | Change |
|---|---|
| `app/core/config.py` | nine-setting block appended |
| `.env` | matching commented block |
| `lead_providers/planned.py` | `InstagramLeadProvider` stub deleted, docstring updated |
| `lead_providers/__init__.py` | one import + one export |
| `tests/test_lead_import.py` | inverted the "instagram is planned" assertions |

`LeadImportService`, `base.py`, the endpoints, the schemas, the repositories, the models and the
database were **not** touched. Adding this provider was one new module, one import line and one
deleted stub — the extensibility property the engine was built to have, demonstrated a second
time.
