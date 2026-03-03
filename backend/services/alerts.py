"""
backend/services/alerts.py
───────────────────────────
Alert and monitoring service.

Responsibilities:
  - Low-stock detection (configurable threshold or per-medicine minimum)
  - Near-expiry batch detection (configurable days window)
  - Urgency classification for expiry alerts

No HTTP concerns here. All DB calls go through database.py helpers.
"""

from __future__ import annotations

from datetime import date, timedelta

from backend.database import (
    db_get_expiry_alerts,
    db_get_low_stock,
    get_db,
)
from backend.models import ExpiryAlert, LowStockAlert


# ─────────────────────────────────────────────────────────────
# Urgency classification
# ─────────────────────────────────────────────────────────────

def _urgency(days_left: int) -> str:
    """
    Classify expiry urgency based on days remaining.

    expired  -> already past expiry date
    critical -> expires within 7 days
    warning  -> expires within 30 days
    watch    -> expires within the alert window (> 30 days)
    """
    if days_left < 0:
        return "expired"
    if days_left <= 7:
        return "critical"
    if days_left <= 30:
        return "warning"
    return "watch"


# ─────────────────────────────────────────────────────────────
# Service functions
# ─────────────────────────────────────────────────────────────

def svc_low_stock(threshold: int | None = None) -> list[LowStockAlert]:
    """
    Return medicines whose total stock is at or below the given threshold.

    If threshold is None, each medicine's individually configured
    min_stock_level is used as the threshold — making this a
    "per-medicine alert" rather than a global one.

    Results are sorted by total_stock ascending (most urgent first).

    Parameters
    ----------
    threshold   Optional override (e.g. ?threshold=20 from the query string).
                Pass None to use per-medicine minimums.
    """
    with get_db() as conn:
        rows = db_get_low_stock(conn, threshold)

    return [
        LowStockAlert(
            id=r["id"],
            name=r["name"],
            category=r["category"],
            total_stock=r["total_stock"],
            min_stock_level=r["min_stock_level"],
            shortage=max(0, r["min_stock_level"] - r["total_stock"]),
            batches=r["batch_count"],
        )
        for r in rows
    ]


def svc_expiry_alerts(days: int = 30) -> list[ExpiryAlert]:
    """
    Return batches that expire within the next `days` calendar days
    and still have stock remaining.

    Each alert includes an urgency label:
      "expired"  — already past expiry (data integrity concern)
      "critical" — expires within 7 days
      "warning"  — expires within 30 days
      "watch"    — expires within the requested window (> 30 days)

    Results are sorted by expiry_date ascending (most urgent first).

    Parameters
    ----------
    days    Look-ahead window in calendar days (default 30).
            Use a large value (e.g. 365) to see all future expiries.
    """
    with get_db() as conn:
        rows = db_get_expiry_alerts(conn, days)

    return [
        ExpiryAlert(
            batch_id=r["batch_id"],
            medicine_name=r["medicine_name"],
            category=r["category"],
            batch_number=r["batch_number"],
            expiry_date=r["expiry_date"],
            quantity=r["quantity"],
            days_left=r["days_left"],
            urgency=_urgency(r["days_left"]),
        )
        for r in rows
    ]