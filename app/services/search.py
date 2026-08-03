"""
app/services/search.py

This file implements the SearchService.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import asyncio
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.photographer import Photographer
from app.models.order import Order
from app.models.product import Product
from app.models.invoice import Invoice


class SearchService:
    """
    Service containing global unified search capabilities across entities.
    """

    async def global_search(self, db: AsyncSession, query: str, limit: int = 10) -> dict:
        """
        Searches Photographers, Orders, Products, and Invoices simultaneously.
        """
        q = query.strip()
        if not q:
            return {
                "photographers": [],
                "orders": [],
                "products": [],
                "invoices": [],
            }

        # 1. Photographer query
        photographers_query = (
            select(Photographer)
            .where(
                Photographer.is_deleted == False,
                or_(
                    Photographer.name.ilike(f"%{q}%"),
                    Photographer.phone.ilike(f"%{q}%"),
                    Photographer.city.ilike(f"%{q}%"),
                    Photographer.studio_name.ilike(f"%{q}%"),
                ),
            )
            .limit(limit)
        )

        # 2. Order query
        orders_query = (
            select(Order)
            .where(
                Order.is_deleted == False,
                or_(
                    Order.order_number.ilike(f"%{q}%"),
                    Order.job_name.ilike(f"%{q}%"),
                ),
            )
            .limit(limit)
        )

        # 3. Product query
        products_query = (
            select(Product)
            .where(
                Product.is_deleted == False,
                or_(
                    Product.name.ilike(f"%{q}%"),
                    Product.category.ilike(f"%{q}%"),
                ),
            )
            .limit(limit)
        )

        # 4. Invoice query
        invoices_query = (
            select(Invoice)
            .where(Invoice.invoice_number.ilike(f"%{q}%"))
            .limit(limit)
        )

        # Run queries sequentially to prevent connection concurrency error
        photographers_result = await db.execute(photographers_query)
        orders_result = await db.execute(orders_query)
        products_result = await db.execute(products_query)
        invoices_result = await db.execute(invoices_query)

        photographers = photographers_result.scalars().all()
        orders = orders_result.scalars().all()
        products = products_result.scalars().all()
        invoices = invoices_result.scalars().all()

        return {
            "photographers": photographers,
            "orders": orders,
            "products": products,
            "invoices": invoices,
        }
