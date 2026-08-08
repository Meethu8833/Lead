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

---

# Follow-up & Task Management — Walkthrough

## 1. Objective

Build a follow-up engine that answers one question for every employee, every morning:
**which leads need action today?**

Scope was strictly the follow-up path. Orders, Inventory, Production, Billing and
Authentication are untouched. The Lead, LeadActivity and WhatsApp modules were extended at
exactly three points (two automation hooks and five new activity-type members), and nowhere
else. The one schema addition is a new `follow_up_tasks` table.

Explicitly out of scope, by instruction: **notifications** and **background schedulers**.
Both shaped the design rather than being stubbed — see §5, which is the most consequential
section of this document.

## 2. What was built

| Layer | File | Role |
|---|---|---|
| Model | `app/models/follow_up.py` | `FollowUpTask` + `FollowUpType`/`FollowUpPriority`/`FollowUpStatus` |
| Model | `app/models/lead_activity.py` | **+5 `ActivityType` members** (the only edit to that file) |
| Repository | `app/repositories/follow_up.py` | CRUD, the three worklist queries, aggregate helpers |
| Service | `app/services/follow_up.py` | `FollowUpTaskService` (lifecycle) + `FollowUpAutomationService` (triggers) |
| Service | `app/services/lead.py` | **+ the NEGOTIATION hook** (one call in `update_lead`) |
| Service | `app/services/whatsapp.py` | **+ the reply hook** (two calls in `record_reply`) |
| Schemas | `app/schemas/follow_up.py` | 10 request/response DTOs |
| Endpoints | `app/api/v1/endpoints/followups.py` | 13 routes |
| RBAC | `scripts/seed_roles.py` | `followups:{view,create,update,delete,*}` + role grants |
| Migration | `alembic/versions/9dcc5194e0bb_*.py` | `follow_up_tasks` table + enum extension |
| Tests | `tests/test_followups.py` | 15-section integration suite |

## 3. Task vs. Activity — why both exist

The obvious simplification is to fold follow-ups into `LeadActivity`, which already has a
`FOLLOW_UP` member. It was rejected deliberately:

- A **task is intent** — "call this lead on Friday". It is mutable, reschedulable,
  cancellable, and has an owner and a due date.
- An **activity is history** — "a call task was created / completed / rescheduled". It is
  append-only; the existing repository exposes no `update` or `delete` at all, and that
  absence is what enforces the audit trail.

Collapsing them gives you either a timeline you can rewrite (not an audit trail) or a
worklist you cannot edit (not a worklist). So tasks live in their own table, and **every**
lifecycle transition emits an immutable activity, in the same transaction.

Five new activity types were added rather than one `FOLLOW_UP` type with a metadata
discriminator, because "show me every task completed this week" must be an indexed query on
`activity_type`, not a JSONB scan:

`TASK_CREATED`, `TASK_COMPLETED`, `TASK_RESCHEDULED`, `TASK_CANCELLED`, `MEETING_SCHEDULED`.

Two existing types are also reused where the domain event is genuinely the existing one:

- Completing a **CALL** task writes **`PHONE_CALL`**, not `TASK_COMPLETED` — a call actually
  happened, and "every call we made" should be one filter.
- Reassignment writes the generic **`FOLLOW_UP`** — it is internal workload management, not
  an interaction with the lead, so it belongs on the timeline for accountability without
  earning its own filterable category.

## 4. Cancel vs. delete — a distinction the API enforces

These are different facts and are modelled as different operations:

| | Meaning | Timeline entry | Row |
|---|---|---|---|
| `PUT /followups/{id}/cancel` | "We decided not to do this" | `TASK_CANCELLED` | stays, `status=CANCELLED` |
| `DELETE /followups/{id}` | "This should never have existed" | **none** | soft-deleted |

A cancellation is a real fact about the lead — the sales team chose to stop pursuing
something — so it is recorded. A deletion is a correction of a mistake or a duplicate; it
writes nothing to the timeline, and the automatic audit-log listener still captures it,
which is the right level of detail for a data-entry fix.

## 5. "Overdue" without a scheduler — the decision that shaped the queries

The specification asks for an `OVERDUE` status **and** forbids background schedulers in this
phase. Taken naively those requirements conflict: nothing exists to sweep past-due `PENDING`
rows into `OVERDUE` on a timer, so a stored status alone would make the overdue list
permanently empty.

The resolution is that **overdue is a derived condition, OR-ed with the stored one**:

```python
or_(
    FollowUpTask.status == FollowUpStatus.OVERDUE,          # a future sweeper's output
    and_(FollowUpTask.status == FollowUpStatus.PENDING,     # true today, with no sweeper
         FollowUpTask.scheduled_at < now),
)
```

This is implemented once in `FollowUpTaskRepository._is_overdue_clause` and mirrored in
Python by `is_task_overdue()` for decorating a single serialized object with its `is_overdue`
flag. The consequences are worth stating plainly:

- The overdue list is **correct today**, with no scheduler running.
- When the scheduler lands it only has to flip the stored value. **No query changes.**
- A row's stored `status` may legitimately read `PENDING` while its `scheduled_at` is in the
  past. Every read path in the module accounts for that; nothing else should assume the
  stored status is the whole truth.

`is_overdue` is computed per response and never persisted — storing it would create a second
source of truth that goes stale the moment the clock moves.

## 6. Today / Upcoming / Overdue partition, they do not overlap

Three worklists that each return "work to do" invite double-counting. They are defined to
partition cleanly instead:

- **Today** — open tasks in `[start_of_today, tomorrow)`. Yesterday's task is *not* here.
- **Upcoming** — open tasks in `[tomorrow, tomorrow + days)`, default 7. Today's task is
  *not* here.
- **Overdue** — open tasks whose due time has passed.

All windows are **half-open**. A task due at exactly midnight belongs to exactly one day
rather than appearing at the end of one list and the start of the next. The test suite
asserts non-overlap directly rather than just asserting membership.

**A known limitation, stated rather than hidden:** day boundaries are computed in UTC, so a
team in IST sees "today" roll over at 05:30 local. Fixing it properly requires a configured
business timezone, which is a settings change beyond this phase; it is recorded in `task.md`
as a follow-up rather than papered over with a hardcoded offset.

## 7. The automation, as data

Four triggers were specified. They are expressed as a dictionary, not as branching, so the
whole policy is readable at a glance and a fifth trigger is a dictionary entry:

| Trigger | Task | Priority | Due in |
|---|---|---|---|
| reply "interested" | CALL | HIGH | 2h |
| reply "need details" | WHATSAPP | MEDIUM | 4h |
| status → NEGOTIATION | MEETING | URGENT | 24h |
| reply needs manual contact | CALL | HIGH | 1h |

The delays encode sales practice rather than round numbers: an "interested" reply gets a
2-hour window because responding in the same session is what converts; "need details" gets
4 hours because material has to be prepared; NEGOTIATION gets a next-day slot because it is
a scheduled conversation, not a callback.

Three routing decisions are load-bearing:

1. **`not_interested` creates nothing.** A lead who said no should not generate a task
   nagging someone to call them back.
2. **An *unclassified* reply routes to `manual_contact_required`.** This is the opposite
   case and easy to conflate with the first: an unrecognised or `None` `reply_type` means
   *nobody has read the message yet*, which is precisely when a human is needed. Defaulting
   to "no task" would let real replies fall silently on the floor.
3. **Automated tasks inherit the lead's owner.** An unowned lead produces an unassigned
   task, which surfaces on the unfiltered worklist for a manager to route — rather than
   being invented onto an arbitrary employee.

De-duplication is scoped to *open* tasks of the same type: a lead replying three times in an
afternoon ends up with one call task, but a genuine new follow-up after the previous one was
completed does get created. The suite asserts both halves.

### The NEGOTIATION hook fires from two places, on purpose

`CampaignReplyService.record_reply` writes `lead.status` **directly on the ORM object** and
never goes through `LeadService.update_lead`. Hooking only `LeadService` would therefore mean
the single most valuable automated task silently never fires for the most common way a lead
reaches negotiation — an "interested" reply. So both paths call
`on_lead_status_changed`, and the open-task de-duplication is what keeps that safe.

## 8. The bug this phase actually caught

The automation contract is: *a follow-up failure must never cost us the event that triggered
it.* A provider webhook cannot be replayed; losing a recorded reply because a secondary
convenience feature raised would be strictly worse than having no automation.

The first implementation did the obvious thing — wrapped the work in `try/except Exception`,
logged, returned `None`. The test asserting that contract failed, and the failure was
instructive: **catching the exception is necessary but not sufficient.**

A database-level error (here, an FK violation) poisons the entire SQLAlchemy session. The
transaction enters an aborted state, and the *caller's* subsequent `db.commit()` fails with
`PendingRollbackError` — even though the automation returned quietly. Verified directly:

```
returned: None
caller commit BROKEN: PendingRollbackError
```

The swallow defeated itself: the reply it was written to protect was lost anyway.

The fix is a **SAVEPOINT**. The task write runs inside `async with db.begin_nested()`, so a
failure rolls back only the automation's own work and leaves the enclosing transaction clean
and committable:

```
returned: None
caller commit after swallowed failure: OK -- contract holds
```

The test was then strengthened to assert *both* halves — that the call returns `None`, **and**
that the caller can still commit real work afterwards. A bare `try/except` passes the first
and fails the second, which is exactly the regression worth guarding.

## 9. Transaction boundaries

Every lifecycle operation commits its task change and its timeline entry **together**:

```python
await self.repository.update(db, db_obj=task, update_data=..., commit=False)
await self._log_task_completed(db, task, remarks)
await db.commit()
```

A completed task always has a matching `TASK_COMPLETED`/`PHONE_CALL` entry; the two can never
disagree. The automation hooks are called with `commit=False` from `record_reply` so the task
joins the same transaction as the reply itself, and with `commit=True` from `update_lead`
where the repository has already committed the lead.

## 10. Two rules enforced in the repository, not the service

Both must hold for *every* caller of *every* query, so they live below the service layer:

1. **A task belonging to a soft-deleted lead is never returned.** Soft-deleting a lead does
   not cascade to its tasks (the FK cascade only fires on a hard delete), so without an
   explicit join a deleted lead would keep pushing work onto someone's list forever. Every
   read joins `Lead` and filters `is_deleted == False`. The suite asserts a task vanishes
   from the worklist the moment its lead is deleted.

2. **Statistics are composed from the same filtered helpers as the lists.** A dashboard that
   disagrees with the list it links to is worse than no dashboard, so `count_where` and
   `count_grouped_by` inherit the identical exclusions rather than hand-writing COUNT
   queries.

`get_by_id` is the deliberate exception — it does *not* join `Lead`, so an individual task
stays fetchable and deletable even after its lead was soft-deleted. The visibility rule is
about worklists ("what should I work on"), not about direct addressing of a known row.

## 11. Route ordering

`/followups/today`, `/upcoming`, `/overdue` and `/statistics` are declared **before**
`/followups/{id}`. FastAPI matches in declaration order, so with the parameterised route
first, `/followups/today` would bind `id="today"` and 422 on UUID validation. Same hazard
`lead_imports.py` documents for `/leads/import`, solved the same way. Verified against the
live route table.

## 12. RBAC

New `followups:*` permissions rather than reuse of `leads:*`. Working a follow-up queue and
editing lead records are different capabilities: a junior caller should be able to complete
their own tasks without being able to rewrite lead data.

- **Manager** — `followups:*`
- **Reception** — view/create/update, but **not** delete (deleting erases a planned
  commitment; that stays with Manager)
- **Viewer** — inherits `followups:view` through the existing `*:view` wildcard
- **Designer/Editor/production roles** — no access

## 13. Verification results

`tests/test_followups.py` — **15/15 sections pass**, covering CRUD + validation, assignment
(including inactive-employee rejection), completion, rescheduling, cancellation, activity
emission for every transition, the three worklists and their non-overlap, soft-deleted-lead
isolation, all four automation triggers plus de-duplication and the savepoint contract,
statistics, optimistic locking, and RBAC.

Full regression sweep — **all 13 pre-existing suites pass**: `test_whatsapp`, `test_leads`,
`test_lead_activities`, `test_audit`, `test_auth`, `test_permissions`, `test_roles`,
`test_dashboard`, `test_search`, `test_inventory`, `test_lead_import`,
`test_google_maps_import`, `test_instagram_import`.

`test_erp.py`, `test_production.py` and `test_delivery_payment.py` fail on the **pre-existing**
soft-deleted `Photographer` fixture (`ab3dd978-...`) documented in all six previous phases —
re-confirmed identical here, and none of the three touches the follow-up path.

## 14. Isolation check

Files created: 5 (model, repository, service, schemas, endpoints) + 1 migration + 1 test.

Files modified, and the entirety of what changed in each:

| File | Change |
|---|---|
| `app/models/lead_activity.py` | +5 `ActivityType` members |
| `app/models/__init__.py` | register the new model |
| `app/services/lead.py` | +1 automation call in `update_lead`, +1 lazy import |
| `app/services/whatsapp.py` | +2 automation calls in `record_reply`, +1 lazy import, +1 return key |
| `app/api/deps.py` | +2 DI providers |
| `app/api/v1/router.py` | register the router |
| `scripts/seed_roles.py` | +5 permissions, +2 role grants |

Orders, Inventory, Production, Billing, Delivery, Payments and Authentication were not
touched. Both automation hooks use lazy imports inside `__init__` to avoid closing an import
cycle, matching the deferred-import pattern already used elsewhere in the codebase.

---

# WhatsApp Cloud API Provider — Walkthrough

## 1. Objective

Replace the NoOp WhatsApp provider with a production-ready Meta WhatsApp Cloud API
implementation that plugs into the existing `WhatsAppProvider` port.

Scope was strictly the provider and its inbound webhook. Lead Management, the Follow-up
engine, ERP modules, Orders, Inventory, Authentication and RBAC are untouched. The campaign
service was **not** modified at all — no campaign business logic moved into the provider,
and `WhatsAppCampaignService.start_campaign` is byte-for-byte the code that shipped last
phase. The only edits outside the two new files are additive: settings, three new methods on
the port, one webhook-routing service, and three routes.

## 2. What was built

| Layer | File | Role |
|---|---|---|
| Config | `app/core/config.py` | **+14 settings** — credentials, Graph version, retry budget, webhook secrets |
| Port | `app/services/whatsapp_provider.py` | **+3 methods** (`send_template`, `get_message_status`, `validate_configuration`), 2 result DTOs, settings-driven factory |
| **Adapter** | `app/services/whatsapp_cloud.py` | **New.** `WhatsAppCloudProvider` + `MetaWebhookVerifier` + `MetaWebhookParser` |
| Service | `app/services/whatsapp.py` | **+`MetaWebhookService`** — routes parsed events into the *existing* pipeline |
| Endpoints | `app/api/v1/endpoints/whatsapp.py` | **+3 routes** — `GET/POST /webhook/meta`, `GET /provider/status` |
| DI | `app/api/deps.py` | **+1 provider** (`get_meta_webhook_service`) |
| Tests | `tests/test_whatsapp_cloud.py` | 11-section suite, Graph API fully mocked |

No migration. No model change. The schema was already provider-neutral — `provider_message_id`
is an opaque string, and that was the whole point of designing it that way.

## 3. The collision at the centre of this phase: rendered strings vs. Meta templates

