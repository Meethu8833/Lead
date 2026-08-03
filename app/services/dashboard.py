"""
app/services/dashboard.py

Service layer for business dashboard metrics.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import asyncio
from datetime import datetime, time, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem, ProductionStage
from app.models.photographer import Photographer
from app.models.payment import Payment
from app.models.invoice import Invoice, InvoiceStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.notification import NotificationLog, NotificationStatus
from app.schemas.dashboard import DashboardStatsResponse, TopProductResponse, TopCustomerResponse


class DashboardService:
    """
    Service to aggregate key performance metrics (KPIs) for the management dashboard.
    """

    async def get_dashboard_stats(self, db: AsyncSession) -> DashboardStatsResponse:
        """
        Retrieves all key metrics for the business dashboard.
        Executes aggregations concurrently using asyncio.gather.
        """
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=timezone.utc)
        weekly_start = now - timedelta(days=7)
        monthly_start = now - timedelta(days=30)

        # 1. Base dashboard query (Scalar subqueries to fetch counts/sums in a single batch)
        base_query = select(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.received_at >= today_start).scalar_subquery().label("revenue_today"),
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.received_at >= month_start).scalar_subquery().label("revenue_this_month"),
            select(func.count(Payment.id)).where(Payment.received_at >= today_start).scalar_subquery().label("payments_today"),
            select(func.coalesce(func.sum(Order._balance_amount), 0.0)).where(Order.is_deleted == False, Order.status != OrderStatus.CANCELLED, Order._balance_amount > 0.00).scalar_subquery().label("pending_payments"),
            select(func.count(Delivery.id)).join(Order, Order.id == Delivery.order_id).where(Order.is_deleted == False, Delivery.status != DeliveryStatus.DELIVERED).scalar_subquery().label("pending_deliveries"),
            select(func.count(Order.id)).where(Order.is_deleted == False, Order.status == OrderStatus.READY).scalar_subquery().label("orders_ready"),
            select(func.count(Order.id)).where(Order.is_deleted == False, Order.status == OrderStatus.DELIVERED, Order.delivered_at >= today_start).scalar_subquery().label("orders_delivered_today"),
            select(func.count(Invoice.id)).where(Invoice.status != InvoiceStatus.CANCELLED).scalar_subquery().label("invoices_generated"),
            select(func.count(Invoice.id)).where(Invoice.status.notin_([InvoiceStatus.PAID, InvoiceStatus.CANCELLED])).scalar_subquery().label("invoices_pending"),
            select(func.count(NotificationLog.id)).where(NotificationLog.status == NotificationStatus.PENDING).scalar_subquery().label("notifications_pending"),
            select(func.count(NotificationLog.id)).where(NotificationLog.status == NotificationStatus.FAILED).scalar_subquery().label("notifications_failed"),
            
            # New numeric KPIs in main subquery
            select(func.count(Order.id)).where(Order.is_deleted == False, Order.created_at >= today_start).scalar_subquery().label("today_orders"),
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.received_at >= weekly_start).scalar_subquery().label("weekly_revenue"),
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.received_at >= monthly_start).scalar_subquery().label("monthly_revenue"),
            select(func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id).where(Order.is_deleted == False, OrderItem.is_deleted == False, OrderItem.production_stage.notin_([ProductionStage.DELIVERED, ProductionStage.CANCELLED])).scalar_subquery().label("pending_production"),
            select(func.count(Order.id)).where(Order.is_deleted == False, Order.expected_delivery_date < now, Order.status.notin_([OrderStatus.DELIVERED, OrderStatus.CANCELLED])).scalar_subquery().label("delayed_orders"),
            select(func.coalesce(func.avg(Order.total_amount), 0.0)).where(Order.is_deleted == False, Order.status != OrderStatus.CANCELLED).scalar_subquery().label("average_order_value")
        )

        # 2. Top products query
        top_products_query = (
            select(OrderItem.product_name, func.sum(OrderItem.quantity).label("total_qty"))
            .where(OrderItem.is_deleted == False)
            .group_by(OrderItem.product_name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(5)
        )

        # 3. Top customers query
        top_customers_query = (
            select(Photographer.name, func.sum(Order.total_amount).label("total_spent"))
            .join(Order, Order.photographer_id == Photographer.id)
            .where(
                Photographer.is_deleted == False,
                Order.is_deleted == False,
                Order.status != OrderStatus.CANCELLED
            )
            .group_by(Photographer.name)
            .order_by(func.sum(Order.total_amount).desc())
            .limit(5)
        )

        # Run queries sequentially to prevent connection concurrency error
        base_result = await db.execute(base_query)
        top_prod_result = await db.execute(top_products_query)
        top_cust_result = await db.execute(top_customers_query)

        base_row = base_result.fetchone()
        top_prod_rows = top_prod_result.all()
        top_cust_rows = top_cust_result.all()

        # Map top products list
        top_products = [
            TopProductResponse(product_name=row.product_name, total_qty=int(row.total_qty or 0))
            for row in top_prod_rows
        ]

        # Map top customers list
        top_customers = [
            TopCustomerResponse(name=row.name, total_spent=float(row.total_spent or 0.0))
            for row in top_cust_rows
        ]

        # Outstanding balance matches the sum of balances on active orders
        outstanding_balance = float(base_row.pending_payments or 0.0)

        return DashboardStatsResponse(
            revenue_today=float(base_row.revenue_today or 0.0),
            revenue_this_month=float(base_row.revenue_this_month or 0.0),
            payments_today=int(base_row.payments_today or 0),
            pending_payments=outstanding_balance,
            pending_deliveries=int(base_row.pending_deliveries or 0),
            orders_ready=int(base_row.orders_ready or 0),
            orders_delivered_today=int(base_row.orders_delivered_today or 0),
            invoices_generated=int(base_row.invoices_generated or 0),
            invoices_pending=int(base_row.invoices_pending or 0),
            notifications_pending=int(base_row.notifications_pending or 0),
            notifications_failed=int(base_row.notifications_failed or 0),
            
            # New KPIs
            today_orders=int(base_row.today_orders or 0),
            weekly_revenue=float(base_row.weekly_revenue or 0.0),
            monthly_revenue=float(base_row.monthly_revenue or 0.0),
            pending_production=int(base_row.pending_production or 0),
            delayed_orders=int(base_row.delayed_orders or 0),
            top_products=top_products,
            top_customers=top_customers,
            outstanding_balance=outstanding_balance,
            average_order_value=float(base_row.average_order_value or 0.0)
        )
