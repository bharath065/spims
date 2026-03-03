"""
backend/services/reorder.py
────────────────────────────
Reorder suggestion engine.

Responsibilities:
  - Identify medicines that need restocking
  - Calculate suggested order quantities
  - Log confirmed reorder intentions to reorder_logs
  - (Extensible: plug in ML velocity-based logic later)

No HTTP concerns here. All DB calls go through database.py helpers.
"""

from __future__ import annotations

from backend.database import (
    db_get_medicine_by_name,
    db_get_reorder_candidates,
    db_get_supplier_by_name,
    db_log_reorder,
    get_db,
)
from backend.models import ReorderSuggestion


# ─────────────────────────────────────────────────────────────
# Reorder quantity heuristic
# ─────────────────────────────────────────────────────────────

def _suggested_quantity(current: int, minimum: int) -> int:
    """
    Simple reorder quantity heuristic.

    Strategy: top up to 2× the minimum level, minus what's already on hand.
    This gives a ~1 full reorder cycle of buffer above the minimum.

    Example:  current=10, minimum=100  ->  order 190
              current=0,  minimum=50   ->  order 100
              current=45, minimum=50   ->  order 55

    In production, replace or extend this with a velocity-based formula:
        reorder_qty = avg_daily_sales * lead_days * safety_factor - current
    """
    target = minimum * 2
    return max(minimum, target - current)


# ─────────────────────────────────────────────────────────────
# Service functions
# ─────────────────────────────────────────────────────────────

def svc_get_reorder_suggestions() -> list[ReorderSuggestion]:
    """
    Return a reorder suggestion for every medicine whose total stock
    is at or below its configured min_stock_level.

    Each suggestion includes:
      - current_stock     what is physically on the shelf right now
      - min_stock_level   the configured safety threshold
      - suggested_quantity units to order to reach 2× the minimum
      - preferred_supplier the supplier used most often for this medicine
      - lead_days         that supplier's typical delivery time

    Results are sorted by current_stock ascending (most critical first).
    """
    with get_db() as conn:
        rows = db_get_reorder_candidates(conn)

    return [
        ReorderSuggestion(
            medicine_id=r["id"],
            medicine_name=r["name"],
            category=r["category"],
            current_stock=r["current_stock"],
            min_stock_level=r["min_stock_level"],
            suggested_quantity=_suggested_quantity(
                r["current_stock"], r["min_stock_level"]
            ),
            preferred_supplier=r["preferred_supplier"],
            lead_days=r["lead_days"],
        )
        for r in rows
    ]


def svc_trigger_reorder(
    medicine_name: str,
    quantity: int,
    supplier_name: str | None = None,
    triggered_by: str = "manual",
) -> dict:
    """
    Log a confirmed reorder intent to the reorder_logs table.

    This does NOT place an actual purchase order — it records the
    intent so operations staff and future integrations can act on it.

    Parameters
    ----------
    medicine_name   Exact medicine name (case-insensitive lookup).
    quantity        Number of units to order.
    supplier_name   Optional preferred supplier override.
                    Falls back to the medicine's most-used supplier.
    triggered_by    Who/what initiated the reorder: "manual" | "system" | "ml".

    Returns
    -------
    dict with confirmation details.

    Raises
    ------
    ValueError  if the medicine or supplier name is not found.
    """
    with get_db() as conn:
        med = db_get_medicine_by_name(conn, medicine_name)
        if not med:
            raise ValueError(f"Medicine '{medicine_name}' not found.")

        sup_id = None
        if supplier_name:
            sup = db_get_supplier_by_name(conn, supplier_name)
            if not sup:
                raise ValueError(f"Supplier '{supplier_name}' not found.")
            sup_id = sup["id"]

        db_log_reorder(
            conn,
            medicine_id=med["id"],
            supplier_id=sup_id,
            quantity=quantity,
            triggered_by=triggered_by,
        )

    return {
        "status":        "reorder_logged",
        "medicine_name": medicine_name,
        "quantity":      quantity,
        "supplier":      supplier_name,
        "triggered_by":  triggered_by,
    }