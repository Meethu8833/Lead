"""
app/schemas/dashboard.py

Pydantic schemas for Business Dashboard.
"""

from typing import List
from pydantic import BaseModel, Field


class TopProductResponse(BaseModel):
    product_name: str
    total_qty: int


class TopCustomerResponse(BaseModel):
    name: str
    total_spent: float


class DashboardStatsResponse(BaseModel):
    revenue_today: float = Field(..., description="Sum of payment amounts received today")
    revenue_this_month: float = Field(..., description="Sum of payment amounts received this month")
    payments_today: int = Field(..., description="Number of payments created today")
    pending_payments: float = Field(..., description="Total outstanding balance amount across all orders")
    pending_deliveries: int = Field(..., description="Number of deliveries currently in dispatch or transit")
    orders_ready: int = Field(..., description="Number of orders marked as READY and waiting for delivery")
    orders_delivered_today: int = Field(..., description="Number of orders delivered today")
    invoices_generated: int = Field(..., description="Total active invoices generated in the system")
    invoices_pending: int = Field(..., description="Number of active invoices that are unpaid")
    notifications_pending: int = Field(..., description="Number of notifications pending delivery")
    notifications_failed: int = Field(..., description="Number of notifications that failed delivery")

    # New KPIs
    today_orders: int = Field(..., description="Number of orders created today")
    weekly_revenue: float = Field(..., description="Sum of payment amounts received in the last 7 days")
    monthly_revenue: float = Field(..., description="Sum of payment amounts received in the last 30 days")
    pending_production: int = Field(..., description="Number of items currently undergoing production")
    delayed_orders: int = Field(..., description="Number of active orders whose delivery expected date has passed")
    top_products: List[TopProductResponse] = Field(..., description="List of top 5 best selling products")
    top_customers: List[TopCustomerResponse] = Field(..., description="List of top 5 photographers by total amount spent")
    outstanding_balance: float = Field(..., description="Outstanding balance across active invoices")
    average_order_value: float = Field(..., description="Average value of non-cancelled orders")
