"""
app/api/v1/router.py

This file aggregates all endpoint routers for version 1 (v1) of the CRM API.
Grouping endpoints under versioned routers (e.g., `/api/v1`) ensures that future updates
can introduce breaking changes (e.g., by creating `/api/v2`) without breaking older clients
already integrated with v1 endpoints.
"""

from fastapi import APIRouter
from app.api.v1.endpoints import (
    health,
    photographers,
    orders,
    products,
    order_items,
    production,
    payments,
    invoices,
    deliveries,
    notifications,
    dashboard,
    inventory,
    attachments,
    search,
    auth,
    employees,
)

api_router = APIRouter()


# Include endpoint sub-routers under specific URL prefixes and tags
api_router.include_router(
    health.router,
    prefix="/health",
    tags=["system-diagnostics"]
)

api_router.include_router(
    photographers.router,
    prefix="/photographers",
    tags=["photographers"]
)

api_router.include_router(
    orders.router,
    prefix="/orders",
    tags=["orders"]
)

api_router.include_router(
    products.router,
    prefix="/products",
    tags=["products"]
)

api_router.include_router(
    order_items.router,
    prefix="",
    tags=["order-items"]
)

api_router.include_router(
    production.router,
    prefix="",
    tags=["production"]
)

api_router.include_router(
    payments.router,
    prefix="",
    tags=["payments"]
)

api_router.include_router(
    invoices.router,
    prefix="",
    tags=["invoices"]
)

api_router.include_router(
    deliveries.router,
    prefix="",
    tags=["deliveries"]
)

api_router.include_router(
    notifications.router,
    prefix="",
    tags=["notifications"]
)

api_router.include_router(
    dashboard.router,
    prefix="",
    tags=["dashboard"]
)

api_router.include_router(
    inventory.router,
    prefix="/inventory",
    tags=["inventory"]
)

api_router.include_router(
    attachments.router,
    prefix="/attachments",
    tags=["attachments"]
)

api_router.include_router(
    search.router,
    prefix="/search",
    tags=["search"]
)

api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["auth"]
)

api_router.include_router(
    employees.router,
    prefix="/employees",
    tags=["employees"]
)