The port hands every adapter a **fully-rendered string**. That contract exists because it is
the only one Meta, Twilio, Interakt and AiSensy can all satisfy (see the port's docstring).

Meta cannot honour it for campaign messaging. Free-form text is permitted **only** inside a
24-hour customer service window opened by the *user* messaging *us* first. A cold outreach
campaign is by definition outside that window, so a free-text send to a lead who has never
written to us is rejected with error 131047 — every recipient, every time. Business-initiated
messaging must be a **pre-registered, Meta-approved template**, identified by name and
language, with positional parameters.

Three options were considered:

1. **Widen the port** to carry template IDs and component arrays. Rejected: it makes the port
   Meta-shaped, which defeats its purpose and breaks the other three vendors.
2. **Move rendering into the adapter.** Rejected: rendering is campaign business logic and
   the specification forbids moving it into the provider.
3. **Use what the port already passes.** Chosen.

The port already forwards `template_name` and `language` alongside the rendered text —
originally added "for vendors that require a pre-registered template identifier". This is that
vendor. The adapter sends the CRM template's **name** and **language** as the Meta template,
and supplies the **rendered body** as its single positional parameter.

The consequence is a real operational requirement, and it is not hidden: **a CRM template's
`name` must match a template registered and approved in Meta Business Manager.** That coupling
is Meta's model, not a design choice. `WHATSAPP_USE_TEMPLATES=false` switches to free text for
the service-window case.

## 4. The retry policy is the part that would have hurt in production

The naive implementation retries every failure. That is actively harmful here, and the
distinction is the most consequential decision in the adapter:

| Failure | Retried? | Why |
|---|---|---|
| 429 rate limit | **Yes**, honouring `Retry-After` | The limiter clears; Meta knows how long better than a constant does |
| Network timeout / connection reset | **Yes** | The request may never have arrived |
| 5xx provider unavailable | **Yes** | Transient by definition |
| **Expired / invalid token** (190, 102) | **No** | Still expired in two seconds. Retrying once per recipient turns a five-minute credential rotation into a rate-limit storm against Meta — 5,000 recipients × 3 retries = 15,000 doomed calls |
| **Invalid template** (132xxx, 131047) | **No** | No amount of resending creates a template that does not exist |
| **Bad recipient** (131026) | **No** | Permanent for that lead, irrelevant to every other one |
| **2xx with no message id** | **No** | Meta accepted *something*; resending risks a duplicate message to a real person |

`classify_graph_error` is a **pure function** of `(payload, http_status)`, which is what makes
every row above assertable without a network. The test suite asserts not just the returned
result but the **call count** — that an expired token was called exactly once and a 429 exactly
twice. A result-only assertion passes even when the retry policy is inverted.

Classification is code-first, HTTP-status-second: Meta returns **400 for both** "your token
expired" (never retry) and "you are being rate limited" (do retry), and only the error code
tells them apart.

## 5. The no-raise contract, and why `except Exception` is correct here

The port forbids raising for a per-message rejection. With the NoOp provider that was free;
with a real network it is load-bearing. `send_message` ends with a blanket
`except Exception` that logs a traceback and returns `success=False`.

That is not a swallowed bug. The campaign loop dispatches thousands of recipients
sequentially, and an unforeseen fault on recipient 400 must cost **that one recipient**, not
the 4,600 behind it. The campaign service already catches per recipient — this is defence in
depth, and it means a bug in *this adapter* degrades one row rather than aborting a run.

Every local failure is caught before the network too: an unusable phone number and an empty
body are both refused **without a call**, so Meta is never asked to reject what we can reject
ourselves.

## 6. Phone normalisation — small function, high blast radius

Meta requires E.164 **without** the `+`. The CRM's leads are Indian and stored three ways:
`9847012345`, `09847012345`, `+91 98470 12345`. All three must reach Meta as `919847012345`
or every send fails as an invalid recipient.

The rule that matters most is the one for numbers we should **not** touch: a number that is
already 11–15 digits and does not start with the configured country code is left alone. It is
almost certainly a foreign number that is already qualified, and prepending `91` would
silently **misroute the message to a stranger**. Getting this wrong is worse than failing —
it delivers a marketing message to an uninvolved person.

`WHATSAPP_DEFAULT_COUNTRY_CODE` is configurable rather than hardcoded to `91`, so the CRM's
first non-Indian client is a config change.

## 7. Webhook security — the endpoint that cannot present a JWT

The previous phase left the reply webhook behind `whatsapp:update` and documented why:
"an unauthenticated webhook with no signature check would let anyone on the internet rewrite
lead statuses." Meta cannot present a JWT, so this phase supplies the missing half.

Two mechanisms, for Meta's two request types:

- **GET handshake** — `hub.verify_token` must equal `WHATSAPP_VERIFY_TOKEN`; the endpoint then
  echoes `hub.challenge` as **plain text**. Returning JSON fails the handshake, since Meta
  compares the raw body — which is why the route builds its own `Response` rather than letting
  FastAPI serialise a string into `"1158201444"` with quotes.
- **POST delivery** — `X-Hub-Signature-256` carries an HMAC-SHA256 of the **raw body**, keyed
  by the Meta **app secret** (a different credential from the access token).

Three decisions here are load-bearing:

1. **The endpoint reads `await request.body()` and parses the JSON itself.** It does not
   declare a Pydantic body model. The signature covers the exact bytes Meta sent, and letting
   FastAPI parse-then-re-serialise produces *different bytes* whose signature would never
   match. This is the single easiest way to get webhook verification subtly, permanently wrong.
2. **Both comparisons use `hmac.compare_digest`**, not `==`, so a timing side channel cannot
   be used to forge a signature byte by byte.
3. **Everything fails closed.** An unset verify token rejects the handshake; an unset app
   secret rejects every POST. The alternative — accepting when unconfigured — is exactly the
   unauthenticated write path into lead statuses the previous phase refused to ship.

`WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE=false` exists so a developer can replay a captured payload
with curl. It logs a warning every time it is used, and `validate_configuration()` reports it
as a warning so it cannot quietly survive into production.

## 8. No duplicate business logic — `MetaWebhookService` is a router, not a second implementation

This is the requirement most at risk of being violated by accident, so it was designed against
explicitly. `MetaWebhookService.process` does exactly one thing: take parsed events and call
the services that already exist.

- A status event → `WhatsAppCampaignService.apply_delivery_status` — the *same* method the
  internal webhook calls.
- A reply → `CampaignReplyService.record_reply` — likewise.

Every rule stays where it was: monotonic status transitions, the reply → lead-status mapping,
timeline entries, `last_contacted_at`, follow-up automation, counter recomputation. None of it
is reimplemented, and none of it is imported into the adapter.

The test proves this rather than asserting it in a comment: it drives a `delivered`, then a
`read`, then a **replayed `delivered`** through the Meta path and asserts the recipient stays
`READ`. That monotonic guard lives in `apply_delivery_status`. If the Meta path had its own
status logic, the replay would regress the row and the test would fail.

The **one** decision this layer genuinely adds is `_classify_reply`, which derives a
`reply_type` from raw text since Meta delivers no classification. It is deliberately crude and
deliberately returns `None` when unsure — because the downstream mapping moves a lead to
**LOST** on `not_interested`, and a wrong guess there silently writes off a live lead that
nobody will ever go looking for.

## 9. Parsing Meta's payload — paranoid on purpose

Meta's webhook is deeply nested and batched: `entry[] → changes[] → value → {statuses[],
messages[]}`. One POST may carry statuses for several messages and replies from several people.

The parser is defensive past the point of looking excessive, and for a specific reason: **a
webhook that raises is a webhook Meta retries** — with escalating backoff, and eventually by
disabling the subscription entirely. One malformed entry must never cost the delivery.

**This is not theoretical — the test suite caught exactly this bug.** The first implementation
used `(entry or {}).get("changes")`, which guards `None` but lets a *string* straight through
to the next `.get()`, raising `AttributeError`. The malformed-payload test found it, and the
fix was a type-checking `_as_dict()` helper applied at every nested access. A test that only
fed well-formed payloads would have shipped it.

Two mapping decisions are worth naming:

- **`deleted` is ignored.** A user deleting a message on their device is not a delivery
  outcome, and mapping it to anything would corrupt the funnel.
- **Media replies are recorded, not dropped.** A lead answering a campaign with a voice note
  has *replied*. Recording `[audio message]` is far more useful than a timeline showing that
  nothing happened. Button taps and interactive list replies likewise become replies, because
  a lead tapping "Interested" means the same thing as typing it.

## 10. Configuration — nothing hardcoded, and misconfiguration is discoverable

All 14 settings read from the environment; no token, secret or URL is in code. Two choices
beyond that:

- **`WHATSAPP_PROVIDER` defaults to `noop`.** Merging a working Meta adapter does not by
  itself start sending real messages to real leads — an operator opts in explicitly. The
  reverse default would make a deployment start messaging on upgrade.
- **`validate_configuration()` is offline and names variables individually.** It separates
  *send-critical* credentials (missing → invalid) from *partial-capability* ones (missing →
  warning), because a deployment that only sends outbound and never receives webhooks is
  legitimate and should not report as broken.

`GET /whatsapp/provider/status` surfaces this, so an operator finds a missing credential
**before** launching a campaign rather than from 5,000 failed recipient rows. It returns which
variables are unset by name and never their values.

## 11. Verification results

`tests/test_whatsapp_cloud.py` — 11 sections, all passing. The Graph API is mocked end to end
via `httpx.MockTransport`; **no real WhatsApp account, token or phone number is required.**
The stub is injected by subclassing and overriding only `_import_httpx`, so payload
construction, the retry loop, error classification, normalisation and the no-raise contract
all run as production code — the stub replaces the socket and nothing else. This is the same
seam `tests/test_instagram_import.py` uses.

Covered: configuration validation · message sending · template sending · status mapping ·
webhook verification · reply handling · provider failures — every item the specification lists,
plus phone normalisation, campaign execution through the real provider, per-recipient failure
isolation, and provider registry selection.

Full regression sweep: **15/15 non-ERP suites pass**, including the pre-existing
`tests/test_whatsapp.py` — which matters most, since it proves the campaign module still
behaves identically with the port extended. The 3 ERP suites fail on the documented,
pre-existing `Photographer` fixture; this was confirmed by stashing all changes and observing
the identical failure on the untouched tree.

## 12. Isolation check

Lead Management, Follow-ups, Orders, Inventory, Production, Billing, Authentication and RBAC
were **not** modified. The campaign services were not modified except for the additive
`MetaWebhookService`; `start_campaign`, `apply_delivery_status` and `record_reply` are
unchanged. No model, no migration, no schema change — the recipient row's opaque
`provider_message_id` absorbed a real vendor without a single column being added, which is the
property the module was designed for and is now demonstrated.

## 13. Known gaps / follow-ups for a later phase

1. **A retried timeout can duplicate a message.** Meta's `/messages` endpoint offers **no
   idempotency key**, so a request that timed out after Meta processed it is indistinguishable
   from one that never arrived. Retrying accepts a small duplicate-send risk in exchange for
   recovering from genuine transient faults. Mitigations are bounded retries (default 2) and
   never retrying a 2xx-without-id. The real fix is a client-side dedupe window keyed by
   (recipient, template, minute) — worth adding before high-volume sending.

2. **Dispatch is still synchronous inside the HTTP request.** Unchanged from the previous
   phase, but the constraint now bites: real Meta latency is ~100–300ms per message, so a
   1,000-lead campaign is a multi-minute request. Retry backoff is capped at 30s for exactly
   this reason. **A task queue is the single most valuable next addition**; the port is already
   async, so moving the loop into a worker needs no interface change.

3. **Rate limiting is reactive, not proactive.** The adapter retries a 429 rather than pacing
   sends beneath Meta's tier limit. A token-bucket throttle in the campaign loop would be
   strictly better and belongs with the task queue.

4. **`reply_type` classification is keyword-based.** It returns `None` when unsure, which is
   safe, but it will miss Malayalam/Hindi replies and anything phrased indirectly. The rules
   are data in one list, so replacing them with a model or a per-tenant configured vocabulary
   is contained.

5. **Template parameters are a single positional value.** The adapter passes the whole rendered
   body as `{{1}}`. A Meta template with three separate placeholders needs the CRM to know its
   parameter *structure*, which today it does not model. Supporting that means a
   `provider_template_name` + parameter-mapping column on `whatsapp_templates`, and is the
   first thing to add when a real template needs more than one variable.

6. **No template-catalogue sync.** `WHATSAPP_BUSINESS_ACCOUNT_ID` is read but only warned
   about; nothing lists or validates templates against Meta's registry. A CRM template whose
   name has no approved Meta counterpart fails at send time with 132001 rather than at save
   time. A `GET /templates/sync` reading the WABA's template list would catch it earlier.

7. **`get_message_status` returns `None` by design.** The Cloud API genuinely has no
   status-read endpoint — delivery state is push-only. Reconciling a missed webhook means
   re-requesting it in Meta's dashboard. Implemented explicitly rather than left inherited so
   the fact is stated where someone will look for it.

8. **The webhook has no replay/dedupe log.** Meta may deliver the same event twice. This is
   harmless today because both downstream paths are idempotent (the monotonic rank guard makes
   a repeated status a no-op), with one exception: a genuinely re-delivered *reply* appends a
   second timeline entry. Storing seen message ids with a short TTL would close it.


---

# Lead CRM Dashboard — Walkthrough

## 1. Objective

Build the Lead CRM Dashboard: the landing page for the project's pivot from a full Colour Lab
ERP to a Lead CRM focused on photographer acquisition. Eight sections — summary cards, recent
replies, today's follow-ups, recent imports, campaign summary, quick actions, four charts, and a
responsive layout — assembled entirely from **existing backend APIs**, with no change to backend
business logic.

The constraint is the interesting part. "Consume the existing APIs only" is easy when the API was
designed for the page; here it was not, and three of the eight sections have no endpoint that
answers their question directly. What follows is mostly about those three.

## 2. What was built

| Layer | File | Role |
|---|---|---|
| Types | `src/features/leads/types.ts` | Mirrors of the backend response schemas + derived view models |
| Services | `src/services/leads.ts` | Every HTTP call in the domain; nothing else touches axios |
| Hooks | `src/features/leads/hooks.ts` | All fan-out, joins, aggregation and mutations |
| Widgets | `src/features/leads/components/*.tsx` | Seven components, two of them shared primitives |
| Page | `src/features/leads/pages/LeadDashboardPage.tsx` | Composition + per-section RBAC |
| Tests | `src/tests/leadDashboard.test.tsx` | 62 tests across all four layers |

Two files outside the feature changed: `src/App.tsx` (index route + seven placeholder routes) and
`src/layouts/AppLayout.tsx` (sidebar repointed, active-route rule extracted).

## 3. The central problem: `GET /dashboard` is useless here

The obvious first move is to call the existing dashboard endpoint. It returns:

```
revenue_today, revenue_this_month, payments_today, pending_payments,
pending_deliveries, orders_ready, orders_delivered_today, invoices_generated,
invoices_pending, notifications_pending, notifications_failed, today_orders,
weekly_revenue, monthly_revenue, pending_production, delayed_orders,
top_products, top_customers, outstanding_balance, average_order_value
```

Every field is ERP. Not one is lead-related. `GET /dashboard` is the *Colour Lab ERP* dashboard,
and the Lead CRM dashboard shares nothing with it but a name.

So the eight summary cards had to be built from the lead endpoints directly — and `GET /leads`
returns rows, not aggregates. There is no status histogram anywhere in the API.

## 4. Counting without an aggregation endpoint

The trick is that `LeadListResponse.total` is computed **ignoring `skip`/`limit`**:

```python
items, total = await service.get_all_leads(db=db, skip=skip, limit=limit, status=status_filter, ...)
return LeadListResponse(items=items, total=total, skip=skip, limit=limit)
```

So `GET /leads?status=NEW&limit=1` returns one lead row and an accurate count of *all* NEW leads.
One row of payload buys the number. That is what `leadsService.count` does:

```ts
count: async (params = {}): Promise<number> => {
  const response = await api.get<Paginated<Lead>>('/leads', {
    params: { ...params, skip: 0, limit: 1 },
  });
  return response.data.total;
},
```

`useLeadSummary` then issues seven of these through `useQueries` — one unfiltered for Total, six
by status — which TanStack Query runs concurrently. Seven small parallel requests, accurate at any
table size.

The rejected alternative was fetching 500 leads once and tallying client-side: one request, but
**silently wrong past 500 rows**, and silently-wrong is the worst failure mode for a number
someone makes decisions from.

The eighth counter, "Follow-up Today", comes from `GET /followups/statistics.due_today` instead —
open *tasks* due today, not *leads* in `FOLLOW_UP` status. Those are genuinely different
questions, and the card carries a "Tasks due today" footer so the distinction is visible rather
than implied.

## 5. Recent Replies — the section with no endpoint

Reply text lives on the campaign recipient row:

```python
class CampaignRecipientResponse(BaseModel):
    lead_id: uuid.UUID
    phone: str
    message_status: MessageStatus
    reply_text: str | None
    replied_at: datetime | None
```

and the only route that returns those rows is `GET /whatsapp/campaigns/{id}/recipients` — scoped
to **one campaign**. There is no cross-campaign replies endpoint. "The latest replies from
WhatsApp", as a question, cannot be asked of this API in one request.

With backend changes out of scope, `useRecentReplies` reconstructs it:

1. `GET /whatsapp/campaigns?limit=5` — the five newest campaigns.
2. For each, `GET /whatsapp/campaigns/{id}/recipients?message_status=REPLIED`.
3. Join each recipient to its lead for the business name and current status.
4. Flatten, sort by `replied_at` descending, truncate to eight.

Two details in step 3 and 4 matter.

**Lead resolution reuses a shared cached query.** Replies, today's follow-ups and the campaign
summary all need to turn a `lead_id` into a business name. All three read from the same
`leadKeys.sample()` query, so the common case costs **one** lead request for the whole page, not
three. When a lead falls outside that sample the row degrades rather than disappearing — the reply
shows the phone number instead of "Unknown", the follow-up falls back to the task title.

**Rows with no timestamp sort last, not first.** The naive comparator sends `null` to the top:

```ts
const aTime = a.repliedAt ? dayjs(a.repliedAt).valueOf() : 0;
const bTime = b.repliedAt ? dayjs(b.repliedAt).valueOf() : 0;
return bTime - aTime;
```

Coercing a missing timestamp to `0` in a descending sort puts it at the bottom, which is where an
undated reply belongs on a "most recent" list.

**Cost:** at most six requests for this section, and replies from leads not enrolled in a recent
campaign never appear. A `GET /whatsapp/replies/recent` joining recipients to leads would collapse
the whole thing into one query, and is the single most valuable backend addition for this page.

## 6. The loading / empty / error triad, decided once

Every section on the dashboard needs three non-content states. Six sections implementing that
independently is six chances to get the precedence wrong, and the wrong precedence is genuinely
misleading:

- **Error hidden behind a skeleton** reads as a request that never finishes.
- **Empty claimed while loading** reads as "you have no leads" when the answer is "not yet known".
- **Eight zeroed cards on a failed fetch** reads as an empty CRM rather than a broken connection.

`DashboardSection` resolves it once — `error > loading > empty > content` — and every section
passes flags instead of branching:

```tsx
if (isError)   return <ErrorState … />;
if (isLoading) return <skeleton rows />;
if (isEmpty)   return <EmptyState … />;
return children;
```

`LeadSummaryCards` doesn't use the wrapper (it is a grid, not a card) but follows the same rule,
which is why its error state *replaces* the grid rather than rendering beside it. Four tests pin
the precedence directly, because it is the kind of ordering that a later refactor silently
inverts.

## 7. Two shared widgets, to avoid six copies of the same thing

**`DashboardSection`** — the card shell + the state triad above. Used by five sections and all
four charts.

**`LeadStatusBadge`** — the existing shared `StatusBadge` maps only generic statuses (`pending`,
`completed`, `failed`…). Every CRM status — `MESSAGE_SENT`, `NEGOTIATION`, `PARTIAL`, `DRAFT` —
would fall through to the default variant and render identically. `LeadStatusBadge` supplies the
domain's colour semantics (progress green, engagement blue, attention amber, dead ends red) while
still delegating rendering to the shared `Badge`, and `humanizeStatus` turns `MESSAGE_SENT` into
"Message Sent" for display.

Both are the difference between "use the existing component library" and "reimplement it".

## 8. The follow-up actions, and the per-row busy state

Complete and Reschedule are the only writes on the page. Two decisions:

**Both mutations invalidate the statistics query, not just the worklist.** "Follow-up Today" on the
summary cards is derived from `GET /followups/statistics.due_today`. Completing a task without
invalidating that query leaves the card showing the pre-completion number — the list updates, the
counter above it does not, and they visibly disagree.

**Busy state is tracked per task id, not as a boolean.** `pendingTaskId` means completing one
follow-up spins that row's button only; a shared `isPending` would disable every row's buttons at
once. A test asserts exactly this by rendering two tasks and checking only the first is disabled.

The reschedule dialog validates before calling anything — a past datetime shows an inline error
and the mutation never fires — and converts the browser's zone-less `datetime-local` value to an
ISO string, because the API rejects a naive datetime:

```python
@field_validator("scheduled_at")
def scheduled_at_must_be_aware(cls, v: datetime) -> datetime:
    return _require_aware(v, "scheduled_at")
```

## 9. RBAC is per-section, not per-page

Wrapping the whole dashboard in one `leads:view` guard would be simpler and worse: an employee
with `leads:view` but not `whatsapp:view` would get a permission wall instead of the four sections
they are entitled to. Each section is gated on the permission its *data* requires —
`canViewLeads`, `canViewFollowUps`, `canViewWhatsApp` — and `canUpdateFollowUps` separately
controls whether the Complete/Reschedule buttons render at all.

`QuickActions` gates each tile individually and returns `null` when none survive, so a viewer-role
employee sees no empty action strip. Hiding beats disabling here: a greyed-out "Import Leads" tile
tells that user nothing actionable.

All of it goes through the existing `checkPermission` — the same wildcard matcher the router and
sidebar use — so the semantics cannot drift from the backend's `RequirePermission`.

## 10. A bug introduced and caught while repointing the sidebar

The new Lead CRM nav has both `/leads` and `/leads/import`. The existing active-route rule was:

```ts
const isActive = item.path === '/' ? location.pathname === '/'
                                    : location.pathname.startsWith(item.path);
```

On `/leads/import` that highlights **both** entries, because `/leads` is a prefix of
`/leads/import`. The old ERP nav had no nested paths, so the bug had nothing to expose it.

`isNavItemActive` replaces it: an item stays active for its own sub-routes (`/leads/abc-123` keeps
"Leads" lit) but yields when a longer *declared nav path* is the better match. It also fixes a
latent prefix bug — `startsWith('/leads')` matches `/leadsomething`, which segment-aware matching
does not. Extracted to module scope so the desktop and mobile navs share one rule instead of two
copies, and covered by four tests.

## 11. Pre-existing breakage, found by the verification requirement

The phase requires `npm test` to pass and `npm run build` to succeed. Both were **already failing
on a clean tree before any of this work**:

```
src/features/orders/components/AddItemDialog.tsx(96,16): error TS2741: Property 'products' is missing…
src/features/orders/components/OrderItemEditor.tsx(45,49): error TS6133: 'products' is declared but never read
src/features/orders/components/OrderItemEditor.tsx(113,16): error TS2741: Property 'products' is missing…

Test Files  1 failed | 8 passed (9)
```

One root cause: `ProductSelector` takes a required `products` prop, and two callers never passed
it — even though both already receive `products` in their own props. `useMemo(() => …products.map…)`
then threw on `undefined`.

The fix is two one-line prop forwards. It is ERP code and outside this phase's scope, touched only
because the verification criteria could not be met otherwise — recorded here and in `task.md`
rather than folded in quietly.

## 12. Verification results

```
npm run build   ✓ tsc clean, built in 4.88s
                  dist/assets/index-A9QRPdHF.js   1,142.57 kB │ gzip: 335.22 kB

npm test        ✓ 10 files, 191 tests passed
                  src/tests/leadDashboard.test.tsx  62 passed   ← new
                  src/tests/orders.test.tsx         14 passed   ← was failing before this phase
                  (8 pre-existing suites unchanged)
```

The 62 new tests are organised by layer:

- **Services (9)** — that the right URLs and params go out. The `limit=1` count probe and the
  `message_status=REPLIED` recipient filter are both asserted explicitly, since they are the two
  places the page's cost model lives.
- **Hooks (13)** — the real complexity. Each summary counter is given a *distinct* total so the
  test proves all eight are wired to different probes rather than all reading one query by
  accident; the replies fan-out is checked for cross-campaign merge order and phone fallback; the
  growth series is checked for zero-filled quiet days.
- **Widgets (34)** — the state triad and its precedence, plus rendering and actions.
- **RBAC + helpers (6)** — permission gating, wildcards, and the nav-matching fix from §10.

`recharts` is stubbed in the suite: it measures its container, which jsdom reports as 0×0, so the
real components render nothing and warn. The chart *data* is verified through `useLeadCharts`
instead, which is where it is actually computed — testing the aggregation rather than the SVG.

## 13. Isolation check

No file under `app/` was modified. No endpoint, service, repository, model, schema or migration
was touched. `git status` on the backend tree is unchanged by this phase.

Frontend files outside `src/features/leads/` that changed: `src/App.tsx` (routes),
`src/layouts/AppLayout.tsx` (nav + `isNavItemActive`), and the two ERP one-line prop fixes in §11.

## 14. Known gaps / follow-ups for a later phase

1. **Lead Sources and Daily Lead Growth describe a 500-lead sample.** `GET /leads` caps `limit` at
   500 and offers no aggregation, so both charts aggregate the most recent 500 leads. This is
   surfaced, not hidden: `useLeadCharts` returns `isSampled`, and both subtitles read "most recent
   500" when it is true. A `GET /leads/statistics` returning source and status histograms would fix
   it properly *and* collapse §4's seven requests into one.

2. **Recent Replies needs a backend endpoint** (§5). Up to six requests, and it structurally cannot
   show replies from leads outside a recent campaign. Highest-value addition for this page.

3. **Lead names resolve from one cached 500-lead sample.** Cheap (one request serves three
   sections) and it degrades gracefully, but leads outside the sample are not named. An `ids`
   filter on `GET /leads` would close it.

4. **Employee names come from an unpaginated `GET /employees`** capped at 200. A larger org needs
   the assignee name denormalised onto `FollowUpTaskResponse`, or an `ids` filter.

5. **"Interested Leads" per campaign is present-tense.** It intersects recipients with leads
   *currently* in `INTERESTED` status, so it reflects status now, not at send time. Stated in the
   column tooltip. A real attribution figure needs the status transition recorded against the
   campaign.

6. **Link destinations are placeholders.** Seven Lead CRM routes exist as permission-guarded stubs
   so nothing 404s; building them out is the next phase.

7. **No auto-refresh.** Fetch-on-mount plus explicit Refresh only. A reply arriving while the page
   is open is not shown until refresh — a `refetchInterval` on the replies and follow-ups queries
   is the cheap fix.

8. **The bundle is 1.14 MB (335 KB gzipped)** and still ships the ERP feature code. Route-level
   `React.lazy` splitting is the fix.

9. **`npm run lint` cannot run** — `eslint` is absent from `node_modules` despite the script
   existing in `package.json`. Typechecking is covered by `tsc` inside `npm run build`.

---

# Lead Details Workspace — Walkthrough

## 1. Objective

Build the Lead Details page — the primary workspace for managing one lead — on the existing
backend API, without touching backend business logic and without building any ERP functionality.

Eight sections were specified: Lead Profile, Activity Timeline, Notes, Follow-ups, WhatsApp
History, Quick Actions, Status Panel, and the layout/RBAC rules that hold them together.

## 2. What was built

| File | Role |
|---|---|
| `src/features/leads/types.ts` | Extended with `LeadActivity`, `LeadNote`, `ActivityType`, `LeadUpdatePayload`, `FollowUpCreatePayload`, `FollowUpCancelPayload`, `LeadWhatsAppHistoryEntry`, and `last_contacted_at` on `Lead` |
| `src/services/leads.ts` | Extended with `leadActivitiesService`, `leadNotesService`, `leadsService.update`, and four follow-up methods (`listByLead`, `create`, `cancel`) |
| `src/features/leads/detailHooks.ts` | **New.** All 14 detail hooks — profile, timeline paging, notes CRUD, follow-up lifecycle, WhatsApp fan-out |
| `src/features/leads/utils.ts` | **New.** Pure derivations: Maps URL, `tel:`/`wa.me`/`mailto:` links, address assembly |
| `src/features/leads/components/LeadProfileCard.tsx` | **New.** All 18 specified profile fields |
| `src/features/leads/components/LeadActivityTimeline.tsx` | **New.** Icon/colour mapping + Load More |
| `src/features/leads/components/LeadNotesSection.tsx` | **New.** Add / edit / delete with author + timestamp |
| `src/features/leads/components/LeadFollowUpsSection.tsx` | **New.** Complete / cancel / reschedule, overdue highlighting |
| `src/features/leads/components/LeadWhatsAppHistory.tsx` | **New.** Campaign history with the four delivery milestones |
| `src/features/leads/components/LeadQuickActions.tsx` | **New.** The seven specified actions |
| `src/features/leads/components/LeadStatusPanel.tsx` | **New.** Status change behind a confirmation |
| `src/features/leads/components/EditLeadDialog.tsx` | **New.** Diff-based lead edit form |
| `src/features/leads/components/CreateFollowUpDialog.tsx` | **New.** Follow-up creation form |
| `src/features/leads/pages/LeadDetailsPage.tsx` | **New.** Composition + per-section RBAC |
| `src/tests/leadDetails.test.tsx` | **New.** 76 tests |
| `app/schemas/lead.py` | **One line** — see §3 |

`RescheduleDialog` and `DashboardSection` were reused as-is from the dashboard phase, not
reimplemented. `DashboardSection` in particular already owned the loading/empty/error triad, so all
five sections inherited it for free.

## 3. The only backend change, and why it was necessary

The spec asks the profile to show **Last Contacted**. `Lead.last_contacted_at` already exists as a
column ([`app/models/lead.py:202`](app/models/lead.py#L202)) and is actively maintained by the
WhatsApp module — stamped on dispatch and on reply. But `LeadResponse` inherits `LeadBase`, which
does not declare it, so the value was never reaching the client.

The fix is a read-only field addition to the response schema:

```python
class LeadResponse(LeadBase):
    id: uuid.UUID
    is_converted: bool
    last_contacted_at: datetime | None = Field(None, ...)   # ← added
    version: int
```

It sits on `LeadResponse` and **not** on `LeadBase`/`LeadCreate`/`LeadUpdate` deliberately: the
column is server-maintained, and putting it on the base would have made it client-writable — which
would let a caller forge contact history. No service, repository, endpoint or migration changed;
the column and its data already existed.

The alternative considered was deriving "last contacted" from the newest WhatsApp activity in the
timeline. That was rejected because it is only an approximation (it misses contacts recorded before
the activity module, and reply-only contacts land differently) and it costs an extra query per
lead to reproduce a value the database already holds.

## 4. Two spec fields with no backend column

### Google Maps URL — derived, not stored

There is no `google_maps_url` column on `Lead`. The Google Maps import provider *does* compute one
([`google_maps.py:562`](app/services/lead_providers/google_maps.py#L562)), but
`LeadImportService` folds it into the lead's free-text `remarks`
([`lead_import.py:692`](app/services/lead_import.py#L692)) rather than storing it as a field.

`Lead` does carry `latitude`/`longitude`, so the link is derived client-side:

```ts
export const mapsUrlFor = (lead) => {
  const { latitude, longitude } = lead;
  if (latitude == null || longitude == null) return null;
  return `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`;
};
```

This lands exactly where it matters — Maps-sourced leads are the ones carrying coordinates. A
manually-entered lead without them returns `null` and the profile **hides the row** rather than
rendering a dead link. Adding a real column plus migration was the alternative; it was rejected as
a schema change the task explicitly discouraged, for a value that is reconstructible.

### WhatsApp history — a fan-out, because there is no lead-scoped route

`GET /whatsapp/campaigns/{id}/recipients` has no `lead_id` filter, and no
`/leads/{id}/whatsapp-history` route exists. Reply text and the four delivery timestamps live only
on the per-campaign recipient row.

So `useLeadWhatsAppHistory` fetches recent campaigns, fans out over their recipients, and keeps the
rows whose `lead_id` matches — the same bounded N+1 the dashboard's `useRecentReplies` already
established. It is capped by `LEAD_CAMPAIGN_HISTORY_LIMIT = 10`.

The important part is that the truncation is **stated, not hidden**: the hook returns `isSampled`
when `total > fetched`, and the section then renders "Covers this lead's most recent campaigns
only." Silently showing a partial history would read as *"this lead was never messaged before
that"*, which is a different and false claim.

## 5. Load More accumulates pages; it does not replace them

`GET /leads/{id}/activities` pages with `skip`/`limit` and has no cursor. The naive
implementation — one query whose `skip` increases — would *replace* the visible list on each click
rather than growing it.

Instead `useLeadActivities` holds a `pageCount` and renders every page `0..n-1` through
`useQueries`, concatenating the results:

```ts
const pageQueries = useQueries({
  queries: Array.from({ length: pageCount }, (_, page) => ({
    queryKey: leadDetailKeys.activityPage(leadId, page * pageSize),
    queryFn: () => leadActivitiesService.list(leadId, { skip: page * pageSize, limit: pageSize }),
  })),
});
```

Three properties fall out of this that matter:

1. **Each page is its own cache entry**, so loading page 3 does not refetch pages 1 and 2.
2. **Invalidation still works.** Adding a note invalidates the `activities` prefix, which refreshes
   *all* loaded pages — the new NOTE entry appears at the top without collapsing the list back to
   one page.
3. **`hasMore` reads the envelope's `total`**, not "did the last page come back short". The UI
   never has to guess.

There is one hazard this creates, and it is handled explicitly: a new activity written *between*
two page fetches shifts every later row down by one, so the boundary row can arrive twice. The hook
de-duplicates by id before returning, which prevents both the visible duplicate and React's
duplicate-key warning. A test covers exactly this case.

## 6. Ten spec events, seventeen enum members

The spec names ten timeline events. The backend's `ActivityType` has seventeen members and uses
different identifiers for several of them:

| Spec wording | Backend enum |
|---|---|
| Lead Imported | `CREATED` |
| Note Added | `NOTE` |
| Follow-up Created | `TASK_CREATED` |
| Follow-up Completed | `TASK_COMPLETED` |
| Lead Updated | `UPDATED` |
| Status Changed | `STATUS_CHANGED` |
| WhatsApp Sent/Delivered/Read/Replied | `WHATSAPP_*` (1:1) |

`ACTIVITY_PRESENTATION` maps **all seventeen**, not just the ten. An unmapped type would otherwise
render as an unlabelled grey dot — so `TASK_RESCHEDULED`, `TASK_CANCELLED`, `MEETING_SCHEDULED`,
`PHONE_CALL`, `FOLLOW_UP`, `CONVERTED` and `DELETED` all get their own icon and colour too, and a
`FALLBACK_PRESENTATION` catches anything added to the backend later.

Colour semantics match the rest of the CRM: green for progress, blue for outbound engagement, amber
for attention-needed, red for dead ends, grey for bookkeeping.

## 7. Status changes are confirmed, and carry `version`

A status change is not a local UI preference. It writes a `STATUS_CHANGED` row to the **immutable**
activity timeline and moves the lead between the dashboard's pipeline counters. A mis-click on a
dropdown should not be able to do that, so the panel is two-step: pick, then confirm.

The update sends the lead's `version`:

```ts
updateStatus: (status, version) =>
  mutation.mutateAsync({ status, ...(version !== undefined ? { version } : {}) }),
```

`LeadUpdate.version` drives optimistic locking server-side. Omitting it would skip the check
entirely — so a status change issued from a page left open for an hour would silently clobber
whatever someone else did in the meantime. With it, that case returns 409 `VERSION_CONFLICT`, and
the panel says *"This lead was changed by someone else. Reload the page and try again."* rather
than failing silently. The dialog closes but the chosen status is retained.

### "Refresh all related queries after update"

The spec requires this, and the query-key design is what makes it one call rather than five.
Every detail key nests under a shared `detail(leadId)` prefix:

```ts
leadDetailKeys.detail(leadId)      // [..., 'detail', id]
leadDetailKeys.profile(leadId)     // [..., 'detail', id, 'profile']
leadDetailKeys.activities(leadId)  // [..., 'detail', id, 'activities']
leadDetailKeys.notes(leadId)       // [..., 'detail', id, 'notes']
leadDetailKeys.followUps(leadId)   // [..., 'detail', id, 'followups']
```

So `invalidateQueries({ queryKey: detail(leadId) })` refreshes profile, timeline, notes and
follow-ups together. `useUpdateLead` also invalidates the *dashboard's* `summary()` and `sample()`
keys, because a status change makes those per-status counters wrong too — a detail-page edit that
left the dashboard stale would be a real bug.

It additionally seeds the profile cache from the mutation response
(`setQueryData(profile(leadId), updated)`) so the page re-renders with the **new `version`**
immediately, rather than briefly holding a stale version that the next edit would 409 on.

## 8. The edit form sends a diff, not the form

`EditLeadDialog` submits only fields that actually changed, plus `version`:

```ts
TEXT_FIELDS.forEach((field) => {
  const next = form[field].trim();
  if (next === (lead[field] ?? '')) return;
  payload[field] = next === '' ? null : next;   // cleared → null, not ""
});
```

Two decisions here:

- **Clearing a field sends `null`, not `""`.** The columns are nullable and the backend's URL and
  email validators reject an empty string — `""` would 400 where the user meant "remove this".
- **A no-op save closes without a request.** If only `version` ends up in the payload, nothing
  changed; issuing the PUT anyway would still bump the version and needlessly invalidate everyone
  else's open page.

Sending the whole form instead would make every save a full overwrite, turning any concurrent edit
into silent data loss *even when the two edits touched different fields*.

**Status is deliberately absent from this form.** It belongs to the Status Panel, which confirms
first. Duplicating it here would create a second, unconfirmed path to the same timeline-writing
effect. `last_contacted_at` is absent too — it is not part of `LeadUpdate` at all.

## 9. A UI-library constraint that changed two forms

`Select` renders its `placeholder` as `<option value="" disabled hidden>`. That is correct for a
prompt, but it means **the empty value cannot be re-selected once something else is chosen**.

Both the "Assign to" field on `CreateFollowUpDialog` and "Assigned Employee" on `EditLeadDialog`
need *Unassigned* to be a real, re-selectable choice — the backend accepts an explicit null
assignee, and un-assigning is a legitimate operation. So in both, it is a genuine option rather
than the placeholder:

```ts
options={[
  { label: 'Unassigned', value: '' },
  ...employees.map(...),
]}
```

Using `placeholder` there would have produced a form where a task can be assigned but never
un-assigned — a bug that no type error would have caught.

## 10. Follow-up ordering, and the `is_overdue` subtlety

The backend orders follow-ups by due date then priority. That would bury a three-days-overdue task
below a *completed* one scheduled for tomorrow, so `useLeadFollowUps` re-sorts into worklist order:
overdue first (most overdue at top), then open by soonest, then closed by most recent.

Overdue-ness reads the server-computed `is_overdue` flag rather than comparing `scheduled_at` to
the clock locally — the backend ships no sweeper, so a row's stored `status` can still say
`PENDING` after its due time passed, and `is_overdue` is the only field telling the truth.

But `is_overdue` alone is not sufficient either. It can be `true` on a task whose status has since
moved to `COMPLETED`. So both the highlight and the count require **open *and* overdue**:

```ts
const overdue = task.is_overdue && isOpenTask(task);
```

Without that conjunction, a task completed two days late would show a red "Overdue" badge forever.
A test covers it.

Lifecycle actions render only on open tasks, because the backend rejects completing, cancelling or
rescheduling a closed one with a 400 — the buttons would be a guaranteed error.

## 11. RBAC: per-section and per-control, mirroring the endpoints

Gating matches what each endpoint actually enforces rather than being page-wide:

| Control | Permission | Because |
|---|---|---|
| Edit Lead, Status Panel, note composer, note edit/delete | `leads:update` | Notes reuse the lead permission set server-side — there are no `lead-notes:*` permissions |
| Follow-ups section | `followups:view` | |
| New follow-up | `followups:create` | |
| Complete / Cancel / Reschedule | `followups:update` | Working a queue ≠ editing lead records |
| WhatsApp History | `whatsapp:view` | |
| Send WhatsApp | `whatsapp:create` | |
| **Copy Phone, Open WhatsApp, Call Now** | **none** | They touch no API |

That last row is the deliberate one. Those three actions are pure client-side operations on data
already visible in the profile; gating them would restrict nothing while making the rail feel
broken. Everything that *does* hit an endpoint is gated on the permission that endpoint requires —
hiding it client-side mirrors the server, it does not replace it.

Sections are gated individually, following the dashboard's precedent: someone with `leads:view` but
not `followups:view` still gets a working profile, timeline and notes rather than a permission wall.
`EditLeadDialog` is not merely hidden but **unmounted** without `leads:update`.

### Send WhatsApp is a wa.me link, not an API call

There is no per-lead send endpoint. The backend dispatches WhatsApp per *campaign*
(`POST /whatsapp/campaigns/{id}/start`). So "Send WhatsApp" opens the lead's wa.me conversation
rather than pretending a one-off API send exists. It is still gated on `whatsapp:create`, because
sending a message is the action being taken regardless of the transport.

## 12. Verification results

```
npm run build   ✓ tsc clean, built in 5.10s
                  dist/assets/index-C-xeEr20.js   1,192.60 kB │ gzip: 348.01 kB

npm test        ✓ 11 files, 267 tests passed
                  src/tests/leadDetails.test.tsx    76 passed   ← new
                  src/tests/leadDashboard.test.tsx  62 passed
                  (9 pre-existing suites unchanged)
```

The 76 new tests, by the six areas the spec names plus the layers beneath them:

- **Utils (6)** — Maps URL derivation and its null cases, phone normalisation, `tel:`/`wa.me`
  divergence over the leading `+`, scheme-adding, address assembly with holes in it.
- **Services (6)** — that the right URLs, bodies and params go out. The two note roots
  (`/leads/{id}/notes` vs `/lead-notes/{id}`) are asserted explicitly, as is the *absence* of a
  status filter on the lead's follow-up list.
- **Hooks (9)** — page accumulation and the shift-duplicate case, follow-up ordering, the
  completed-but-late non-overdue case, the WhatsApp fan-out's lead filtering and `isSampled`.
- **Lead profile rendering (8)** — every field, the links, `last_contacted_at` in both states,
  omission of absent fields, the hidden Maps row.
- **Timeline (5)** — loading, all ten spec events mapped, Load More appearing/firing/disappearing.
- **Notes CRUD (9)** — create with trimming, blank rejection, edit prefill, edit cancel, delete
  behind confirmation, author fallback, composer reachable when empty.
- **Follow-up actions (8)** — complete and cancel behind confirmation, reschedule delegation,
  overdue highlighting present and absent, no actions on closed tasks.
- **Status updates (5)** — confirmation required, dismissal is a no-op, `version` sent, current
  status excluded from options, 409 surfaced as readable text.
- **RBAC (7)** — each control hidden without its permission and present with it, including the
  local-actions-stay-visible case.
- **WhatsApp history (4)** and **page integration (3)** — all sections present for a
  full-permission user, page-level error, sections omitted without their view permissions.

## 13. Isolation check

**No ERP functionality was built or modified.** Orders, Payments, Inventory, Production, Delivery,
Invoices and Photographers are untouched.

Backend: exactly one file changed — `app/schemas/lead.py`, one field on `LeadResponse` (§3). No
endpoint, service, repository, model or migration was modified. No business logic changed.

Frontend files changed outside the new ones: `src/App.tsx` (the `leads/:id` placeholder replaced
with the real page + its import) and `src/tests/leadDashboard.test.tsx` (one line — its `makeLead`
factory needed `last_contacted_at` to satisfy the widened `Lead` type; that compile error is the
type system doing its job).

## 14. Known gaps / follow-ups for a later phase

1. **WhatsApp history covers recent campaigns only** (§4). Bounded at 10 campaigns and surfaced via
   `isSampled`. A `lead_id` filter on `GET /whatsapp/campaigns/{id}/recipients`, or a
   `GET /leads/{id}/whatsapp-history` route, would make it complete *and* collapse the fan-out to
   one request. Highest-value backend addition for this page.

2. **Google Maps URL is derived from coordinates** (§4), so leads without lat/long show no link
   even when the importer captured a real Maps URL into `remarks`. A `google_maps_url` column
   populated from the provider's `source_url` would fix it properly.

3. **Author and assignee names come from an unpaginated `GET /employees`** capped at 200 — the same
   limitation the dashboard has. Denormalising the author name onto `LeadNoteResponse` and
   `FollowUpTaskResponse` would remove the dependency entirely.

4. **Timeline filtering by activity type is not exposed in the UI.** The service and endpoint both
   support `activity_type`, but no filter control was built; the spec asked for pagination, not
   filtering. It is a small addition when wanted.

5. **No follow-up *edit* or *assign*.** `PUT /followups/{id}` and `/assign` exist and are unused —
   the spec listed create/complete/cancel/reschedule only.

6. **No auto-refresh.** Fetch-on-mount plus the explicit Refresh button. A reply arriving while the
   page is open is not shown until refreshed.

7. **The bundle is now 1.19 MB (348 KB gzipped)**, up ~50 KB from this phase and still un-split.
   Route-level `React.lazy` remains the fix.

8. **`npm run lint` still cannot run** — `eslint` is absent from `node_modules` despite the script
   existing in `package.json`. Pre-existing and unrelated to this phase; typechecking is covered by
   `tsc` inside `npm run build`.

---

# Lead Pipeline (Kanban Board) — Walkthrough

## 1. Objective

Build the Lead Pipeline board at `/leads`: every lead in the CRM laid out as a column per status,
cards draggable between columns, with filters, sorting, per-column incremental loading, column
totals and per-card quick actions — on the existing backend API, reusing the existing component
library, with **no ERP functionality** touched.

## 2. What was built

| Layer | File | Role |
|---|---|---|
| Service | `src/services/leads.ts` | `leadPipelineService.column()` / `.moveToStatus()`, `followUpsService.pending()` |
| Utils | `src/features/leads/pipelineUtils.ts` | column list, 4 sort comparators, drop predicate, filter helpers |
| Hooks | `src/features/leads/pipelineHooks.ts` | board fetching, optimistic move + rollback, DnD state machine, card actions |
| Components | `PipelineColumn`, `PipelineCard`, `PipelineFiltersBar`, `AddNoteDialog` | presentation only |
| Page | `src/features/leads/pages/LeadPipelinePage.tsx` | composition, filter/sort state, dialogs |
| Tests | `src/tests/leadPipeline.test.tsx` | 72 tests across the six required areas |

`CreateFollowUpDialog` and `LeadStatusBadge` were reused from earlier phases. The only genuinely
new dialog is `AddNoteDialog`, and it exists for a specific reason covered in §7.

## 3. The one thing that could not be built as specified

The brief listed **`CONVERTED`** as a column. `LeadStatus` had no such member — its terminal-success
value was `CUSTOMER`:

```python
# app/models/lead.py, before
NEGOTIATION = "NEGOTIATION"
CUSTOMER = "CUSTOMER"
LOST = "LOST"
```

So a board rendering a "Converted" column had exactly two honest options: label the column
`CUSTOMER` (and diverge from the brief), or send `status: "CONVERTED"` on every drop into it and
collect a 422. This was raised before any code was written, and the decision was to **rename the
enum member**.

Three details made that safe rather than scary.

**It is a rename, not an add-plus-backfill.** Postgres cannot drop an enum member. Adding
`CONVERTED`, backfilling rows, and abandoning `CUSTOMER` would leave a permanently reachable dead
value that every future reader would have to ask about. `ALTER TYPE ... RENAME VALUE` rewrites the
label in the type's catalog entry; rows keep their physical OID and simply read back under the new
name. No row is rewritten, which is what makes it safe on a populated table.

```sql
-- alembic/versions/a1f4c7b93e02
ALTER TYPE lead_status RENAME VALUE 'CUSTOMER' TO 'CONVERTED'
```

**There is a second `LeadStatus`, and it must not be touched.** `app/models/photographer.py`
declares its own `LeadStatus` with its own `CUSTOMER` member, on the Postgres type `leadstatus` —
no underscore — still referenced by `app/services/photographer.py`. Both statements in the
migration name `lead_status` explicitly for that reason. After applying it, both types were
re-inspected in the live database:

```
lead_status: [NEW, CONTACTED, MESSAGE_SENT, REPLIED, INTERESTED, FOLLOW_UP, NEGOTIATION, CONVERTED, LOST]
leadstatus (photographer):  [NEW, CONTACTED, FOLLOW_UP, INTERESTED, NEGOTIATING, CUSTOMER, INACTIVE, REJECTED]
```

**Two service call-sites moved with it**, both of which would have failed silently rather than
loudly if missed:

- `app/services/lead.py:208` — the transition test that decides whether to append a `CONVERTED`
  entry to the lead's timeline. Left unchanged it would have compared against a member that no
  longer existed and raised `AttributeError` on every lead update.
- `app/services/whatsapp.py:105` — `_TERMINAL_LEAD_STATUSES`, the guard that stops an inbound "thanks!"
  from demoting a converted lead back to `NEGOTIATION`. This one is the more interesting of the two:
  it is a `set` membership test, so a stale value would not have raised — it would have quietly
  stopped protecting converted leads. `tests/test_whatsapp.py` covers exactly this behaviour and
  passes after the rename.

The frontend `LeadStatus` union, `LeadStatusPanel`'s option list and `LeadStatusBadge`'s colour map
were updated to match. `src/tests/dashboard.test.tsx` still contains `lead_status: 'CUSTOMER'` and
was correctly left alone — those fixtures are photographers, not leads.

## 4. Nine columns, because eight would hide leads

The brief's list omitted `CONTACTED`, which is a real and reachable status. A board that skipped it
would do two bad things at once: hide every lead sitting in it, and give those leads no column to be
dragged *out* of. It is rendered in its pipeline position, and the test suite asserts both that all
nine are present and that the brief's eight are among them.

## 5. Why nine requests beat one

The obvious implementation — fetch all leads, group by status client-side — does not work here, and
the reason is worth stating precisely:

- `GET /leads` caps `limit` at **500**. Past that, the board silently shows a subset with no
  indication it is doing so.
- There is **no status histogram endpoint**. Column totals computed from a fetched sample are not
  "the number of leads in Interested"; they are "the number of leads in Interested *within the first
  500 rows*". Displaying that as a total is a lie the user cannot detect.

So each column issues its own filtered request and reads `total` from its own envelope — which is
the server's real count for that status under the current filters, independent of how many rows were
actually downloaded. That also means one column paginating never disturbs another.

Pages accumulate rather than replace, the same approach the Lead Details timeline uses: page 3 is a
separate cache entry from pages 1 and 2, so Load More never refetches what is already on screen, and
one invalidation after a drop refreshes every loaded page. Leads are de-duplicated by id while
concatenating, because a lead moved by someone else between two page fetches can legitimately come
back on both — which would otherwise render the card twice and trip React's duplicate-key warning.

## 6. Drag-and-drop without a library

No DnD library was installed, and none was added. The native HTML5 drag API was used instead, which
is a real trade-off rather than a free win:

**What it buys.** Cards stay plain elements. jsdom can fire real `dragStart` / `dragOver` /
`dragEnter` / `dragLeave` / `drop` events at them, so the drag behaviour is *actually tested* rather
than mocked away behind a library's abstraction. Twelve of the 72 tests exercise it directly.

**What it costs.** HTML5 drag fires no events for touch, and cannot be performed by keyboard at all.
Left there, the board's central interaction would be mouse-only. So every card also carries a
**"Move…" select** that runs the identical mutation through the identical code path — same optimistic
update, same rollback, same toasts. It is not a degraded fallback; it is the accessible primary path,
and on touch devices it is the only one. This is listed as gap §1 in `task.md`.

Two implementation details that are easy to get wrong:

**The column is the drop target, not the card.** A card can therefore be dropped into the empty space
below the last one — and crucially into an **empty column**, which would otherwise be the single
place on the board a lead could never be moved to.

**`dragleave` fires when entering a child.** Highlighting naively on enter and clearing on leave makes
the column strobe as the cursor passes over each card inside it. The fix is a counter — enters minus
leaves, clearing only at zero:

```tsx
const handleDragEnter = (event) => { event.preventDefault(); dragCounter.current += 1; onDragEnterColumn(column.status); };
const handleDragLeave = () => { dragCounter.current = Math.max(0, dragCounter.current - 1); if (dragCounter.current === 0) onDragEnterColumn(null); };
```

A test walks the exact enter → enter → leave → leave sequence and asserts the highlight survives the
middle two.

And the single most important line in the whole implementation, which is easy to omit and produces a
board where dropping simply does nothing:

```tsx
const handleDragOver = (event) => { event.preventDefault(); /* without this, `drop` never fires */ };
```

## 7. The optimistic move, and what rollback actually has to restore

A drop is direct manipulation. A card that springs back to its origin for the duration of a round
trip reads as a *failed drag*, not as a pending one — so the move is optimistic, and the mutation's
job is to confirm or undo it.

The subtlety is what "undo" has to cover. A single move touches more than the card:

- the source column's page loses an item **and** decrements its total
- the destination column's page gains an item **and** increments its total
- every *other* loaded page of both columns has its total shift too

Rolling back just the card would leave the counts wrong — visibly and permanently, until a refetch.
So `onMutate` snapshots **every cache entry under the board prefix**, and `onError` restores all of
them:

```ts
const snapshot = queryClient.getQueriesData<Paginated<Lead>>({ queryKey: pipelineKeys.board() });
// …
onError: (_e, _v, context) => context?.snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data)),
```

`cancelQueries` runs before the optimistic edit, or an in-flight column fetch resolving afterwards
would overwrite it with a server page that predates the move — snapping the card back mid-drag for no
visible reason.

Only the destination's **first** page receives the card; appending it to page 2 would place it below
cards it should outrank, and it would vanish on the next refetch anyway. Every page still gains the
count.

Three tests pin this: the card moves optimistically, the totals move with it, and a rejected update
restores items *and* totals on both columns. A fourth covers 409 specifically, since a stale
`version` is the failure most likely to happen in practice.

### A test-harness trap worth recording

The four mutation tests initially failed with `getQueryData` returning `undefined`, which looked like
a bug in the optimistic logic. It was not. The test helper built its `QueryClient` with `gcTime: 0`,
and the tests seed cache entries directly without mounting anything that observes them — so those
entries were garbage-collected the instant they were written, and `cancelQueries` found an empty
cache. The product code was correct throughout; the fix was to leave `gcTime` at its default and
document why in the helper.

## 8. Refreshing only what the move actually invalidated

The brief asked for the affected queries to be refreshed, not the world. A move invalidates:

```ts
onSuccess: (updated) => {
  queryClient.setQueryData(leadDetailKeys.profile(updated.id), updated);   // seed, don't refetch
  queryClient.invalidateQueries({ queryKey: leadDetailKeys.detail(updated.id) });  // timeline gained STATUS_CHANGED
  queryClient.invalidateQueries({ queryKey: leadKeys.summary() });          // dashboard counters
  queryClient.invalidateQueries({ queryKey: leadKeys.count() });
  queryClient.invalidateQueries({ queryKey: leadKeys.sample() });
},
onSettled: () => queryClient.invalidateQueries({ queryKey: pipelineKeys.board() }),
```

The profile cache is *seeded* from the server's response rather than invalidated, so the lead's new
`version` is available immediately — the next drag of that same card sends a fresh version instead of
a stale one. `onSettled` reconciles the board on both paths: on success the real ordering and totals
are confirmed, and on failure the restored snapshot is re-verified rather than trusted.

## 9. Two API shapes the cards had to work around

**Follow-up due dates.** Not a column on `Lead`, and `GET /followups?lead_id=` takes one id — so a
per-card fetch would be dozens of requests per board render. The hook instead reads the open worklist
once (the API already orders it soonest-first) and indexes it by `lead_id`. The honest consequence:
a lead whose only open follow-up falls outside the 200 most imminent tasks shows no due date. That is
decoration on a card, the Lead Details page stays authoritative, and the alternative would dominate
the board's load time.

**Add Note.** `useCreateLeadNote` in `detailHooks.ts` is bound to a lead id at hook-construction
time, which is correct for a page about one lead and useless on a board where the lead varies per
card. Rather than bend the existing hook, `usePipelineCreateNote` takes the lead in its mutation
arguments. `AddNoteDialog` exists for the same reason — the details page uses an inline composer,
and a card has no room for one. It resets on every open, since a dialog reused across cards makes
leaking a draft from one lead into another both easy to do and hard to notice.

## 10. RBAC, and one thing it deliberately does not claim

Per-control, mirroring the endpoints: `leads:update` on the Move control (it performs the same write
a drop does), `followups:create` on Create Follow-up, `whatsapp:create` on Send WhatsApp. **Open
Lead is ungated** beyond the page's own `leads:view` — it navigates and touches no API, so gating it
would restrict nothing while making the card feel broken.

Worth being explicit about: hiding the Move control does **not** disable native dragging, which is a
client-side gesture the browser owns. A user without `leads:update` who drags a card will see the
optimistic move, then watch it roll back when the server rejects the write. The guard mirrors the
server; it does not replace it. That is the same posture every other page in this codebase takes.

## 11. Verification results

```
npm run test   →  339/339 passing (12 files)
                  └─ src/tests/leadPipeline.test.tsx: 72 new tests
