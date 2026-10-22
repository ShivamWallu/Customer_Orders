"""
Khandelia Oil & General Mills Pvt. Ltd.
Enterprise Asynchronous Database Engine (SQLAlchemy 2.0 + asyncpg / aiosqlite)
Engineered for High-Concurrency Multi-Core Scale (1M - 10M Scale Architecture)
Features:
- Primary Write Engine & Read-Replica Engine separation
- High-Performance Connection Pooling (PgBouncer-compatible)
- Comprehensive composite indexes for microsecond query latency
- Cursor-based & offset pagination to eliminate memory spikes
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Float, Text, Boolean, Index, select, update, delete, desc, and_, or_, func
)
from config import settings
from logger_service import logger

Base = declarative_base()

# ----------------- SQLALCHEMY 2.0 DECLARATIVE MODELS & INDEXES -----------------

class OrderModel(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    party_address: Mapped[Optional[str]] = mapped_column(Text)
    delivery_address: Mapped[Optional[str]] = mapped_column(Text)
    sales_person: Mapped[Optional[str]] = mapped_column(String(128))
    order_date: Mapped[Optional[str]] = mapped_column(String(64))
    formatted_timestamp: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    total_boxes: Mapped[int] = mapped_column(Integer, default=0)
    total_pieces: Mapped[int] = mapped_column(Integer, default=0)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    items_summary: Mapped[Optional[str]] = mapped_column(Text)
    slip_image_path: Mapped[Optional[str]] = mapped_column(String(255))
    slip_image_url: Mapped[Optional[str]] = mapped_column(String(512))
    synced_to_sheet: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[Optional[str]] = mapped_column(String(64))
    whatsapp_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    whatsapp_sent_at: Mapped[Optional[str]] = mapped_column(String(64))
    party_code: Mapped[Optional[str]] = mapped_column(String(64))
    data_consent: Mapped[int] = mapped_column(Integer, default=1)
    order_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    so_number: Mapped[Optional[str]] = mapped_column(String(64))
    confirmed_at: Mapped[Optional[str]] = mapped_column(String(64))
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(64), default="Unit 1")

    # High-Frequency Query & Reporting Composite Indexes
    __table_args__ = (
        Index("idx_orders_created", "created_at"),
        Index("idx_orders_party", "party_name"),
        Index("idx_orders_party_code", "party_code"),
        Index("idx_orders_sales_person", "sales_person"),
        Index("idx_orders_status", "order_status"),
        Index("idx_orders_unit", "unit"),
        Index("idx_orders_so_number", "so_number"),
        Index("idx_orders_wa_status", "whatsapp_status"),
        Index("idx_orders_synced", "synced_to_sheet"),
        # Composite Indexes for Instant ASM & Customer Order History
        Index("idx_orders_asm_history", "sales_person", "created_at"),
        Index("idx_orders_cust_history", "party_code", "created_at"),
        Index("idx_orders_unit_status", "unit", "order_status"),
    )


class CustomerCRMModel(Base):
    __tablename__ = "customers_crm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_code: Mapped[Optional[str]] = mapped_column(String(64))
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line1: Mapped[Optional[str]] = mapped_column(Text)
    address_line2: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(128))
    state: Mapped[Optional[str]] = mapped_column(String(128))
    pincode: Mapped[Optional[str]] = mapped_column(String(32))
    full_address: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(String(128))
    phone1: Mapped[Optional[str]] = mapped_column(String(64))
    phone2: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64))
    is_custom: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_crm_party_name", "party_name"),
        Index("idx_crm_party_code", "party_code"),
        Index("idx_crm_phone1", "phone1"),
        Index("idx_crm_phone2", "phone2"),
        Index("idx_crm_email", "email"),
    )


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    party_code: Mapped[Optional[str]] = mapped_column(String(64), default="")
    party_name: Mapped[Optional[str]] = mapped_column(String(255), default="")
    assigned_units: Mapped[str] = mapped_column(String(255), default="Unit 1")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), default="SUPER_ADMIN")

    __table_args__ = (
        Index("idx_users_phone", "phone"),
        Index("idx_users_role", "role"),
        Index("idx_users_status", "status"),
    )


class UnitModel(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    unit_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("idx_units_code", "unit_code"),
        Index("idx_units_status", "status"),
    )


class AdminSessionModel(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(64), default="ADMIN")
    assigned_units: Mapped[Optional[str]] = mapped_column(String(255), default="ALL")

    __table_args__ = (
        Index("idx_admin_token", "token"),
    )


class CustomerSessionModel(Base):
    __tablename__ = "customer_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_name: Mapped[Optional[str]] = mapped_column(String(128))
    party_code: Mapped[Optional[str]] = mapped_column(String(64))
    party_name: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("idx_cust_token", "token"),
        Index("idx_cust_phone", "phone"),
    )


class SalesManagerSessionModel(Base):
    __tablename__ = "sales_manager_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    manager_name: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("idx_mgr_token", "token"),
        Index("idx_mgr_phone", "phone"),
    )


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(128))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    role: Mapped[Optional[str]] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS")
    details: Mapped[Optional[str]] = mapped_column(Text)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[Optional[str]] = mapped_column(String(64))

    __table_args__ = (
        Index("idx_audit_created", "created_at"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_phone", "phone"),
        Index("idx_audit_role", "role"),
    )


class RolePermissionModel(Base):
    __tablename__ = "role_permissions"

    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    can_add_order: Mapped[int] = mapped_column(Integer, default=1)
    can_edit_unit: Mapped[int] = mapped_column(Integer, default=1)
    can_confirm_so: Mapped[int] = mapped_column(Integer, default=1)
    can_delete_order: Mapped[int] = mapped_column(Integer, default=1)
    can_block_user: Mapped[int] = mapped_column(Integer, default=1)
    can_manage_units: Mapped[int] = mapped_column(Integer, default=1)
    can_view_logs: Mapped[int] = mapped_column(Integer, default=1)
    can_export_csv: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), default="SYSTEM")


# ----------------- ASYNC DATABASE ENGINE & CONNECTION POOL -----------------

def create_engine_for_url(db_url: str):
    """Creates an AsyncEngine with PgBouncer / high-concurrency pooling parameters"""
    is_sqlite = db_url.startswith("sqlite")
    
    if is_sqlite:
        return create_async_engine(
            db_url,
            echo=settings.DEBUG,
            connect_args={"check_same_thread": False}
        )
    else:
        # PostgreSQL / asyncpg with enterprise connection pooler
        return create_async_engine(
            db_url,
            echo=settings.DEBUG,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True
        )

# Primary Write Engine
async_engine_write = create_engine_for_url(settings.ASYNC_DATABASE_URL)
AsyncSessionWrite = async_sessionmaker(
    bind=async_engine_write,
    class_=AsyncSession,
    expire_on_commit=False
)

# Optional Read Replica Engine (falls back to Write Engine if not provided)
if settings.ASYNC_READ_REPLICA_URL:
    async_engine_read = create_engine_for_url(settings.ASYNC_READ_REPLICA_URL)
    logger.info(f"Read-Replica Engine initialized for URL: {settings.ASYNC_READ_REPLICA_URL}")
else:
    async_engine_read = async_engine_write

AsyncSessionRead = async_sessionmaker(
    bind=async_engine_read,
    class_=AsyncSession,
    expire_on_commit=False
)

async def init_async_db():
    """Initializes tables asynchronously if they do not exist"""
    async with async_engine_write.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Async database schema & indexes verified successfully")

async def check_db_health() -> bool:
    """Microsecond database ping for load balancer health checks"""
    try:
        async with AsyncSessionRead() as session:
            await session.execute(select(func.count(OrderModel.order_id)))
        return True
    except Exception as e:
        logger.error(f"Database healthcheck failed: {e}")
        return False


# ----------------- ASYNC BUSINESS LOGIC & CONCURRENCY OPTIMIZATIONS -----------------

async def async_save_order(order_data: Dict[str, Any]) -> str:
    """Saves a new order asynchronously with zero-data-loss commit guarantee"""
    order_id = order_data.get("order_id") or order_data.get("orderId")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    order_obj = OrderModel(
        order_id=order_id,
        party_name=order_data.get("party_name") or order_data.get("partyName", "Unknown"),
        party_address=order_data.get("party_address") or order_data.get("partyAddress", ""),
        delivery_address=order_data.get("delivery_address") or order_data.get("deliveryAddress", ""),
        sales_person=order_data.get("sales_person") or order_data.get("salesPerson", "Self / Online"),
        order_date=order_data.get("order_date") or order_data.get("orderDate", now_str),
        formatted_timestamp=order_data.get("formatted_timestamp") or order_data.get("formattedTimestamp", now_str),
        created_at=order_data.get("created_at") or now_str,
        total_boxes=int(order_data.get("total_boxes") or order_data.get("totalBoxes", 0)),
        total_pieces=int(order_data.get("total_pieces") or order_data.get("totalPieces", 0)),
        items_json=json.dumps(order_data.get("items") or order_data.get("items_json") or []),
        items_summary=order_data.get("items_summary") or order_data.get("itemsSummary", ""),
        slip_image_path=order_data.get("slip_image_path") or order_data.get("slipImagePath", ""),
        slip_image_url=order_data.get("slip_image_url") or order_data.get("slipImageUrl", ""),
        synced_to_sheet=0,
        whatsapp_status="PENDING",
        party_code=order_data.get("party_code") or order_data.get("partyCode", ""),
        data_consent=int(order_data.get("data_consent", 1)),
        order_status=order_data.get("order_status") or order_data.get("orderStatus", "PENDING"),
        so_number=order_data.get("so_number") or order_data.get("soNumber", ""),
        unit=order_data.get("unit", "Unit 1")
    )

    async with AsyncSessionWrite() as session:
        async with session.begin():
            session.add(order_obj)
    
    return order_id


async def async_get_orders_paginated(
    sales_person: Optional[str] = None,
    party_code: Optional[str] = None,
    unit: Optional[str] = None,
    status: Optional[str] = None,
    has_so: Optional[bool] = None,
    search_query: Optional[str] = None,
    page: int = 1,
    limit: int = 25,
    cursor_created_at: Optional[str] = None
) -> Dict[str, Any]:
    """
    High-concurrency paginated & cursor-based order queries.
    Prevents memory spikes by streaming only required slices.
    """
    async with AsyncSessionRead() as session:
        query = select(OrderModel)
        count_query = select(func.count(OrderModel.order_id))
        filters = []

        if sales_person and sales_person != "ALL":
            filters.append(OrderModel.sales_person.ilike(sales_person.strip()))
        if party_code:
            filters.append(OrderModel.party_code == party_code)
        if unit and unit != "ALL":
            filters.append(OrderModel.unit == unit)
        if status and status != "ALL":
            filters.append(OrderModel.order_status == status)
        if has_so is True:
            filters.append(and_(OrderModel.so_number.isnot(None), OrderModel.so_number != "", OrderModel.so_number != "-"))
        elif has_so is False:
            filters.append(or_(OrderModel.so_number.is_(None), OrderModel.so_number == "", OrderModel.so_number == "-"))
        if search_query:
            term = f"%{search_query.strip()}%"
            filters.append(
                or_(
                    OrderModel.party_name.ilike(term),
                    OrderModel.party_code.ilike(term),
                    OrderModel.so_number.ilike(term),
                    OrderModel.order_id.ilike(term)
                )
            )

        # High-performance cursor pagination if provided
        if cursor_created_at:
            filters.append(OrderModel.created_at < cursor_created_at)

        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        # Total count
        total_count_res = await session.execute(count_query)
        total_count = total_count_res.scalar() or 0

        # Sorting by created_at descending (utilizes idx_orders_created)
        query = query.order_by(desc(OrderModel.created_at))

        # Apply offset pagination if cursor is not used
        if not cursor_created_at:
            offset = max(0, (page - 1) * limit)
            query = query.offset(offset).limit(limit)
        else:
            query = query.limit(limit)

        result = await session.execute(query)
        orders = result.scalars().all()

        order_list = []
        next_cursor = None
        for o in orders:
            try:
                items = json.loads(o.items_json) if o.items_json else []
            except Exception:
                items = []

            item_dict = {
                "order_id": o.order_id,
                "orderId": o.order_id,
                "cleanId": o.order_id.split("-")[-1] if "-" in o.order_id else o.order_id,
                "party_name": o.party_name,
                "partyName": o.party_name,
                "party_code": o.party_code,
                "partyCode": o.party_code,
                "party_address": o.party_address,
                "partyAddress": o.party_address,
                "delivery_address": o.delivery_address,
                "deliveryAddress": o.delivery_address,
                "sales_person": o.sales_person,
                "salesPerson": o.sales_person,
                "order_date": o.order_date,
                "orderDate": o.order_date,
                "formatted_timestamp": o.formatted_timestamp,
                "formattedTimestamp": o.formatted_timestamp,
                "created_at": o.created_at,
                "createdAt": o.created_at,
                "total_boxes": o.total_boxes,
                "totalBoxes": o.total_boxes,
                "total_pieces": o.total_pieces,
                "totalPieces": o.total_pieces,
                "items": items,
                "items_summary": o.items_summary,
                "itemsSummary": o.items_summary,
                "slip_image_url": o.slip_image_url,
                "slipImageUrl": o.slip_image_url,
                "order_status": o.order_status,
                "orderStatus": o.order_status,
                "so_number": o.so_number,
                "soNumber": o.so_number,
                "confirmed_at": o.confirmed_at,
                "confirmed_by": o.confirmed_by,
                "unit": o.unit,
                "synced_to_sheet": o.synced_to_sheet,
                "whatsapp_status": o.whatsapp_status
            }
            order_list.append(item_dict)
            next_cursor = o.created_at

        return {
            "orders": order_list,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": (total_count + limit - 1) // limit if limit > 0 else 1,
            "next_cursor": next_cursor if len(order_list) == limit else None
        }


async def async_search_customers(query_text: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Ultra-fast indexed lookup across 900+ B2B party codes and names"""
    clean_q = (query_text or "").strip()
    if not clean_q:
        return []

    async with AsyncSessionRead() as session:
        term = f"%{clean_q}%"
        stmt = select(CustomerCRMModel).where(
            or_(
                CustomerCRMModel.party_name.ilike(term),
                CustomerCRMModel.party_code.ilike(term),
                CustomerCRMModel.phone1.ilike(term),
                CustomerCRMModel.phone2.ilike(term)
            )
        ).limit(limit)

        result = await session.execute(stmt)
        customers = result.scalars().all()

        return [
            {
                "id": c.id,
                "party_code": c.party_code or "",
                "party_name": c.party_name or "",
                "address": c.full_address or f"{c.address_line1 or ''} {c.city or ''} {c.state or ''}".strip(),
                "phone": c.phone1 or c.phone2 or "",
                "phone1": c.phone1 or "",
                "phone2": c.phone2 or "",
                "email": c.email or "",
                "city": c.city or "",
                "state": c.state or "",
                "pincode": c.pincode or ""
            }
            for c in customers
        ]


