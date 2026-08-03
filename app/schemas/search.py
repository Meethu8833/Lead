"""
app/schemas/search.py

This file defines the Pydantic schemas for the Global Search feature.
Under Clean Architecture, this structured response encapsulates unified search results.
"""

from typing import List
from pydantic import BaseModel
from app.schemas.photographer import PhotographerResponse
from app.schemas.order import OrderResponse
from app.schemas.product import ProductResponse
from app.schemas.invoice import InvoiceResponse


class GlobalSearchResponse(BaseModel):
    """
    Consolidated search results containing matching records across multiple modules.
    """
    photographers: List[PhotographerResponse]
    orders: List[OrderResponse]
    products: List[ProductResponse]
    invoices: List[InvoiceResponse]