npm run build  →  tsc + vite build clean, 0 TypeScript errors
                  dist/assets/index-Chz1tFAF.js  1,213.45 kB │ gzip: 353.47 kB
alembic upgrade head  →  9dcc5194e0bb → a1f4c7b93e02 applied
```

The 72 tests cover the six required areas plus the layers beneath them: sort comparators and column
definitions (utils), URL/param correctness (services), page accumulation, de-duplication, totals and
the optimistic move with rollback (hooks), rendering/empty/loading/error/Load More (columns), real
HTML5 drag events (DnD), filter and sort wiring (UI), and permission gating (RBAC).

Backend regression after the enum rename — all against the live database:

```
python tests/test_lead_activities.py  →  ALL TESTS COMPLETED SUCCESSFULLY
python tests/test_whatsapp.py         →  ALL TESTS COMPLETED SUCCESSFULLY
python tests/test_followups.py        →  ALL TESTS COMPLETED SUCCESSFULLY
```

The WhatsApp suite is the meaningful one here: it contains the assertion that a reply never
re-categorises a converted lead, which is precisely the behaviour `_TERMINAL_LEAD_STATUSES` protects
and precisely what a missed rename would have silently broken.

## 12. Isolation check

No ERP code was read into or written from this phase. Orders, Payments, Inventory, Production,
Delivery, Invoices and Photographers are untouched — `app/services/photographer.py` in particular was
verified unchanged despite owning a `LeadStatus.CUSTOMER` of its own. The frontend changes are
confined to `src/features/leads/`, `src/services/leads.ts`, one route in `src/App.tsx`, and the new
test file. The backend changes are the enum member, its two call-sites, and one migration.

## 13. Known gaps / follow-ups for a later phase

1. **Native drag is mouse-only** (§6). Touch and keyboard users move cards via the "Move…" select.
   `@dnd-kit` with touch sensors, or a pointer-events implementation, would close this.
2. **No user-defined card ordering.** `Lead` has no rank column, so dropping into a specific
   *position* within a column is not meaningful — only the target column is.
3. **Sorting orders only what is loaded** (§5). An `order_by` parameter on `GET /leads` would make it
   exact, and is the highest-value backend addition for this page.
4. **Follow-up badges bounded to 200 open tasks** (§9).
5. **No realtime or polling** — 30s stale window plus an explicit Refresh button.
6. **Assignee names from an unpaginated `GET /employees`** capped at 200, the same limitation the
   dashboard and details pages carry.
7. **Bundle is 1.21 MB (353 KB gzipped)**, up ~24 KB and still un-split. Route-level `React.lazy`
   remains the fix.
8. **`npm run lint` still cannot run** — `eslint` is not installed despite the script existing.
   Pre-existing; `tsc` inside `npm run build` covers typechecking and passes clean.

---

# Lead Import — Frontend Walkthrough

## 1. Objective

Replace the `/leads/import` placeholder with a production Lead Import screen: choose a source, run a
collection, watch it progress, see what landed, and review the history. The backend engine —
providers, deduplication, import jobs, endpoints — already existed and was consumed **exactly as
built**. Nothing under `app/`, no migration and no provider implementation was modified.

## 2. Files created

| File | Layer | Contents |
|---|---|---|
| `src/features/leads/importUtils.ts` | pure | Provider capability catalogue, CSV validation, duration/byte/name formatting, status→Badge mapping, `toFriendlyErrorMessage` |
| `src/features/leads/importValidation.ts` | pure | `buildImportSchema` — a Zod schema factory built per selected provider |
| `src/features/leads/importHooks.ts` | logic | `useImportProviders`, `useImportHistory`, `useImportStatistics`, `useProviderBreakdown`, `useLeadImport`, `useRetryImport` |
| `src/features/leads/components/ProviderSelector.tsx` | view | Radio-group source picker + capability panel |
| `src/features/leads/components/CsvDropZone.tsx` | view | Drag-and-drop CSV picker with upload progress |
| `src/features/leads/components/ImportResultSummary.tsx` | view | Outcome card (Imported / Duplicates / Updated / Failed / Duration) |
| `src/features/leads/components/ImportHistoryTable.tsx` | view | Run history, table on desktop / cards on mobile, with retry |
| `src/features/leads/components/ImportStatsCards.tsx` | view | Lifetime statistics + provider breakdown |
| `src/features/leads/pages/ImportLeadsPage.tsx` | page | Composition and form wiring only |
| `src/tests/importLeads.test.tsx` | test | 61 tests |

## 3. Files modified

- **`src/features/leads/types.ts`** — added the seven import DTOs mirroring
  `app/schemas/import_job.py`, and corrected `ImportJobStatus`, which declared five members where
  `ImportJobStatus` in `app/models/import_job.py` has six. `CANCELLED` was missing, and it is one of
  the three statuses the retry endpoint accepts — so the omission was load-bearing, not cosmetic.
- **`src/services/leads.ts`** — extended the existing `leadImportsService` with seven wrappers.
  `listJobs` was left in place rather than replaced: the dashboard's Recent Imports widget only ever
  wants "the newest N", and rewriting a working call site for uniformity would be churn.
- **`src/App.tsx`** — placeholder replaced with `<ImportLeadsPage />`; guard corrected from
  `leads:create` to `leads:import`.

## 4. Architecture decisions

**Layering matches the rest of the feature.** Service = API calls only; hooks = every request, cache
edit and toast; components = presentational, no fetching. The page holds two pieces of local state
(selected provider, form) and nothing else. No new global state was introduced.

**The provider registry is fetched, not hardcoded.** `is_available` is a deployment fact — whether
`GOOGLE_MAPS_API_KEY` or the Instagram credentials are configured on that server. A hardcoded list
would advertise Instagram as ready on a server that cannot run it, and the user would learn otherwise
only from a failed request. Only presentation copy (the ✔ capability bullets) lives in the frontend,
keyed by provider and merged onto the registry response; a provider the registry returns but
`importUtils` does not know still renders, with an empty bullet list.

**No `FileUpload` component was created.** The brief named one from "the UI library", but
`src/components/ui/index.ts` exports no such primitive. `CsvDropZone` therefore composes the ones
that do exist rather than adding a global component for one call site. Its drop target is a real
`<button>`, not a styled `<div>`, which supplies keyboard focus, Enter/Space activation and a
screen-reader role without reimplementing any of them.

**The provider key is deliberately not a form field.** An earlier revision mirrored `selectedKey`
into the form with `setValue`, creating two sources of truth; the submit then failed validation on an
empty `provider` with no visible error, because no input rendered that field's message. Holding it in
one place and passing it at submit removed the class of bug entirely.

**No polling.** `POST /leads/import` runs collection synchronously and returns the completed job, so
there is no job id to poll and no status query. The consequence is a long-lived request: both import
endpoints get a 5-minute per-request timeout (`IMPORT_REQUEST_TIMEOUT_MS`) applied per call rather
than by widening the shared client's 15s default, which would let every ordinary CRUD request hang
for minutes.

## 5. API endpoints consumed

| Endpoint | Used by | Notes |
|---|---|---|
| `GET /leads/import/providers` | `useImportProviders` | 5-minute `staleTime`; availability drives the "Not configured" badge |
| `POST /leads/import` | `useLeadImport` | JSON `{provider, query, limit}`; returns the finished job |
| `POST /leads/import/csv` | `useLeadImport` | multipart `file` + `limit`; `onUploadProgress` drives the bar |
| `GET /leads/imports` | `useImportHistory` | paginated history, newest first |
| `GET /leads/imports/statistics` | `useImportStatistics` | lifetime aggregates for the summary cards |
| `POST /leads/imports/{id}/retry` | `useRetryImport` | offered only for FAILED/PARTIAL/CANCELLED, never for file uploads |
| `GET /leads/imports/{id}` | `leadImportsService.getJob` | wrapper in place; no drill-in view consumes it yet |

## 6. State flow

```
ProviderSelector ──selectedKey──┐
                                ├──> buildImportSchema({requiresQuery, requiresFile})
