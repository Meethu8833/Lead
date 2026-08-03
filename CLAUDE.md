# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Colour Labs Photographer CRM: a FastAPI + PostgreSQL backend (`app/`) with a React/Vite/TypeScript frontend (`src/`). Domain: managing photography orders through booking → production → payment → delivery, plus inventory, employees/RBAC, invoicing, notifications, and audit logging.

## Commands

### Backend
```bash
# Install deps
pip install -r requirements.txt

# Run dev server (reload)
uvicorn app.main:app --reload
# → API at http://localhost:8000, versioned under /api/v1, OpenAPI at /api/v1/openapi.json

# Migrations (Alembic, async-aware via app/core/config.settings.ASYNC_DATABASE_URI)
alembic revision --autogenerate -m "message"
alembic upgrade head

# Seed roles/permissions (idempotent)
python scripts/seed_roles.py

# Full stack via Docker (Postgres + API)
docker-compose up --build
# Postgres exposed on host port 5433 (container 5432); API on 8000
```

### Backend tests — NOT pytest
`tests/*.py` are standalone async integration scripts, each with its own `if __name__ == "__main__": asyncio.run(...)`. There is no pytest.ini/conftest.py — run each file directly:
```bash
python tests/test_auth.py
python tests/test_permissions.py
python tests/test_erp.py
# etc.
```
They connect to the **real configured database** (from `.env` / `app/core/config.py`), not an isolated/in-memory one. Most suites wrap their work in a transaction and roll it back at the end ("Rollback successful."), but a few (e.g. `test_permissions.py`, `test_search.py`) create and then manually delete rows — assume tests are not automatically safe to run against a shared/production database.

### Frontend
```bash
npm install
npm run dev       # Vite dev server on :3000, proxies /api → http://localhost:8000
npm run build      # tsc typecheck + vite build
npm run lint        # eslint, zero warnings allowed
npm run preview
npm test            # vitest run (jsdom env, setup in src/tests/setup.ts)
npm test -- src/tests/auth.test.tsx   # single file
```

## Backend Architecture

Layered/clean-architecture style, strictly separated:
- `app/models/` — SQLAlchemy 2.0 declarative models (Enterprise Domain layer). All inherit `Base` from `app/core/database.py`.
- `app/repositories/` — raw DB access per entity (Interface Adapters). No business logic; return ORM objects.
- `app/services/` — business logic/use cases. Compose repositories, raise `AppException` subclasses, own transaction boundaries.
- `app/schemas/` — Pydantic request/response models.
- `app/api/v1/endpoints/` — thin route handlers; one file per resource, aggregated in `app/api/v1/router.py` under `/api/v1`.
- `app/api/deps.py` — all FastAPI dependency providers (DB session, service constructors, auth/permission checks) live here in one file.

### Request flow
`main.py` wires: CORS middleware → custom `audit_middleware` (populates a `ContextVar` in `app/core/context.py` with `user_id`/`ip`/`user_agent` from `x-user-id`/`x-performed-by` headers, used later by the audit listener) → `api_router`. Global exception handlers (`app/core/exceptions.py`) turn `AppException` subclasses, Pydantic `RequestValidationError`, `SQLAlchemyError`, and `StaleDataError` into a consistent `{success, error_code, detail}` JSON shape.