async def async_get_all_units() -> List[Dict[str, Any]]:
    """Retrieves all active warehouse units"""
    async with AsyncSessionRead() as session:
        stmt = select(UnitModel).order_by(UnitModel.id)
        result = await session.execute(stmt)
        units = result.scalars().all()
        return [
            {
                "id": u.id,
                "unit_code": u.unit_code,
                "unit_name": u.unit_name,
                "description": u.description,
                "status": u.status
            }
            for u in units
        ]


async def async_confirm_order(order_id: str, so_number: str, confirmed_by: str = "ADMIN") -> bool:
    """Updates SO number and marks order as CONFIRMED"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with AsyncSessionWrite() as session:
        async with session.begin():
            stmt = update(OrderModel).where(OrderModel.order_id == order_id).values(
                order_status="CONFIRMED",
                so_number=so_number.strip(),
                confirmed_at=now_str,
                confirmed_by=confirmed_by
            )
            result = await session.execute(stmt)
            return result.rowcount > 0


async def async_update_order_unit(order_id: str, new_unit: str) -> bool:
    """Reallocates order to a specific manufacturing unit"""
    async with AsyncSessionWrite() as session:
        async with session.begin():
            stmt = update(OrderModel).where(OrderModel.order_id == order_id).values(
                unit=new_unit.strip()
            )
            result = await session.execute(stmt)
            return result.rowcount > 0


async def async_delete_order(order_id: str) -> bool:
    """Deletes order from database"""
    async with AsyncSessionWrite() as session:
        async with session.begin():
            stmt = delete(OrderModel).where(OrderModel.order_id == order_id)
            result = await session.execute(stmt)
            return result.rowcount > 0


async def async_log_audit(
    action: str,
    user_name: Optional[str] = None,
    phone: Optional[str] = None,
    role: Optional[str] = None,
    status: str = "SUCCESS",
    details: Optional[str] = None,
    ip_address: Optional[str] = None
) -> None:
    """Records audit trail event asynchronously"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_obj = AuditLogModel(
        user_name=user_name,
        phone=phone,
        role=role,
        action=action,
        status=status,
        details=details,
        ip_address=ip_address,
        created_at=now_str,
        timestamp=now_str
    )
    async with AsyncSessionWrite() as session:
        async with session.begin():
            session.add(log_obj)


async def async_get_dashboard_stats() -> Dict[str, Any]:
    """Calculates KPI statistics across millions of orders using indexed queries"""
    async with AsyncSessionRead() as session:
        # Total orders count
        total_res = await session.execute(select(func.count(OrderModel.order_id)))
        total_orders = total_res.scalar() or 0

        # Pending orders count
        pending_res = await session.execute(
            select(func.count(OrderModel.order_id)).where(OrderModel.order_status == "PENDING")
        )
        pending_orders = pending_res.scalar() or 0

        # Confirmed orders count
        confirmed_res = await session.execute(
            select(func.count(OrderModel.order_id)).where(OrderModel.order_status == "CONFIRMED")
        )
        confirmed_orders = confirmed_res.scalar() or 0

        # Total boxes
        boxes_res = await session.execute(select(func.sum(OrderModel.total_boxes)))
        total_boxes = boxes_res.scalar() or 0

        # Total pieces
        pieces_res = await session.execute(select(func.sum(OrderModel.total_pieces)))
        total_pieces = pieces_res.scalar() or 0

        return {
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "confirmed_orders": confirmed_orders,
            "total_boxes": int(total_boxes),
            "total_pieces": int(total_pieces)
        }