react-hook-form (query, limit, file)          │
        │                                     ▼
        └── submit ──> useLeadImport.run() ──> csv? POST /leads/import/csv
                                              else POST /leads/import
                                                       │
                              ┌────────────────────────┤
                              ▼                        ▼
                   invalidateQueries(leadKeys.all)   setResult(job)
                              │                        │
                    pipeline/dashboard/history       ImportResultSummary
                    /statistics all refetch          replaces the form
```

Whether a keyword is required is a property of the provider in the registry, so the Zod schema is
rebuilt per selection rather than branching on `provider === 'csv'` inside the component. Switching
source clears the input that no longer applies, so a CSV is never carried over to a Google Maps run.

Invalidation targets `leadKeys.all` — the root — rather than the import keys alone. A successful
import creates leads, so every list, count and chart is stale; this page's own history and statistics
are nested under the same root and refresh with it. One broad call cannot miss a widget, and
TanStack Query only refetches what is actually mounted.

## 7. Error handling

`toFriendlyErrorMessage` is the single translation point, and it draws one line: backend text is
surfaced only for statuses whose bodies are written for humans (400/404/409/422 — our own
`AppException`s, which say things like "'notes.pdf' is not a CSV file"). **5xx bodies are replaced
wholesale**, because they may carry a driver message or stack trace. That is precisely the class of
response the "never expose raw backend errors" requirement is about, and it is asserted in the tests.

| Condition | What the user sees |
|---|---|
| Missing API key | "Not configured" badge, an explanatory panel, and a disabled Import button — the request is never fired |
| Provider unavailable (502/503/504) | "The lead provider is temporarily unavailable." |
| Network failure | "Could not reach the server." |
| Timeout | "The import took too long… check the import history before retrying" — deliberately *not* "it failed", since a synchronous run may well have completed |
| Validation (400/422) | The backend's own human-readable detail |
| Missing permission (403) | Names the `leads:import` permission to ask for |
| Large file | Caught client-side before upload, with the actual size and the limit |

Rate limiting (429) and oversized payloads (413) are handled explicitly too. Every failure raises a
toast through the existing `useNotificationStore`/`ToastProvider`; none is rendered raw.

## 8. Accessibility

The drop zone is a focusable `<button>` with `aria-label` and `aria-describedby`. The source picker
is a `<fieldset>`/`<legend>` of real radio inputs, so arrow-key navigation and group semantics come
from the platform. The result card carries `role="status" aria-live="polite"`, and a live region
beside the Import button announces the run starting, its upload percentage and its completion — a
screen-reader user learns the outcome without watching the spinner. Validation errors use
`role="alert"`. The history table has a `<caption>` and `scope="col"` headers. All interactive
elements have visible `focus-visible` rings, and disabled states are real `disabled` attributes.

Light/dark are handled through existing design tokens; layouts are responsive at every breakpoint,
with the history table collapsing to stacked cards below `md` rather than dropping columns.

## 9. Testing

`src/tests/importLeads.test.tsx` — **61 tests**, organised by layer, with `axios` stubbed at the
`api` module boundary so the service layer under test is real code:

- **utils (16)** — CSV validation (extension, size, empty), provider ordering and copy merging,
  duration/name formatting, and seven `toFriendlyErrorMessage` cases including the assertion that a
  `psycopg2` 500 body never reaches the user.
- **services (6)** — exact URL, JSON body, multipart fields and upload-progress percentage.
- **hooks (7)** — cache invalidation on `leadKeys.all`, success/PARTIAL/error toasts, CSV routing,
  and the provider breakdown with its sampled flag.
- **page (18)** — provider switching (keyword input hidden and drop zone shown for CSV), capability
  panels, unavailable-provider gating, validation blocking (empty keyword, no file, wrong file type),
  Google Maps / Instagram / CSV imports end-to-end, the loading state, duplicate-submission
  prevention, failure keeping the form, and Import Again.
- **navigation & RBAC (3)** — View Leads → `/leads`, query invalidation, and the screen refusing
  without `leads:import`.
- **history & statistics (11)** — row rendering, empty/error/refresh, retry offered only where the
  backend accepts it, and the statistics cards.

## 10. Build verification

```
npm run test   →  400/400 passing (13 files)
                  └─ src/tests/importLeads.test.tsx: 61 new tests, 0 failures
                  └─ 339 pre-existing tests unchanged and still passing