### Auth & permissions (RBAC)
- JWT access tokens (`app/services/auth.py`, `create_access_token`/`decode_access_token`, HS256, short-lived — `ACCESS_TOKEN_EXPIRE_MINUTES`). Opaque, SHA-256-hashed refresh tokens stored in `UserSession` rows, with **refresh token rotation (RTR)**: reuse of an already-rotated token is treated as a replay attack and revokes *all* sessions for that employee.
- Failed logins increment `Employee.failed_login_attempts`; hitting `MAX_LOGIN_ATTEMPTS` locks the account for `LOCKOUT_DURATION_MINUTES`.
- Permissions are `"module:action"` strings (e.g. `orders:view`), many-to-many `Role` ↔ `Permission` via `role_permissions`. Wildcards supported both module and action side (`orders:*`, `*:view`, `*:*`). `Role.name == "Administrator"` or `Role.is_system` bypasses permission checks entirely.
- `app/services/cache.py`'s `permission_cache` (in-memory, process-local `InMemoryPermissionCache`) caches an employee's resolved permission list; warmed on startup (`main.py` lifespan) and invalidated on role/permission changes or session replay detection. **Being in-memory, it does not survive/synchronize across multiple worker processes** — be aware of this if deploying with multiple uvicorn/gunicorn workers.
- Enforce permissions on an endpoint via the `RequirePermission("module:action")` dependency in `app/api/deps.py` (checks cache first, falls back to DB on miss).
- Frontend mirrors this exact wildcard-matching logic independently in `src/components/auth/PermissionGuard.tsx` (`checkPermission`) — keep the two in sync if permission semantics change.

### Data conventions (see `app/models/order.py` as the reference model)
- All primary keys are UUIDv4 (avoids enumeration, avoids cross-env collisions).
- Soft deletes: `is_deleted` + `deleted_at` columns; repositories default to filtering `is_deleted == False` unless `include_deleted=True` or using the `Admin*Repository` variant (see `AdminOrderRepository`).
- Optimistic locking: a `version` integer column with `__mapper_args__ = {"version_id_col": version}`; a concurrent stale write raises SQLAlchemy `StaleDataError`, translated by the global handler into HTTP 409 with `error_code: VERSION_CONFLICT`.
- Money fields use `Numeric`/`Decimal`, never float, to avoid rounding errors.
- Repository `create`/`update`/`delete` methods accept `commit: bool = True` so services can batch multiple writes into one transaction when needed.

### Automatic audit logging
`app/core/database.py` registers a SQLAlchemy `before_flush` event listener that inspects `session.new`/`dirty`/`deleted` on every flush and auto-writes `AuditLog` rows (entity name/id, action, old/new values, who/IP/user-agent from the `audit_context` ContextVar) — **you do not need to manually log CRUD changes**; it happens for every model except `AuditLog` itself. Status-field changes (`status`, `production_stage`, `lead_status`) and `is_deleted` transitions are specially tagged as `STATUS_CHANGE`/`DELETE` actions.

### Adding a new resource end-to-end
Model (`app/models/`) → repository (`app/repositories/`) → service (`app/services/`) → Pydantic schemas (`app/schemas/`) → endpoints (`app/api/v1/endpoints/`) → register router in `app/api/v1/router.py` → add DI providers to `app/api/deps.py` → generate/apply an Alembic migration.

## Frontend Architecture

- `src/app/store.ts` — all Zustand stores in one file: `useAuthStore` (tokens/user/permissions, persisted to `localStorage` or `sessionStorage` depending on "remember me"), `useThemeStore`, `useSidebarStore`, `useNotificationStore` (toasts).
- `src/services/api.ts` — shared Axios instance. Request interceptor injects `Authorization: Bearer`; response interceptor auto-refreshes on 401 (queuing concurrent requests while a refresh is in flight) and logs out on refresh failure. Feature API calls go in `src/services/*.ts` or `src/features/*/api.ts`.
- `src/components/auth/ProtectedRoute.tsx` + `PermissionGuard.tsx` — route- and element-level access control, driven by `useAuthStore().permissions` (see RBAC note above — logic must match backend's `RequirePermission`).
- `src/App.tsx` — central route table; most feature routes are still placeholder `<div>`s pending implementation, each already wrapped in the correct `ProtectedRoute requiredPermission="<module>:view"`.
- `src/features/<name>/` — feature-scoped code (e.g. `dashboard/`: `api.ts`, `hooks.ts`, `types.ts`, `components/`). New features should follow this same internal shape.
- `src/components/ui/` — shared design-system primitives (Button, DataTable, Dialog, etc.) built on Radix UI + Tailwind + `class-variance-authority`; prefer these over ad hoc markup.
- Path alias `@` → `src/` (configured in both `vite.config.ts` and `tsconfig.json`).
