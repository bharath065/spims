"""
backend/services/inventory.py
──────────────────────────────
High-level inventory operations: add stock, sell (FEFO), adjust.

Orchestration rules:
  - Open ONE connection per operation (with get_db()).
  - Call database helpers for all SQL.
  - Call fefo.run_fefo() for dispensing logic.
  - Map raw DB rows to Pydantic response models.
  - Raise ValueError for domain errors (caught in main.py -> HTTP 400).
"""

from __future__ import annotations

from datetime import date, datetime

from backend.database import (
    db_adjust_batch,
    db_get_all_batches,
    db_get_batches_fefo,
    db_get_medicine_by_name,
    db_get_supplier_by_name,
    db_upsert_batch,
    get_db,
)
from backend.models import (
    AddStockRequest,
    AddStockResponse,
    AdjustRequest,
    AdjustResponse,
    BatchInfo,
    SellRequest,
    SellResponse,
    SellResponseBatch,
)
from backend.services.fefo import InsufficientStockError, run_fefo


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _days_until(expiry_iso: str) -> int:
    try:
        return (date.fromisoformat(expiry_iso) - date.today()).days
    except ValueError:
        return 0


def _require_medicine(conn, name: str):
    """Fetch medicine by name or raise ValueError."""
    med = db_get_medicine_by_name(conn, name)
    if not med:
        raise ValueError(f"Medicine '{name}' not found.")
    return med


# ─────────────────────────────────────────────────────────────
# Service functions
# ─────────────────────────────────────────────────────────────

def svc_get_batches(medicine_name: str) -> list[BatchInfo]:
    """
    Return all batches for a medicine, sorted by expiry date ascending.
    Includes empty batches so staff can see the full batch history.
    """
    with get_db() as conn:
        med  = _require_medicine(conn, medicine_name)
        rows = db_get_all_batches(conn, med["id"])

    return [
        BatchInfo(
            id=r["id"],
            batch_number=r["batch_number"],
            expiry_date=r["expiry_date"],
            quantity=r["quantity"],
            unit_cost=r["unit_cost"],
            supplier_name=r["supplier_name"],
            days_until_expiry=_days_until(r["expiry_date"]),
        )
        for r in rows
    ]


def svc_add_stock(req: AddStockRequest) -> AddStockResponse:
    """
    Insert a new batch or add quantity to an existing one.
    If batch_number already exists for this medicine, quantities are summed.
    Expiry date is updated to the new value on upsert.
    """
    with get_db() as conn:
        med = _require_medicine(conn, req.medicine_name)

        # Optional: resolve supplier
        sup_id = None
        if req.supplier_name:
            sup = db_get_supplier_by_name(conn, req.supplier_name)
            if sup:
                sup_id = sup["id"]

        db_upsert_batch(
            conn,
            medicine_id=med["id"],
            supplier_id=sup_id,
            batch_number=req.batch_number,
            expiry_date=req.expiry_date.isoformat(),
            quantity=req.quantity,
            unit_cost=req.unit_cost,
        )

        # Read back the final quantity after upsert
        row = conn.execute(
            "SELECT quantity FROM batches WHERE medicine_id = ? AND batch_number = ?",
            (med["id"], req.batch_number),
        ).fetchone()

    return AddStockResponse(
        medicine_name=req.medicine_name,
        batch_number=req.batch_number,
        expiry_date=req.expiry_date.isoformat(),
        new_quantity=row["quantity"],
    )


def svc_sell(req: SellRequest) -> SellResponse:
    """
    Dispense medicine using FEFO.

    Opens a single connection so the entire deduction
    (across potentially multiple batches) is one atomic transaction.
    Raises InsufficientStockError if total stock < requested quantity.
    """
    sold_at = req.sold_at or datetime.now()

    with get_db() as conn:
        med     = _require_medicine(conn, req.medicine_name)
        batches = db_get_batches_fefo(conn, med["id"])   # expiry ASC

        result = run_fefo(
            conn=conn,
            medicine_id=med["id"],
            medicine_name=req.medicine_name,
            requested_qty=req.quantity,
            sorted_batches=batches,
            sold_at=sold_at,
            sale_price=req.sale_price,
        )

    return SellResponse(
        medicine_name=result.medicine_name,
        total_dispensed=result.total_dispensed,
        batches_consumed=[
            SellResponseBatch(
                batch_number=c.batch_number,
                expiry_date=c.expiry_date,
                quantity_taken=c.quantity_taken,
                remaining=c.remaining,
            )
            for c in result.batches_consumed
        ],
    )


def svc_adjust(req: AdjustRequest) -> AdjustResponse:
    """
    Manual stock correction (return, damage, count discrepancy).
    delta > 0 → add units.
    delta < 0 → remove units (blocked if result would be negative).
    """
    with get_db() as conn:
        med = _require_medicine(conn, req.medicine_name)
        new_qty = db_adjust_batch(
            conn,
            medicine_id=med["id"],
            batch_number=req.batch_number,
            delta=req.delta,
            reason=req.reason,
        )

    return AdjustResponse(
        medicine_name=req.medicine_name,
        batch_number=req.batch_number,
        delta=req.delta,
        new_quantity=new_qty,
        reason=req.reason,
    )