npm run build  →  tsc + vite build clean, 0 TypeScript errors
                  dist/assets/index-B-WDjyl6.js  1,255.36 kB │ gzip: 364.76 kB
```

`npm run lint` still cannot run: `eslint` is not installed and is not a declared devDependency.
This is pre-existing and unrelated to this phase — `tsc` (with `noUnusedLocals`) runs inside
`npm run build` and passes clean, which covers the unused-import class of lint error.

The Vite chunk-size advisory is pre-existing and applies to the whole bundle; route-level
`React.lazy` remains the fix, as noted in the previous phase.

## 11. Isolation check

No backend file was read into or written from this phase — `app/`, `alembic/`, the provider
implementations and the deduplication logic are byte-for-byte unchanged, as are the WhatsApp and ERP
modules. The Lead module's own code was extended only additively: `types.ts` gained new interfaces
(plus the `CANCELLED` correction) and `services/leads.ts` gained methods on an existing object. No
existing lead component, hook or page was modified. The only edit outside `src/features/leads/` is
the one route in `src/App.tsx`.

---

# OpenStreetMap / Overpass Lead Provider — Walkthrough

## 1. Objective

Replace the **paid** Google Maps provider with a **free** one: collect the same photography
businesses from OpenStreetMap via the public Overpass API, behind the same `LeadProvider`
interface, so a search costs nothing and needs no credential.

Scope note: this phase touched **only** the collection path. The CRM and the `Lead` model were
not modified — no column, no enum member, no Alembic migration. WhatsApp, Lead Management,
Orders, Inventory, Payments, Production, Delivery, Dashboard and Authentication were not
touched. No endpoint was added; `POST /api/v1/leads/import` is reused exactly as it stands.

## 2. What was added

**Added:** one module, `app/services/lead_providers/overpass.py`, and one test suite,
`tests/test_overpass_import.py`.

**Edited** (three files, all additive):

| File | Change |
|---|---|
| `app/core/config.py` | New `OVERPASS_*` / `NOMINATIM_*` settings block. No existing setting altered. |
| `app/services/lead_providers/__init__.py` | One import line + one `__all__` entry. |
| `tests/test_lead_import.py` | The provider-registry assertion now expects 9 providers, not 8. |

`google_maps.py`, `base.py`, `normalized.py`, `planned.py`, `lead_import.py`, every endpoint
and every model are **byte-for-byte unchanged**.

## 3. The constraint that shaped everything: Overpass is not a search engine

The Google adapter could hand "Wedding Photographer Thrissur" almost verbatim to Text Search.
Overpass cannot accept that at all. It is a *query language over a geographic database*: it
answers "objects with these tags inside this shape", and the shape must be **coordinates**.

So collection is necessarily two hops:

```
city  ──Nominatim──►  (lat, lon)  ──Overpass QL──►  every matching OSM element
```

That is **two network calls for an entire import**, against Google's N+1 (a Text Search page
plus one *billed* Place Details call per business). The entire cost model that dominated the
Google adapter — honour the limit before the fan-out, bound the Details concurrency, let an
operator switch details off — **has no analogue here**. There is no fan-out and nothing is
billed. Roughly two-thirds of the design pressure in `google_maps.py` simply evaporates.

Because a city is what gets geocoded, **`city` is mandatory** for this provider where it was
optional for Google. `search()` refuses without one, at request time, before the job is ever
marked RUNNING.

## 4. What replaces cost as the thing to be careful about

The public Overpass and Nominatim instances are **donated capacity governed by a usage
policy**, not a paid quota. The failure mode is not a surprise invoice — it is being blocked.
Three mechanisms exist solely for that, and they are the substantive design decisions in the
module:

**Serialised, spaced requests.** `_RateLimiter` holds an `asyncio.Lock` across the *whole*
request — not merely while sleeping — and enforces `OVERPASS_MIN_REQUEST_INTERVAL_SECONDS`
between releases. The policy asks for roughly one query at a time from a given client, so the
correct model is a queue, not a token bucket with a burst allowance. Holding the lock across
the request is what makes two *concurrent imports* through one provider instance queue behind
each other instead of doubling the load the endpoint sees; a bare `asyncio.sleep` between
calls would not.

**Retry with exponential backoff.** Overpass answers `429` (rate limited) and `504` (query
load too high) under load and both are ordinarily transient — retrying is the documented
correct response and giving up immediately would fail runs that were always going to succeed.
Delay is `base * 2**attempt`, capped at `OVERPASS_BACKOFF_MAX_SECONDS`. Three details matter:

  * **`Retry-After` wins over the computed delay.** The server knows when it will be ready and
    we do not; ignoring an explicit instruction is the fastest way to get blocked. It is still
    capped, so a hostile or mistaken header cannot park an import for hours.
  * **`400`/`403` are *not* retried.** A malformed query or a block is a final answer;
    retrying only adds load to an endpoint that has already said no. Only
    `{429, 500, 502, 503, 504}` and transport faults are retryable.
  * **No sleep after the final attempt.** Waiting 8 seconds only to then give up is pure
    latency for the operator.

**A real User-Agent.** Both usage policies *require* a client to identify itself;
`OVERPASS_USER_AGENT` should carry a real contact address in production.

## 5. The generated query, and why it looks like that

`build_query()` is public and pure — the QL string *is* the contract with Overpass, so it is
directly assertable in a unit test with no network at all:

```
[out:json][timeout:50];
(
  node["shop"="photo"](around:5000,11.2588,75.7804);
  way["shop"="photo"](around:5000,11.2588,75.7804);
  relation["shop"="photo"](around:5000,11.2588,75.7804);
  ... one clause per (tag, element type) pair ...
);
out center tags;
```

Four decisions are encoded here:

1. **Five tag filters, not the three the brief named.** `shop=photo`, `office=photographer`
   and `studio=photography` are queried as specified — plus `craft=photographer`, which in
   OSM's actual data substantially *outnumbers* `office=photographer` for a photography
   studio, and `shop=photo_studio`. Querying only the three named tags would silently halve
   the yield.
2. **All three element types.** A studio may be mapped as a `node` (a point), a `way` (a
   building outline) or a `relation`. Querying only nodes — the obvious simplification — drops
   every business mapped as a building, which in Indian towns is a large share of commercial
   POIs.
3. **`out center`, not a bare `out`.** A `way` has no coordinate of its own; without `center`
   it returns as a list of node references and the CRM's `latitude`/`longitude` columns get
   nothing.
4. **The server-side `[timeout:N]` is kept *below* the client timeout.** Otherwise the client
   hangs up on work the server is still doing, and the retry re-queues it — turning one slow
   query into several.

The union is required because Overpass has no "any of these tags" operator across differing
keys. Note also that **`category` does not narrow the query**: OSM has no free-text index to
narrow *with*. The category is recorded and surfaces as a lead category tag; filtering names
client-side would drop correctly tagged studios whose names merely lack the operator's word.

## 6. Mapping OSM tags onto `NormalizedLead`

OSM has no canonical key for anything, so `normalize()` is mostly *preference order over
competing tags* — and the ordering is the substance, not a detail:

| Field | Tags tried, in order | Why the order |
|---|---|---|
| name | `name:en`, `name`, `official_name`, `brand`, `operator` | A Malayalam-script `name` is correct OSM data but unusable in an English call list. |
| phone | `phone`, `contact:phone`, `contact:mobile`, `mobile`, `phone:mobile` | The first entry is promoted to the CRM's `phone` column, and a landline on `phone` is more often the *published* number. |
| email | `email`, `contact:email` | — |
| website | `website`, `contact:website`, `url`, `contact:url` | — |
| city | `addr:city`, `addr:town`, `addr:village`, `addr:suburb` | Indian addresses are frequently tagged at town/village granularity. |

Multi-value tags (`phone=+91 495 111;+91 98470 222`) are split on `;` and `,` in source order,
so a studio publishing two numbers yields a primary *and* a WhatsApp number.

**Address is assembled, not read.** OSM stores no formatted-address string, so a displayable
line is built from the `addr:*` parts in the order an Indian address is written, with
case-insensitive de-duplication — an element tagged with both `addr:suburb` and `addr:city`
holding the same value is common, and "Kozhikode, Kozhikode, Kerala" reads as a data error to
whoever is working the call list.

**City falls back to the searched city.** This would be unsound for a general geocoder but is
sound here: every element in the result set is *by construction* within `radius_km` of that
city's centre. Without it, `normalize_business_key` cannot produce a key at all, so the same
studio re-collected next month would import a second time.

## 7. The one thing OSM gives that Google cannot — and what it costs

Google Places returns **no email address at any price**. OSM contributors tag `email` and
`contact:email` directly, so this adapter populates `NormalizedLead.emails` from data the paid
provider structurally could not supply.

The trade is coverage and contactability, and it should be stated plainly:

> OSM's photography coverage in India is **thinner** than Google's, and many OSM nodes carry a
> name and a location but **no phone** — which `NormalizedLead.is_valid()` rejects. **A run
> here will show a higher failed-record count than the same search on Google Places.**

That is expected, it is visible per record in the job log, and it is the trade being made for
a provider that costs nothing. It is not a bug to be fixed in the adapter.

## 8. Failure contract — unchanged, which is why this drops in cleanly

`ProviderCollectionError` is raised **only** for faults invalidating the whole run: the city
cannot be geocoded, the endpoint is unreachable, it is still refusing after every retry, or it
returned something that is not Overpass JSON. Anything wrong with a single element — no phone,
no name, an unparseable coordinate — degrades **that record** via `is_valid()` and never the
run. `normalize()` never raises; junk in yields an invalid `NormalizedLead` out.

The geocode failure is the one place this adapter fails a run over something the *operator*
typed. That is deliberate: with no coordinates there is no query to run, so there is nothing to
degrade gracefully into. The message says exactly that and suggests a fix.

## 9. Attribution: why `lead_source = "GOOGLE_MAPS"`

The brief said not to modify the CRM or `Lead` models, and `LeadSource` is an enum **on**
`app/models/lead.py`. Adding an `OPENSTREETMAP` member would mean editing that model plus an
Alembic `ALTER TYPE` migration.

Overpass leads are map-listing leads, so they reuse the member the Google adapter used. Every
existing dashboard, filter and dedup rule that groups map-sourced leads keeps working
unchanged, and the phase stays a pure provider-layer addition. The cost is a member name that
no longer literally matches its source — recorded as a follow-up in task.md, where adding
`OPENSTREETMAP` is a one-line enum change plus a migration whenever a model change is in scope.

## 10. Registered *alongside*, not over

`OverpassLeadProvider` registers under the new key `overpass`; `google_maps` is left
registered and untouched. Operators pick either at request time, the two can be compared on
the same city side by side, and there is no hard cutover on a provider whose coverage
characteristics differ. Retiring the paid adapter later is deleting one import line.

Note the availability contrast, which is the headline of this phase:

```
google_maps      available=False  Google Maps lead collection is not configured:
                                  GOOGLE_MAPS_API_KEY is unset. …
overpass         available=True   (no credential exists that could disable it)
```

## 11. Testing (`tests/test_overpass_import.py`)

Unlike its Google sibling, this is a **pure unit suite**: no database, no marker rows, no
cleanup block, no configured Postgres — because the brief for this provider is explicitly "do
not save anything into the database". It is safe to run anywhere. Every response is mocked via
`httpx.MockTransport`, speaking real Overpass and Nominatim shapes (`{"elements": [...]}` with
`center` on ways; Nominatim's bare JSON array with *string* `lat`/`lon`).

`StubbedOverpassProvider` overrides **only** `_import_httpx`, so `search()`, `collect()`,
`normalize()`, the geocode hop, the rate limiter and every retry path are the production code
— the stub replaces the socket and nothing else.

Ten sections: provider initialization · search validation · QL construction · geocoding ·
collection · normalization · rate limiting · retry & backoff · the failure contract ·
non-persistence.

Two are worth calling out:

* **Rate limiting is measured, not asserted structurally.** Two concurrent imports are run
  through one provider instance with `asyncio.gather` and the inter-call gaps are checked
  against the event-loop clock — which is the only way to catch a limiter that sleeps but does
  not actually serialise.
* **Backoff delays are recorded rather than spent.** `asyncio.sleep` is swapped for a recorder,
  so the suite asserts the *computed policy* — `[2.0, 4.0]`, `Retry-After` precedence, the cap,
  no-sleep-after-the-final-attempt — in milliseconds instead of half a minute. A retry suite
  that really slept is the first one a developer skips.
* **Non-persistence is asserted on the source.** The module is read with `inspect.getsource`
  and checked to contain no `from app.models`, no `from app.repositories`, no `AsyncSession`,
  no `db.commit`. The provider *cannot* write to the CRM, because it imports nothing that
  could.

```
python tests/test_overpass_import.py       # ALL 10 SECTIONS PASSED
python tests/test_lead_import.py           # unchanged, still passing (9 providers)
```

## 12. Isolation check

No migration was generated, because nothing schema-shaped changed. The route table is
unchanged — no endpoint added. Outside the new provider module and its new test, the edits are
exactly three: `config.py` (a new settings block), `lead_providers/__init__.py` (one import,
one export), and `test_lead_import.py` (a provider count of 9 instead of 8).

---

# Website Discovery — Lead Enrichment Walkthrough

## 1. Objective

Extend the lead discovery pipeline with an enrichment step. For every normalized lead whose
`website` is empty: search the public web on business name + city, discover the official
website, validate that it belongs to the same business, ignore directory sites, save only the
official domain, never overwrite an existing website, and return the enriched
`NormalizedLead`.

Kept as a **separate `WebsiteDiscoveryService`**. **No database writes.**

## 2. What was added

| File | Change |
|---|---|
| `app/services/website_discovery.py` | **New** — the service, the `SearchBackend` port, the DuckDuckGo backend, the directory list, the scorer. |
| `tests/test_website_discovery.py` | **New** — unit suite. |
| `app/core/config.py` | New `WEBSITE_DISCOVERY_*` settings block. |

> **Superseded in part.** A follow-up phase extracted the `SearchBackend` port and the
> DuckDuckGo backend into `app/services/lead_providers/web_search/`, renamed the transport
> settings to `WEB_SEARCH_*`, and added live URL validation, retries and robots.txt handling.
> See *Web Search Abstraction — Website Discovery Phase 2* below for the current shape.

Nothing else changed. No provider, no model, no schema, no endpoint, no migration.

## 3. Why a service and not a provider

The obvious-looking move is to make this another `LeadProvider`. It is the wrong shape.

A provider answers **"what businesses exist for this query"** — its contract is `search →
collect → normalize` over a search term. This answers **"given a business I already have,
what is its website"**. The input is a `NormalizedLead`, not a query, and the output is the
same lead with one field filled.

Folding discovery into an adapter would also mean implementing it *per adapter*. Overpass
leads frequently lack a website (OSM's `website` tag is optional and often absent), and so do
Instagram leads. Both would need the same logic. As a separate service it composes with all of
them at once, and it is testable on a hand-built `NormalizedLead` with no provider, no
`ProviderContext` and no network at all — which is exactly what the suite does.

## 4. The pipeline, per lead

```
website already present ──▶ returned untouched                    (rule 6, checked first)
website empty ──▶ build query "name + city"                       (rule 1)
              ──▶ SearchBackend.search()                          (rule 2)
              ──▶ reject directories                              (rule 4, before scoring)
              ──▶ score surviving candidates against the business (rule 3)
              ──▶ best ≥ threshold ? store its domain : unchanged  (rule 5)
              ──▶ return NormalizedLead                           (rule 7)
```

Rule 6 is checked **first**, before anything else, and that ordering is load-bearing: a batch
of already-enriched leads issues **zero** outbound searches. The suite asserts not merely that
the existing website survives but that `backend.queries == []`.

## 5. The search backend is a port

"Search the public web" has no single correct implementation. An operator holding a Google CSE
or Brave key wants that engine; an operator holding neither still wants the feature to work at
all. So the backend is a one-method ABC:

```python
class SearchBackend(ABC):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...
```

with `DuckDuckGoSearchBackend` — **no credential of any kind** — as the default. This is the
same reasoning that put `OverpassLeadProvider` alongside the billed Google Places adapter:
the feature should work on a fresh checkout with nothing configured.

Adding Google CSE, Brave or Serper later is a new subclass plus one `_SEARCH_BACKENDS` entry
and a config value. `WebsiteDiscoveryService` does not change — it depends on the port.

Note one deliberate asymmetry with `get_provider`: an **unknown backend key falls back to the
default with a warning rather than raising**. `get_provider` raises because substituting a
provider would write CRM rows under the wrong `source` attribution. Nothing is written here at
all, so degrading to the free default is strictly better than breaking an import run.

## 6. The part that actually matters: validation, not search

A search for "Sunrise Studio Kozhikode" reliably returns *something*. The risk was never
finding nothing — it is **confidently attaching the wrong domain**, which is worse than
leaving the field empty, because an empty field visibly reads as a gap while a wrong one looks
like data. Two defences, in this order.

### Defence 1 — directories are rejected outright, before scoring

Search "Sunrise Studio Kozhikode" and the real results are dominated by Justdial, Sulekha,
WedMeGood, WeddingWire, IndiaMART, a Facebook page and a Google Maps pin. These **outrank a
small studio's own site** for exactly the query this service issues. A "take the first result"
implementation would attach a directory to the majority of leads.

`_DIRECTORY_DOMAINS` holds ~90 such domains and is matched against the registrable domain
**and any subdomain of it** — directories serve city and category pages from subdomains
(`kozhikode.justdial.com`) that are the same site.

Rejection happens **before** scoring, not after. That is what guarantees a top-ranked directory
can never win on rank; the suite proves it by putting Justdial at position 1 and the genuine
site at position 2 and asserting the genuine site is chosen.

The list errs toward rejecting on purpose, because the costs are not symmetric: a directory
that slips through writes a wrong website, while a legitimate site wrongly skipped leaves the
lead in the state it was already in.

### Defence 2 — what survives must earn its place

`_score_candidate` accumulates evidence, capped at 1.0:

| Evidence | Weight | Why |
|---|---|---|
| Domain ↔ business-name token overlap | up to 0.6 | The primary signal. |
| Result title corroborates the name | up to 0.3 | Independent of the domain string. |
| City appears in title or snippet | 0.1 | Ties the result to the right locality. |
| Search-engine rank | up to 0.1 | Real evidence, worth *a little* — it is what puts directories on top in the first place. |

Matching is both token-equality **and** substring containment against the concatenated domain
stem, because studios overwhelmingly register `sunrisestudio.com` rather than
`sunrise-studio.com`.

The subtle part is `_GENERIC_TOKENS`. "photography", "studio", "wedding", "films", "candid"
and ~50 others are stripped before matching, because they appear in a large share of *all*
photography business names. Without that, `lakesidephotography.in` would validate against
"Sunrise Photography Studio" on the shared word "photography" — two unrelated businesses. When
*every* token is generic ("The Photo Studio") the full list is used as a fallback and the
confidence threshold is what decides.

Below `WEBSITE_DISCOVERY_MIN_CONFIDENCE` (0.5) the lead comes back unchanged with status
`below_threshold`. **Declining to guess is a supported outcome**, and it carries the score and
the reasoning so an operator can see the service considered a domain and rejected it.

## 7. Only the domain, never the ranking URL

A lead's website is the business's site — not the one page a search engine happened to
surface. So:

```
https://www.sunrisestudio.in/gallery/weddings?ref=ddg#top   →   https://sunrisestudio.in
```

Path, query string, fragment and `www.` are all dropped, and several pages of the same site
collapse to a single candidate rather than three. The stored value is then passed through the
existing `normalize_url`, so what a lead receives already satisfies the CRM's URL validator.

## 8. Explainability

`discover()` is the plain function the brief describes — `NormalizedLead` in, `NormalizedLead`
out. `discover_with_outcome()` returns a `DiscoveryOutcome` carrying the status, the
confidence, the evidence that produced it, the number of candidates considered and the
directories rejected:

```
status:     discovered
website:    https://sunrisestudio.in
confidence: 1.00
reasons:    · domain 'sunrisestudio.in' matches name token(s) sunrise (100% of distinctive tokens)
            · result title corroborates name token(s) sunrise
            · result mentions the lead's city
            · top-ranked non-directory result
rejected:   justdial.com
```

This is the same split `LeadProvider` makes between `collect()` and `collect_normalized()`:
the clean path for the common case, the inspectable one for when someone asks *why*.

## 9. Failure contract — nothing raises

Enrichment is best-effort by definition. An import of two hundred leads must never fail
because one of them could not be resolved. So every failure path returns the input lead:

| Situation | Status | Result |
|---|---|---|
| Lead already has a website | `already_present` | unchanged, no search issued |
| Lead has no business name | `not_searchable` | unchanged, no search issued |
| Backend unavailable (no credential) | `search_failed` | unchanged, not called |
| Network fault / HTTP 5xx | `search_failed` | unchanged |
| Backend bug (violates the contract, raises) | `search_failed` | unchanged |
| Engine answered, nothing survived filtering | `no_candidates` | unchanged |
| Best candidate too weak | `below_threshold` | unchanged, score recorded |
| Match found | `discovered` | enriched copy |

`discover_many` inherits this per lead: the suite runs a batch where the middle lead's search
raises, and asserts the other two still enrich.

## 10. Politeness, borrowed from the Overpass adapter

The default backend is an unmetered public endpoint, so the failure mode for bursting is
**being blocked**, not being billed — the same situation Overpass is in. The same answer
applies: outbound searches are serialised behind a lock held *across the whole request* (not
merely across the sleep, which is what makes concurrent discoveries queue instead of double
the observed load), spaced by `WEB_SEARCH_MIN_REQUEST_INTERVAL_SECONDS`, and sent with
an identifying `User-Agent`.

The SERP parse is deliberately defensive. The HTML endpoint is not a documented API, so the
parse anchors on the stable `result__a` / `result__snippet` class names and **skips anything it
does not recognise**. A SERP redesign degrades this to "no candidates found" — it cannot
produce wrong URLs. DuckDuckGo's `//duckduckgo.com/l/?uddg=` redirect wrapper is unwrapped to
the real target, because storing the wrapper would save a tracking URL that breaks the moment
the redirector changes.

Regex rather than an HTML parser: none is a dependency of this project, and adding one for a
single defensive extraction is not worth the supply-chain surface.

## 11. Testing (`tests/test_website_discovery.py`)

A **pure unit suite**, like `test_overpass_import.py` and unlike the DB-backed
`test_google_maps_import.py` — the brief is explicitly "no database writes", so there is no
session, no marker row and no cleanup block. It needs no `.env`, no Postgres and no
credential, and is safe to run anywhere.

Most sections drive the service through a `StubSearchBackend` implementing the port directly —
that is what the port is *for*, and it exercises the filtering, scoring and threshold logic
with no engine response format in the way. Section 8 additionally drives the **real**
`DuckDuckGoSearchBackend` against `httpx.MockTransport` serving real-shaped DuckDuckGo HTML
(genuine `result__a` markup, genuine `uddg=` redirect wrappers), so the production parse is
the one under test.

Ten sections at this phase: construction & registry · query construction · directory rejection ·
validation · domain-only persistence · never-overwriting · the enriched return value · the
DuckDuckGo backend · rate limiting · the failure contract & non-persistence. (Phase 2 below
adds five more, taking the suite to fifteen.)

Three are worth calling out:

* **Directory rejection is tested against ten real directory URL shapes** — Justdial, Sulekha,
  WeddingWire, WedMeGood, Facebook, Instagram, IndiaMART, Google Maps, a Justdial *subdomain*
  and linktr.ee — all ranked above the genuine site, and the lead must come back with no
  website at all.
* **Rate limiting is measured, not asserted structurally.** Three concurrent discoveries run
  through one backend and the inter-call gaps are checked against the event-loop clock, which
  is the only way to catch a limiter that sleeps but does not actually serialise.
* **Non-persistence is asserted on the source.** The module is read with `inspect.getsource`
  and checked to contain no `from app.models`, no `from app.repositories`, no `AsyncSession`,
  no `db.commit`; and `discover()`'s signature is asserted to be exactly `(self, lead)`. The
  service *cannot* write to the CRM, because it imports nothing that could and accepts no
  session to do it with.

```
python tests/test_website_discovery.py    # ALL 15 SECTIONS PASSED (after phase 2)
python tests/test_overpass_import.py      # unchanged, still passing
```

## 12. Isolation check

No migration was generated, because nothing schema-shaped changed. The route table is
unchanged — no endpoint added. Outside the new service module and its new test, the edit is
exactly one: a `WEBSITE_DISCOVERY_*` settings block appended to `config.py`.

The service is **not yet wired into `LeadImportService`** — that is deliberate. The brief asked
for the service and for no database writes; calling it from the import path changes the
behaviour of every import run (one outbound search per websiteless lead) and should land
together with an operator-facing switch. The wiring is small when it comes: construct the
service, `await service.discover_many(records)` between `collect_normalized()` and
`_process_records()`, and fold each `DiscoveryOutcome.detail` into the job's log array. It is
recorded as follow-up 1 in `task.md`.

---

# Web Search Abstraction — Website Discovery Phase 2 Walkthrough

## 1. Objective

Two things, one phase.

**Structural:** promote the search backend from a section inside `website_discovery.py` to a
**package of its own**, so "how do we search the web" and "which of these URLs is the official
site" stop sharing a file. The brief named the layout directly — `web_search/base.py`,
`web_search/duckduckgo.py` — and required that no lead or database logic live inside a search
provider.

**Operational:** close the four gaps the first phase left open — the discovered URL was never
actually fetched to see if it resolved, a transient search failure was not retried, robots.txt
was not consulted, and redirects were followed without a bound.

DuckDuckGo remains the **default, zero-credential** backend. No paid search API was added, and
the Google Maps provider is not involved.

## 2. What was added

| File | Change |
|---|---|
| `app/services/lead_providers/web_search/__init__.py` | **New** — package entry point; imports backends for their registration side effect. |
| `app/services/lead_providers/web_search/base.py` | **New** — `SearchResult`, `SearchBackend`, `SearchBackendError`, the registry, `get_search_backend()`. |
| `app/services/lead_providers/web_search/duckduckgo.py` | **New** — the default backend. HTML parse, rate limiter, retries, robots.txt, bounded redirects. |
| `app/services/website_discovery.py` | **Modified** — backend code removed; `_validate_website` added; new `validation_failed` status. |
| `app/core/config.py` | **Modified** — transport settings renamed `WEBSITE_DISCOVERY_*` → `WEB_SEARCH_*` and extended; two validation knobs added. |
| `tests/test_website_discovery.py` | **Modified** — 10 → 15 sections. |

The `Lead` model, every schema, every repository, every endpoint, `overpass.py` and the Import
Leads UI are **unchanged**. **No migration** — confirmed by running autogenerate, below.

## 3. The seam, and why it is worth a package

The whole point of the split is a boundary that holds in **both** directions:

```
website_discovery.py            web_search/
  knows: leads, scoring,          knows: HTTP, HTML, robots.txt,
         directories, confidence         retries, rate limits
  does NOT know: HTML, SERPs      does NOT know: leads, the DB, scoring
                       ↘         ↙
                      SearchResult
                  (title, url, snippet)
```

`SearchResult` is three strings. That is the entire contract, and keeping it that small is
deliberate: anything richer would be a field one backend could populate and another could not.

The brief's constraint — *"Do NOT put lead/database logic inside the search provider"* — is not
just documented, it is **tested**. Section 14 reads the backend's source with
`inspect.getsource` and asserts it contains no `NormalizedLead`, no `AsyncSession`, no
`from app.models` and no `from app.repositories`. A future contributor who reaches for the lead
layer from inside a backend gets a failing test, not a code review comment.

The payoff is concrete: adding Google CSE or Brave later is a new module with a
`@register_search_backend` decorator and a `WEB_SEARCH_BACKEND=` value. `WebsiteDiscoveryService`
does not change — which is exactly what "provider-agnostic" was asked to mean.

## 4. Registration, and one deliberate asymmetry

Backends register with a decorator rather than a manual dict entry, so the declaration and the
wiring are the same line in the same file — a backend cannot be written and then silently left
unreachable. This mirrors `lead_providers/base.py`.

One thing behaves **differently** from the provider registry, on purpose. `get_provider("nope")`
**raises**; `get_search_backend("nope")` **warns and falls back to DuckDuckGo**.

The asymmetry is about consequences. A wrong provider key means an operator asked for data the
system cannot supply — silently substituting a different source would be lying about where the
leads came from. A wrong search-backend key means one *enrichment* step consulted a different
engine. Discovery writes nothing on its own, and a weak result is discarded by the confidence
threshold regardless, so degrading to the free default is strictly better than failing an
import run over a typo in `.env`.

## 5. Validation — the gap that mattered most

Phase 1 validated a discovered URL's **shape**. It never checked that anything was *there*.
That leaves a specific bad outcome: a domain that scores well, parses fine, and 404s — a dead
link written onto a lead, indistinguishable in the UI from real data.

`_validate_website` now runs before the lead is enriched:

1. **Shape** — scheme must be `http`/`https`, host must contain a dot. No network for a
   malformed candidate; `ftp://`, `javascript:` and hostless strings die here.
2. **Reachability** — `HEAD` first because it is far cheaper. On `405`/`501`, retry with `GET`:
   enough small hosts reject `HEAD` outright that treating it as failure would discard working
   sites.
3. **Bounded** — `max_redirects=WEB_SEARCH_MAX_REDIRECTS`, never unlimited, so a parked-domain
   redirect loop terminates instead of consuming the timeout.
4. **Short timeout** — `WEBSITE_DISCOVERY_VALIDATE_TIMEOUT_SECONDS` (5s), deliberately shorter
   than the search timeout, since this runs once per discovered lead.

Failure produces the new `validation_failed` status and **leaves the website empty**. It never
raises — including when `httpx` is missing, where it accepts on shape alone rather than
discarding every discovery over an optional dependency.

Note what validation deliberately does **not** do: it answers "does something answer here", not
"is this the right business". That remains the scorer's job. Conflating them would let a
reachable *wrong* domain pass on the strength of returning HTTP 200.

## 6. Retries — and why a 403 is not retried

Retries cover **429 and 5xx and transport faults**. A `403` is not retried at all.

That distinction is the interesting part. A 403 is not a transient fault; it is a decision
about *this client*. Retrying it three times does not recover the request — it confirms to the
far side that we are automated and arrives at a durable block faster. Retrying is only correct
when the fault is plausibly temporary.

Backoff is `base * 2**(attempt-1)` with a ceiling, plus **full jitter**. The jitter is not
decoration: several concurrent imports that all failed on the same upstream blip would
otherwise retry in perfect lockstep and reproduce the burst that caused the failure.

An exhausted budget raises `SearchBackendError`, which the service catches and turns into "lead
unchanged" — so a total outage costs exactly the enrichment it could not perform, and nothing
else.

## 7. robots.txt — including the case that is easy to get backwards

The endpoint is unmetered public capacity we are a guest on, so robots.txt is fetched and
honoured before searching, and the verdict is **cached for the process lifetime** — re-fetching
it per search would itself be the kind of traffic robots.txt exists to limit.

The case worth stating explicitly: **an unreachable robots.txt means allowed, not forbidden.**
A file we could not fetch is not a directive to stay away. Treating a 500 or a timeout as a
prohibition would disable website discovery entirely on any transient network fault — strictly
worse than proceeding under the same terms a browser would. An explicit `Disallow` *is*
honoured, and refuses the search.

The matcher is minimal by design: the `User-agent: *` group, prefix matching, no full RFC 9309
`Allow`-precedence rules. `urllib.robotparser` is stdlib but synchronous, and calling it would
block the event loop on its own fetch — so the fetch stays async here and only the matching is
reimplemented.

## 8. Configuration

`WEB_SEARCH_BACKEND=duckduckgo` is the setting the brief asked for. The split between the two
blocks mirrors the split in the code, so which layer a knob belongs to is readable from its name:

| Prefix | Governs | Examples |
|---|---|---|
| `WEB_SEARCH_*` | the **swappable transport** | `BACKEND`, `TIMEOUT_SECONDS`, `MAX_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`, `MAX_REDIRECTS`, `RESPECT_ROBOTS`, `MIN_REQUEST_INTERVAL_SECONDS` |
| `WEBSITE_DISCOVERY_*` | the **non-swappable scoring/validation** | `MIN_CONFIDENCE`, `MAX_RESULTS`, `CONCURRENCY`, `VALIDATE_URL`, `VALIDATE_TIMEOUT_SECONDS` |

**No credential setting exists** for the default backend — and section 14 asserts that none can
appear unnoticed, by scanning `settings` for any `WEB_SEARCH_*` name containing `KEY`, `TOKEN`,
`SECRET`, `CREDENTIAL` or `PASSWORD` and failing if one turns up. "Works with an empty `.env`"
is a property the suite defends, not a claim in a docstring.

Old import paths still resolve: `SearchResult`, `SearchBackend`, `SearchBackendError` and
`get_search_backend` are re-exported from `website_discovery`, so the move breaks no caller.
They are aliases, not a second copy.

## 9. Testing — 15 sections, still no network and no database

Sections 1–10 are the phase-1 suite, unchanged in intent. Five are new:

* **11 — URL validation.** A reachable site is accepted via `HEAD`; a 404 yields
  `validation_failed` with the website left **empty** and the original lead object returned; a
  host answering `HEAD` with 405 falls back to `GET` and still validates; a `ConnectError` is
  contained; and `ftp://`, `javascript:`, hostless and malformed URLs are rejected **without a
  request being made**.
* **12 — Retries and backoff.** A 503 that recovers on the third attempt; the recorded sleep
  delays asserted to *grow*; a 429 retried to exhaustion then raised; a **403 asserted to be
  tried exactly once**; and a timeout retried then contained by the service. The backoff
  constants are shrunk and `asyncio.sleep` is captured, so the section asserts the schedule
  without spending real seconds.
* **13 — robots.txt and redirects.** `Disallow: /html/` refuses the search; an unrelated
  `Disallow` does not; an unfetchable robots.txt resolves to allowed; three searches trigger
  **one** robots fetch (proving the cache); and a redirect loop terminates against the budget
  instead of hanging.
* **14 — No credentials.** The default resolves to DuckDuckGo, reports available with nothing
  configured, constructs bare, exposes no credential setting, and — per §3 — its source
  references no lead or database symbol.
* **15 — Duplicate results.** Four results across one site collapse to one candidate;
  `www.` and deep paths reduce to the same registrable domain; a genuinely *different* domain
  is **not** crowded out by repetition; and de-duplication happens before the result limit is
  applied, so duplicates cannot starve the evaluation.

Every HTTP call — search, validation, **and robots.txt** — is served by `httpx.MockTransport`.
The suite needs no `.env`, no Postgres, no credential and no network.

```
python tests/test_website_discovery.py    # ALL 15 SECTIONS PASSED
python tests/test_lead_discovery.py       # ALL 8 SECTIONS PASSED
python tests/test_contact_extractor.py    # ALL 17 SECTIONS PASSED
python tests/test_overpass_import.py      # ALL 10 SECTIONS PASSED (provider untouched)
npm run test                              # 452 passed (13 files)
npm run build                             # tsc + vite build clean
```

## 10. Isolation check — no migration

Confirmed rather than asserted. Running `alembic revision --autogenerate` produced a file whose
`upgrade()` and `downgrade()` were both bare `pass` — the models and the database already agree,
because this phase added no column, no table and no enum value. The throwaway file was deleted;
`alembic/versions/` is unchanged.

This is the expected result: the phase adds a *service-layer* capability. A discovered website
is written to the existing `leads.website` column by the existing import path, through code
that did not change.

The Import Leads UI was not touched either — the brief allowed changes "if absolutely
necessary", and none were: the enrichment is server-side and the response contract the frontend
consumes is unchanged, which the 452 passing frontend tests confirm.

---

# Contact Extraction — Lead Enrichment Walkthrough

## 1. Objective

Extend the enrichment pipeline with the step that follows website discovery. For a normalized
lead that **has** a website: visit it, look at the header, the footer, the contact page and
the about page, extract phone numbers, WhatsApp numbers, email addresses and
Instagram/Facebook/YouTube links, normalize every value, and return the enriched
`NormalizedLead`.

Constraints from the brief, all structural rather than advisory: use **BeautifulSoup**,
respect **robots.txt**, limit crawling depth to **one level**, do **not** crawl the entire
website, and do **not** write into the database.

## 2. What was added

| File | Change |
|---|---|
| `app/services/contact_extractor.py` | **New** — the service, the robots cache, region/link selection, extractors, normalisers. |
| `tests/test_contact_extractor.py` | **New** — 11-section unit suite. |
| `app/core/config.py` | New `CONTACT_EXTRACTION_*` settings block. |
| `requirements.txt` | Added `beautifulsoup4==4.12.3`. |

Nothing else changed. No provider, no model, no schema, no endpoint, no migration.

## 3. Why this is the next step after discovery

The website discovery walkthrough closed with a list of known limitations. Number 4 read:

> **The candidate's site is never fetched.** Validation uses the domain, the SERP title and
> the snippet only. Fetching the homepage and checking it … would be materially stronger
> evidence — it is the single highest-value improvement available here.

This is that improvement, built as its own service rather than folded into discovery. The two
compose in sequence and have genuinely different jobs:

```
provider ──▶ NormalizedLead (no website)
         ──▶ WebsiteDiscoveryService  ──▶ "what is their website?"
         ──▶ ContactExtractorService  ──▶ "given the website, how do I contact them?"
```

Keeping them separate means a lead that arrived *with* a website from Google Places skips
discovery entirely and still gets extraction — which is the common case, and would have been
awkward to express inside a service whose first rule is "return early if a website exists".

## 4. The pipeline, per lead

```
no website ──────────────▶ returned untouched (nothing to visit)
website present ─────────▶ robots.txt ──▶ disallowed ──▶ returned untouched
                         ──▶ allowed ──▶ fetch home page
                                      ──▶ extract from header + footer + whole page
                                      ──▶ pick <=N contact/about links (SAME HOST ONLY)
                                      ──▶ fetch each (depth 1 — never followed further)
                                      ──▶ merge, normalize, dedupe ──▶ enriched lead
```

Every branch that is not the happy path returns the **input lead object**, unchanged.

## 5. "One level" is a property of the code's shape, not a counter

This is the constraint most likely to erode over time, so it is not implemented as a
parameter. A `max_depth=1` argument is one edit away from `max_depth=3`, and a reviewer of
that edit sees a number change rather than an architectural one.

Instead: `extract()` contains exactly one `_fetch_page` call for the home page, and exactly
one `_fetch_page` per selected link, in a flat `for` loop. The links harvested from those
second-level pages are parsed for *contacts* but never *visited*. There is no recursion, no
work queue, and no depth parameter in the constructor — the suite asserts all three, including
by grepping the module source for a queue.

The test does not take the service's word for it either. The mock transport records every URL
requested, and the fixture site deliberately links `/contact/directions`, `/team` and
`/about/history` from its level-one pages, with a phone number that exists *only* on those
deeper pages. The suite asserts those URLs were never requested and that the number never
reached the lead.

## 6. "Do not crawl the entire website" — three independent bounds

1. **Same host only.** An off-host link is never followed. Without this, one `<a>` to a
   partner studio turns enrichment into a walk across the open web.
2. **A page is fetched because it is a contact page, not because it exists.** A link qualifies
   only if its text or path matches a contact/about hint. The fixture's `/gallery` and
   `/pricing` links are internal, valid and never fetched.
3. **A hard cap.** `CONTACT_EXTRACTION_MAX_SUBPAGES` bounds the second level regardless of how
   many links qualify. The suite feeds it a page with 30 qualifying links and asserts the
   result is 4 requests — one home page plus a cap of three.

Contact pages are ordered ahead of about pages, because that is where a number actually lives;
about is the fallback for sites that fold contact details into their story.

## 7. robots.txt

Visiting five pages on a small business's site is unremarkable traffic, but the site's operator
is entitled to say no, and the cost of asking is one cached request per host.

`urllib.robotparser` is standard library and implements the grammar needed. Two behaviours
worth stating explicitly, because they are opposite defaults:

* **Absent or unreachable robots.txt permits fetching.** A 404 is the overwhelmingly common
  case and means "no rules exist". A 5xx is treated the same way: failing closed against sites
  that never configured robots.txt would disable the feature for most of the market.
* **A file that parses and disallows us is final.** Zero page requests are issued and the lead
  is returned untouched — not "returned with whatever we got first".

It is fetched **once per host** and cached, including across concurrent leads on that host: a
per-origin lock means twenty leads on one domain issue one robots.txt request between them,
while different hosts never wait on each other. The suite asserts the single-fetch property
both sequentially and across three concurrent leads.

The User-Agent matched against the rules is the same string the page fetcher sends. Obeying
rules written for someone else would be worse than not checking at all.

## 8. Where contacts come from, and in what order

The brief names header, footer, contact page and about page. Header and footer are scanned
**first and separately**, then the whole document.

That ordering is not cosmetic. `NormalizedLead` promotes `phone_numbers[0]` into the CRM's
single `phone` column, so whichever number lands first *becomes the business's number*.
Scanning in source order would let a photographer's mobile quoted in a testimonial outrank the
studio's own switchboard.

Footer and header are matched by tag, by ARIA role, **and** by class/id convention — a large
share of small-business templates render the footer as `<div class="site-footer">` rather than
`<footer>`, and a tag-only implementation would miss the single richest contact block on the
page. The fixture uses exactly that form, so the suite would catch a regression here.

Within a region, **links are read before text**. A `tel:` or `mailto:` href is a value the site
*declared* to be a phone number or an address; a digit run in a paragraph is an inference. The
declared values therefore lead the ordering.

## 9. The junk problem

Text scraping produces false positives constantly, and they are not symmetric with misses. A
missing phone number is a visible gap. A **wrong** phone number is the field the CRM
deduplicates on — a bogus value can collapse two unrelated businesses onto one lead.

So the text pass is defended:

| Junk | Why it looks valid | Defence |
|---|---|---|
| `logo@2x.png` | A perfectly well-shaped email address | Domain-suffix rejection |
| Sentry DSN in a `<script>` | A well-shaped address with a hex local part | `<script>`/`<style>` stripped before any text is read; long-hex local rejected |
| `info@example.com` | Genuinely valid | Placeholder local/domain lists |
| `2014`, `25000`, `673001` | Digit runs — a year, a price, a pincode | Length bounds + `normalize_phone` must accept it |
| `9999999999` | Right length | Repeated-digit and known-placeholder rejection |
| `facebook.com/sharer/…` | A real Facebook URL in the footer | Platform-furniture path segments rejected |

Every row above is in the fixture and asserted in section 5 of the suite.

**WhatsApp is only claimed when the site claims it.** A number is recorded as a WhatsApp
number only from a `wa.me` or `api.whatsapp.com/send` link, both of which carry the number in
the URL. A number printed in a footer may or may not be on WhatsApp, and guessing would put a
wrong claim in front of an operator who is about to message it.

## 10. Merging onto the lead: enrichment never overwrites

A lead arriving here already carries whatever its provider found, and a Google Places record
is better attributed than a regex over HTML. So:

* **Single-valued fields are filled only when empty.** An existing `instagram` or `facebook`
  survives untouched — mirroring rule 6 of website discovery.
* **List fields are appended to, never replaced.** Scraped numbers and addresses land *behind*
  the provider's, deduplicated on the CRM's own comparison keys (`normalize_phone` /
  `normalize_email`) rather than on raw strings — so `+91 98765 43210` and `9876543210` do not
  both survive.
* **The input is never mutated.** A new `NormalizedLead` is returned via `dataclasses.replace`.

WhatsApp numbers and YouTube links get **their own fields** on `NormalizedLead`
(`whatsapp_numbers: list[str]`, `youtube: str | None`), both optional and defaulted so no
existing provider or caller changes. The first cut carried them in `raw` to avoid widening a
shared DTO; that was the wrong call for WhatsApp, because the brief requires it stored
*separately* from ordinary phones and the one consumer that needs it — `secondary_phone`,
which fills the CRM's `whatsapp` column — cannot read `raw`. `raw["contact_extraction"]` still
records the complete harvest and the pages visited, so a value that lost to an existing field
is inspectable rather than lost.

### Phone numbers become E.164

Every number goes through `phonenumbers` (the libphonenumber port). The forms an Indian site
actually uses all converge on one value:

| Written on the page | Stored |
|---|---|
| `9876543210` | `+919876543210` |
| `+91 9876543210` | `+919876543210` |
| `+919876543210` | `+919876543210` |
| `0091 9876543210` | `+919876543210` |
| `098765 43210` | `+919876543210` |
| `080 12345678` | `+918012345678` |

The library is also what rejects junk a digit-count heuristic cannot: it knows which ranges
are *assignable*, so a 10-digit order number or a GST identifier fails validation even though
it is exactly phone-shaped. Numbers that will not validate are dropped rather than stored in a
canonical-looking form that would lend them false authority.

### The ownership signal

`WebsiteDiscoveryService` proves a URL is *reachable*; reachability says nothing about
*ownership*. A search backend can return a directory page, a competitor or a parked domain,
and all three answer 200. Once the page has actually been read we can do better, because the
page says who it belongs to. `_score_relevance` weighs five signals:

| Signal | Weight | Why |
|---|---|---|
| A phone already on the lead is published on the site | 0.35 | Near-conclusive. |
| The business name appears in the page text | 0.30 | Strong. |
| The name is echoed in the domain | 0.20 | Strong. |
| A contact email is at the site's own domain | 0.15 | Corroborating. |
| The lead's city appears on the site | 0.10 | Weak — every studio in a city names it. |

The result is a score, a band (`owned` / `uncertain` / `unrelated`) and the individual signals.
**It gates nothing.** A real studio whose homepage is an image-only splash with the name in a
logo scores near zero, and discarding it would lose a good lead — so the extractor reports and
`LeadDiscoveryService` decides, exactly as the brief specifies.

### Result statuses

| Status | Meaning |
|---|---|
| `extracted` | Every selected page was read; contacts found. |
| `partial` | Contacts found, but at least one selected page failed to load. |
| `no_contact_found` | Pages read fine; the site publishes no contact details. |
| `fetch_failed` | The home page never arrived (timeout, DNS, 4xx, 5xx, redirect loop). |
| `robots_blocked` | `robots.txt` forbade the visit. |
| `invalid_content` | A response arrived but was not usable HTML, or exceeded the size cap. |
| `no_website` | The lead had no website to visit. |

`no_contact_found` is a **success** — `outcome.succeeded` is True. Plenty of small sites expose
only a contact form, and treating that as a system error would bury the real failures.

## 11. Testing (`tests/test_contact_extractor.py`)

17 sections, **no database and no network**, safe to run with no `.env`, no Postgres and no
credential:

```
python tests/test_contact_extractor.py    # ALL 17 SECTIONS PASSED
```

* **Only the socket is mocked.** Pages and `robots.txt` are served by an injected
  `httpx.MockTransport`, so the real fetch path, the real BeautifulSoup parse and the real
  `urllib.robotparser` handling are the code under test.
* **The transport records every request.** This is what makes "depth is one level" and "the
  whole site is not crawled" *verifiable* — they are claims about which requests were and were
  not issued, and cannot be checked from a return value.
* **The fixture is adversarial on purpose**: a `<div class="site-footer">` instead of
  `<footer>`, a share button beside the real social links, an asset filename that reads as an
  email, a Sentry DSN in a `<script>`, a number written as text in one place and as `tel:` in
  another, and level-two links carrying a number that must never surface.
* **Non-persistence is asserted on the source.** The module is read with `inspect.getsource`
  and checked to contain no `from app.models`, no `from app.repositories`, no `AsyncSession`,
  no `db.commit`; and `extract()`'s signature is asserted to be exactly `(self, lead)`.

Writing the suite paid for itself immediately: section 8 caught a real bug in which the robots
cache built its own HTTP client and ignored the injected transport, so a `Disallow` was never
seen. In production that path would have fetched the live robots.txt correctly, but the cache
was untestable and any client customisation would have silently bypassed it.

## 12. Isolation check

`alembic revision --autogenerate` produces an **empty** migration — generated, inspected,
deleted. Both `upgrade()` and `downgrade()` were `pass`. The `Lead` model and the CRM schema
are untouched; `NormalizedLead` is an in-memory DTO, not a table, so its two new optional
fields cost nothing at the database layer. The route table is unchanged — no endpoint added.

### Crawling limits, at a glance

| Bound | Where it comes from | What it stops |
|---|---|---|
| Depth = 1, structurally | the shape of `extract()` — no recursion, no queue, no depth knob | becoming a crawler |
| ≤ 4 second-level pages | `CONTACT_EXTRACTION_MAX_SUBPAGES` | fetching a whole sitemap |
| Same host only | `_select_subpages` | walking onto a CDN, a partner or a client site |
| Contact/about links only | link-text and path hints | fetching a page merely because it exists |
| 2 MB per response | streamed cap; oversized ⇒ `invalid_content` | one pathological page exhausting memory |
| 5 redirects | `CONTACT_EXTRACTION_MAX_REDIRECTS` | a redirect loop running unbounded |
| 3 leads at a time | `CONTACT_EXTRACTION_CONCURRENCY` (a shared semaphore) | hundreds of simultaneous sockets |
| 1 s between requests to one host | per-host limiter, not global | hammering one small server |
| `robots.txt` | cached once per host; `Disallow` is final | fetching where we were told not to |

A visit therefore costs at most 5 page requests plus one cached `robots.txt` per host, and a
run of 200 leads never has more than 3 in flight.

### Failure handling

`extract()` **never raises.** A dead domain, TLS error, timeout, 404, 500, redirect loop,
non-HTML body, oversized body, unparseable markup and a robots prohibition all resolve to
"return the input lead unchanged", carrying a status that says which happened. One site being
down cannot fail an import of two hundred leads — and a sub-page that fails does not lose the
home page's harvest, it just downgrades the outcome to `partial`.

### Where it is wired

**Into `LeadDiscoveryService`, behind a switch that already existed.** `DiscoveryRunRequest`
has carried `discover_websites` and `extract_contacts` booleans since the pipeline phase, so
turning this on changed no operator-facing workflow and needed no new endpoint. The stage now
calls `extract_many_with_outcomes`, so per-lead statuses and ownership bands reach the run
summary in `StageStats.detail` — an operator seeing "0 enriched" can tell unreachable sites
from robots-blocked ones from sites that simply publish nothing.

`detail` is additive, and the stage still accepts an extractor that offers only
`extract_many`. Note that `extract_contacts` defaults to **true**: a discovery run visits the
site of every lead that has one, bounded as tabulated above.

---

# Lead Discovery Pipeline — `LeadDiscoveryService`

## 1. Objective

Turn a city name into saved leads by running the stages that already exist, in order:

```
city
  ↓  Overpass provider          businesses on the map near that city
  ↓  website discovery          find the official site of the ones without one
  ↓  contact extraction         visit those sites, read the published contacts
  ↓  normalization              canonicalise phones / emails / handles / URLs
  ↓  deduplication              classify each record: new / merge / duplicate
  ↓  save new leads             insert the new ones, enrich the mergeable ones
summary
```

and return:

```python
{"found": …, "imported": …, "merged": …, "duplicates": …, "failed": …}
```

## 2. What was added

Two files, and nothing else:

| File | Change |
|---|---|
| `app/services/lead_discovery.py` | **New** — `LeadDiscoveryService`, `DiscoverySummary`, `StageStats`. |
| `tests/test_lead_discovery.py` | **New** — 8-section integration suite. |

No provider changed. No model, schema or endpoint changed. No migration, no new dependency,
no config key. Every stage this service runs was already written and already tested; what was
missing was the thing that runs them in order.

## 3. This is the wiring the last two phases deferred

`WebsiteDiscoveryService` and `ContactExtractorService` both shipped deliberately unwired.
Each closed with the same note: the wiring is small, but it adds outbound network requests to
every run, so it belongs with an operator-facing switch rather than being switched on by
stealth.

This phase is that wiring, and it ships that switch — `discover_websites=False` and
`extract_contacts=False` skip the two network-touching stages. A re-run over a city that was
enriched last month pays for one Overpass query instead of one search and one site visit per
lead.

## 4. The one rule that shapes the whole file

**The service orchestrates. It does not scrape.**

There is no HTTP call in it, no HTML parsing, no scoring, no matching rule, no cleanup regex.
Every one of those already lives in a service that owns it and tests it. The moment one is
copied here it exists twice, and two copies of a matching rule drift — silently, and in a way
that shows up as "why did this import create a duplicate" months later.

So the rule for editing this file is: if the change is about **what a stage does**, it belongs
in that stage's module. Only a change about **which stage runs when** belongs here.

That rule is enforced rather than requested. Section 7 of the suite parses the module with
`ast` and fails the build if it imports `httpx`, `requests`, `bs4`, `urllib`, `aiohttp`,
`selenium` — or `re`:

```python
for banned in ("httpx", "requests", "bs4", "urllib", "aiohttp", "selenium"):
    check(banned not in imported_modules,
          f"The orchestrator must not import '{banned}' — scraping belongs in a stage.")
```

and it asserts the positive too — that the module *does* call `discover_many`,
`extract_many`, `normalize_lead`, `deduplicate` and `collect_normalized`, so the stages are
delegated rather than quietly reimplemented. A comment saying "no scraping here" is worth
nothing the first time someone needs just one regex. A failing test is worth something.

## 5. Dependency injection, and what it buys

Every collaborator is a constructor argument defaulting to `None`, resolved to the real
implementation:

```python
LeadDiscoveryService(
    provider=None,                 # → registry's "overpass"
    website_discovery=None,        # → WebsiteDiscoveryService()
    contact_extractor=None,        # → ContactExtractorService()
    contact_normalizer=None,       # → ContactNormalizationService()
    deduplication_service=None,    # → LeadDeduplicationService()
    lead_repository=None,          # → LeadRepository()
    activity_service=None,         # → LeadActivityService()
)
```

Production constructs it with no arguments and gets the shipped pipeline. The suite injects
stubs for the three stages that touch the network, and runs everything else for real against
a real database.

That is not a testing convenience bolted on afterwards — it is what makes an integration test
of this class possible at all. Without it, testing the pipeline would require a live Overpass
endpoint, a live search engine and a live set of photographer websites, which is slow,
non-deterministic, and rude to donated infrastructure.

The provider is injected as an **object**, not resolved from the registry inside `run()`, for
the same reason `LeadImportService.run_import` accepts a `provider` argument: a service that
reaches into a global registry mid-run cannot be tested without mutating that global. It is
resolved lazily via a property, so construction never depends on provider-registration import
order, and one adapter instance — therefore one rate limiter — is reused across a run.

## 6. City in, and the query nobody should have to know about

`run(db, city="Kozhikode")` is the whole call. But `OverpassLeadProvider` sets
`requires_query = True`, so a bare city would be refused — even though what it actually
geocodes *is* the city, and its tag filter is what selects photography businesses.

Rather than make every caller pad the call with a query string they cannot influence, the
service defaults it:

```python
DEFAULT_QUERY = "photography"
```

The provider's requirement is still honoured, and "city in, leads out" stays an honest
one-argument call.

## 7. Whole-batch passes, not per-record

Each stage runs over the entire batch before the next begins. This is deliberate: both
`discover_many` and `extract_many` hold their own semaphore and fan out across leads. Running
the pipeline per record would serialise a hundred round trips, which is the difference
between a fast run and a timeout.

The trade is memory — the whole batch is held at once — which is bounded by the provider's
`MAX_COLLECTION_LIMIT` of 1000 records and is not a real constraint at that size.

## 8. Both normalisation passes run, and neither is redundant

Stage 4 looks like it does the same thing twice:

```python
cleaned = self.contact_normalizer.normalize_lead(record).normalize()
```

It does not. `ContactNormalizationService.normalize_lead` canonicalises **values** — phones to
E.164, emails lowercased, Instagram to a bare handle, URLs to a scheme. `NormalizedLead.normalize()`
enforces the **record's shape** — column length caps, coordinate range checks, ordered
de-duplication of the phone list.

Deduplication derives its comparison keys from both. Skipping either would mean comparing a
canonicalised phone against an uncanonicalised one, which is exactly the failure that lets a
duplicate through.

## 9. Enrichment is best-effort; persistence is not

These two are treated differently, on purpose.

**Discovery and extraction never raise** — that is their documented contract, and both return
the lead unchanged on every failure path. So this service does *not* wrap them in a
try/except. Wrapping them would add nothing except a place for a genuine bug in one of them
to hide behind a silent "enrichment skipped". A lead whose website could not be found is not
a failure; it is a lead with no website, which is the state it arrived in.

**A failed write is a real loss**, and is contained per record:

```python
except Exception as exc:
    await db.rollback()
    summary.failed += 1
    summary.errors.append(...)
```

The rollback is load-bearing: a failed write poisons the session, and without it every
subsequent record in the run would fail too. This is the same per-record isolation
`LeadImportService._process_records` uses, for the same reason — one bad row must not cost a
run of two hundred.

**A source-level fault propagates.** If Overpass is unreachable, `run()` raises rather than
returning `found: 0`. "The source was down" and "this city has no photographers" produce the
same number and mean opposite things; reporting them identically would be a lie the operator
acts on.

## 10. The summary, and why it reconciles

The five counters are not independent tallies — they partition the collected records:

```
imported + merged + duplicates + failed == found
```

`found` is counted before any filtering, so it is a real denominator. An invalid record (no
business name, no phone) is counted in `failed` rather than quietly dropped. A record that
matched an existing lead lands in `merged` if it filled a blank field and `duplicates` if it
added nothing.

That identity is what makes the summary trustworthy: a record cannot be lost between two
stages without the totals disagreeing. It is exposed as `summary.reconciles`, logged at ERROR
when it fails — a mismatch is a bug in this file, not in a stage, so it should be loud — and
asserted on **every** scenario the suite runs, not just the happy one.

`to_dict()` returns exactly the five specified keys and nothing else. The diagnostics that
make a surprising number explainable — per-stage counts, the ids of leads created and merged,
one error line per failure — are attributes and `to_detailed_dict()`, so a documented
response shape is not widened by a debugging convenience.

## 11. A vanished merge target is a failure, not a re-create

Deduplication returns a **plan**; this service applies it. Between planning and writing,
another operator can delete a lead the plan wanted to enrich. The obvious handling — create
it instead — is wrong: it resurrects a lead someone deliberately removed. So the record is
counted in `failed` with a reason, and the run continues.

## 12. Testing (`tests/test_lead_discovery.py`)

An **integration** suite, not a unit one: the database is real, and four of the six stages are
real — normalization, deduplication, persistence and activity logging all run in production
form. Only the three network-touching collaborators are stubbed, each implementing its port
directly:

* `StubProvider` — an actual `LeadProvider` subclass, returning canned records.
* `StubDiscovery` — honours the real service's rules (never overwrite, never raise).
* `StubExtractor` — enriches only leads that have a website, never raises.

Stubbing exactly those three is the point of the injection under test. Each already has its
own dedicated suite (`test_overpass_import.py`, `test_website_discovery.py`,
`test_contact_extractor.py`); what is under test *here* is the orchestration.

| § | Covers |
|---|---|
| 1 | DI — every collaborator overridable, defaults are the real services, `describe()` reports what is actually wired |
| 2 | Stage order and hand-off, proven by recording harnesses — including that extraction receives the website discovery found |
| 3 | The five-key contract, reconciled against rows actually in the database |
| 4 | Enrichment reaching the saved `Lead`; status `NEW`, source attributed, timeline activity written |
| 5 | Merge, duplicate, and the same business twice in one batch |
| 6 | Invalid record, a write that raises, a source fault, a refused request |
| 7 | The structural orchestration-only assertions |
| 8 | Empty collection, the two stage toggles, diagnostics |

Every row is hard-deleted in a `finally` block — repository writes commit immediately, so a
session rollback would not undo them — matched by a per-run marker so a mid-suite failure
still cleans up after itself. Phone numbers are derived from that marker too, because `phone`
carries a UNIQUE constraint and a fixed test number would collide with a previous run's
leftovers, turning a real failure into a confusing one.

Section 2's hand-off assertion is the one worth keeping. It does not check that discovery and
extraction both ran — it checks that the *website discovery produced in stage 2* appears in
the batch stage 3 received. A pipeline whose stages each work but pass the wrong thing along
is precisely the bug an orchestrator can have and its component tests cannot catch.

## 13. Isolation check

No migration, because nothing schema-shaped changed. The route table is unchanged — no
endpoint added. Outside the two new files, **nothing was edited**: not a provider, not
`normalized.py`, not `lead_import.py`, not `config.py`, not `requirements.txt`.

The service is callable but not yet exposed. A `POST /leads/discover` belongs in a follow-up
alongside an RBAC permission and a decision about backgrounding — a city-wide run issues one
search and one site visit per lead found, which is a slow request rather than a snappy one.
The other open thread is `ImportJob`: `LeadImportService` records every run as an auditable
job with a log array, while this pipeline leaves no trace beyond the leads and their
activities. The two should converge on one audit shape, most naturally by having this service
create an `ImportJob` too.

---

# Production-Readiness of the Lead Discovery Workflow

## 1. Objective

Make `CITY SEARCH → REAL BUSINESSES → CONTACT INFORMATION → CLEAN LEADS → CRM` work reliably
from end to end, and make what was collected visible to the operator who has to phone these
people. The stages already existed; this phase audited them for silent data loss, fixed what
it found, and surfaced the result. It deliberately stops short of WhatsApp campaign
execution.

## 2. The final pipeline

```
POST /api/v1/leads/discover   (city, category, radius_km, limit,
                               discover_websites, extract_contacts)
   │
   ▼
1. Overpass provider        businesses tagged photography near the geocoded city
   ▼
2. Website Discovery        for businesses with no website: a DuckDuckGo search,
                            filtered to plausible official sites  [skippable]
   ▼
3. Contact Extraction       visit those sites; read phones, WhatsApp, emails and
                            social links published on them          [skippable]
   ▼
4. Normalization            E.164 phones, lowercased emails, bare handles,
                            column-length caps, ordered de-duplication
   ▼
5. Deduplication            classify each record: new / merge / duplicate.
                            Returns a PLAN. Nothing is written yet.
   ▼
6. Persistence              insert the new, fill blanks on the mergeable,
                            count the rest as duplicates
   ▼
DiscoveryRunResponse        five counters + per-record rows + stages + enrichment
```

Stages 2 and 3 are the only ones that touch the network, which is why they are the two the
operator can switch off. Both are best-effort: a lead whose site cannot be reached is saved
with whatever the map gave us, never dropped.

## 3. Which field comes from which source

| Field | Source | Notes |
|---|---|---|
| `business_name` | Overpass (OSM `name`) | Required. No name → the record fails. |
| `phone` | Overpass tags, else extracted from the website | Required. The CRM's unique key. |
| `whatsapp` | **Only** a source that identified a number *as* WhatsApp | A `wa.me` link or a labelled number. Never inferred. |
| `email` | Extracted from the website | `mailto:` links and page text. |
| `website` | Overpass tag, else Website Discovery | An existing URL is never replaced by a discovered one. |
| `instagram` | Link published on the business's own website | Stored as a bare handle. |
| `facebook` | Link published on the business's own website | Stored as a full URL. |
| `youtube` | Link published on the business's own website | Stored as a full URL. **New this phase.** |
| `address`, `city`, `district`, `state` | Overpass address tags | |
| `latitude`, `longitude` | Overpass node/way centroid | `0.0` is a real coordinate, not a blank. |
| `source` | The provider's declared `LeadSource` | Falls back to `OTHER`. |
| `pincode`, `source_url`, rating, categories, surplus numbers | Overpass / extraction | **Folded into `remarks`** — these have no dedicated column. |

`remarks` is the honest home for collected data that has no column. It is prose, not a
queryable field, and that is the trade: the alternative is a column per stray attribute.

## 4. phone vs WhatsApp vs Instagram URL vs Facebook URL

These four are routinely conflated and must not be.

- **`phone`** is a number to *call*. It is the CRM's unique key, it is required, and it comes
  off the map data or the website. It says nothing about WhatsApp.
- **`whatsapp`** is a number to *message*. It is populated only when a source said so — a
  `wa.me` link on the site, or a number explicitly labelled WhatsApp. **A lead with a phone
  and no `whatsapp` is not WhatsApp-ready**, and the UI will not offer a `wa.me` link for it.
  This is deliberate and it costs us reach: a studio publishing one unlabelled number that
  *does* work on WhatsApp will be missed. Guessing would cost more — a campaign firing into
  numbers that were never on WhatsApp produces silent failures that look like disinterest.
- **`instagram`** is stored as a bare **handle** (`sunrisestudio`), because that is what the
  column has always held and what the profile validator enforces. The UI builds the URL.
- **`facebook`** and **`youtube`** are stored as full **URLs**, because a Facebook page has no
  single canonical handle form and a YouTube channel may be `/@handle`, `/c/`, or `/channel/`.

## 5. Social links are collected, social platforms are not scraped

The distinction is the whole basis on which social data is gathered here.

The contact extractor fetches a **business's own website** and reads the links that business
chose to publish on it — typically the footer icon row. If a studio links its Instagram from
its homepage, that URL is a published fact about the business, and recording it is no
different from recording the phone number printed beside it.

What never happens: no request is made to `instagram.com`, `facebook.com` or `youtube.com`;
no profile, post, follower count or bio is read; no login, token or API key is involved. A
studio with an Instagram presence but no website contributes nothing here, and that is the
correct outcome rather than a gap to close by scraping.

Website fetching itself stays bounded by the extractor's existing rules: robots.txt is
honoured, a small fixed set of pages per site (home, contact, about), one level deep, with a
per-host rate limit shared across concurrent runs.

## 6. Enrichment never overwrites

The merge fills **blanks only**. `build_merge` proposes a value for every mergeable field and
keeps it only where the stored lead is `None` or an empty string. Note that `0` and `0.0` are
not blanks — latitude `0.0` is a real coordinate.

`phone` is not mergeable at all: it is the unique key and usually the thing the match was
made on, so rewriting it could collide with another lead. `status`, `is_converted` and
`assigned_employee_id` are not mergeable either — they are CRM workflow state that no
external source may touch.

The one apparent exception is `whatsapp`, and it is still not an overwrite: when a lead has
no WhatsApp number and an incoming record's primary phone differs from the stored one, that
second number is recorded rather than discarded. Given the CRM stores exactly two numbers,
this is the only way a second number collected later survives at all.

A record that matches an existing lead and adds nothing is a **duplicate** — counted, not
written, and never a second Lead row.

## 7. Statistics describe what was stored, not what was attempted

`EnrichmentStats` counts over the leads the run **wrote** (`imported_records` +
`merged_records`), not over what a stage reported finding. The difference is not pedantry: an
email extracted from a website and then dropped because the lead already had one is not an
email this run delivered, and counting it would tell the operator the run achieved something
it did not.

The two exceptions are `websites_discovered` and `contacts_extracted`, which come from the
stage statistics because they describe *work done* rather than data stored — a site found for
a lead that later proved to be a duplicate was still found.

Nothing here is persisted and no table was added. The figures are derived at the end of a run
for the response only, which is why reporting them needed no schema change. A run that wrote
nothing reports zeroes rather than a fabricated figure.

## 8. Contact quality

A presentation-level band, computed from stored fields, never a column:

- **HIGH** — a number (phone or WhatsApp) *and* a second channel (website, email, or social)
- **MEDIUM** — a number and nothing else
- **LOW** — no number; only a website or social presence
- **NONE** — nothing actionable

Its only purpose is ordering the call list. Storing it would create a value that goes stale
the moment any of the fields it derives from changes.

It is computed in two places on purpose: `DiscoveredLeadRecord.contact_quality` for discovery
results, and `contactQualityOf` in `utils.ts` for pipeline cards, whose leads may never have
been through discovery. The two are kept identical.

## 9. Discovery never sends anything

`POST /leads/discover` writes leads and lead activities. It starts no campaign, queues no
message and calls no WhatsApp API. Producing the interested-contact call list remains a
separate, operator-driven step, and the WhatsApp-ready badge exists to make that step's input
obvious — not to trigger it.

## 10. Testing

`tests/test_lead_discovery.py` section 9 covers the new ground: every collected channel
reaching the `Lead` row, an ordinary phone never being read as WhatsApp, statistics counted
over what was written, populated fields surviving a weaker source, and a failed enrichment
saving the lead unenriched.

That last case drives the **real** `ContactExtractorService` at an RFC 2606 `.invalid`
hostname — a TLD guaranteed never to resolve — rather than a stub that raises. The property
under test is the extractor's own documented "never raises" contract, and a raising stub would
only have proven that the stub raises. No test in this phase makes a real external request.

## 11. Remaining limitations

1. **ESLint is not installed**, so `npm run lint` cannot execute. Not installed here by
   instruction; the npm script is unchanged.
2. **Discovery is synchronous** and writes no `ImportJob` row, so a large city is a long
   request and the progress panel remains an elapsed-time estimate rather than an observed
   stage. The polling seam in `discoveryHooks.ts` is wired and disabled.
3. **WhatsApp coverage is limited by what sources label.** See §4 — this understates reach in
   exchange for not sending into the void.
4. **A business with no website yields little.** Overpass gives name, location and sometimes a
   phone; without a site there is nothing to extract. Such leads land as MEDIUM or LOW.
5. **`remarks` is prose.** Pincode, source URL, rating and surplus numbers are readable but
   not queryable.
6. **Overpass coverage is uneven.** OSM photography tagging is sparse outside larger Indian
   cities, so a small town can legitimately return zero — which the UI reports as "nothing
   found", not as a failure.
