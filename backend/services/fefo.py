"""
backend/services/fefo.py
─────────────────────────
Pure FEFO (First-Expiry, First-Out) deduction algorithm.

This module has zero HTTP concerns and zero direct DB access.
It receives pre-fetched, pre-sorted batch rows and a connection,
performs the deduction, writes audit logs, and returns a result.

FEFO rule: consume the batch with the earliest expiry date first.
Partial batch consumption is fully supported.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from backend.database import db_deduct_from_batch, db_log_dispensing


# ─────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────

@dataclass
class ConsumedBatch:
    """Records exactly what was taken from one batch."""
    batch_id:       int
    batch_number:   str
    expiry_date:    str
    quantity_taken: int
    remaining:      int


@dataclass
class FefoResult:
    """Outcome of a complete FEFO dispensing operation."""
    medicine_name:   str
    total_dispensed: int
    batches_consumed: list[ConsumedBatch] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Exception
# ─────────────────────────────────────────────────────────────

class InsufficientStockError(Exception):
    """
    Raised when the requested quantity exceeds total available stock.
    Carries context so the API layer can build a meaningful 400 response.
    """

    def __init__(
        self,
        medicine_name: str,
        requested: int,
        available: int,
        existing_batches: list[dict],
    ) -> None:
        self.medicine_name    = medicine_name
        self.requested        = requested
        self.available        = available
        self.existing_batches = existing_batches
        super().__init__(
            f"Insufficient stock for '{medicine_name}': "
            f"requested {requested}, available {available}."
        )


# ─────────────────────────────────────────────────────────────
# Core algorithm
# ─────────────────────────────────────────────────────────────

def run_fefo(
    conn: sqlite3.Connection,
    medicine_id: int,
    medicine_name: str,
    requested_qty: int,
    sorted_batches: list[sqlite3.Row],   # MUST be sorted expiry_date ASC
    sold_at: datetime,
    sale_price: float | None,
) -> FefoResult:
    """
    Execute a FEFO deduction.

    Algorithm
    ---------
    1. Sum available stock across all batches.
       Raise InsufficientStockError immediately if total < requested.
    2. Walk batches in expiry-ascending order.
    3. For each batch: take  min(batch.quantity, still_needed).
    4. Atomically deduct from the batch (db_deduct_from_batch enforces
       zero-negative guarantee at the DB level too).
    5. Write a dispensing_log entry for each partial or full consumption.
    6. Stop as soon as the requested quantity is fulfilled.

    Parameters
    ----------
    conn            Open SQLite connection (caller owns commit/rollback).
    medicine_id     DB primary key of the medicine.
    medicine_name   Human-readable name (for error messages + result).
    requested_qty   Total units the caller wants to dispense.
    sorted_batches  Rows from db_get_batches_fefo — expiry ASC, qty > 0.
    sold_at         Timestamp to record in the dispensing log.
    sale_price      Optional per-unit price for the dispensing log.

    Returns
    -------
    FefoResult with a breakdown of every batch touched.

    Raises
    ------
    InsufficientStockError  if total available stock < requested_qty.
    """
    # Step 1: guard
    total_available = sum(row["quantity"] for row in sorted_batches)
    if total_available < requested_qty:
        raise InsufficientStockError(
            medicine_name=medicine_name,
            requested=requested_qty,
            available=total_available,
            existing_batches=[
                {
                    "batch_number": r["batch_number"],
                    "expiry_date":  r["expiry_date"],
                    "quantity":     r["quantity"],
                }
                for r in sorted_batches
            ],
        )

    # Step 2-6: walk and consume
    still_needed = requested_qty
    consumed: list[ConsumedBatch] = []

    for batch in sorted_batches:
        if still_needed <= 0:
            break

        take = min(batch["quantity"], still_needed)

        # Atomic deduct (raises if somehow goes negative — double safety net)
        new_qty = db_deduct_from_batch(conn, batch_id=batch["id"], qty=take)

        # Audit log
        db_log_dispensing(
            conn,
            medicine_id=medicine_id,
            batch_id=batch["id"],
            qty_taken=take,
            remaining=new_qty,
            sale_price=sale_price,
            sold_at=sold_at,
        )

        consumed.append(ConsumedBatch(
            batch_id=batch["id"],
            batch_number=batch["batch_number"],
            expiry_date=batch["expiry_date"],
            quantity_taken=take,
            remaining=new_qty,
        ))

        still_needed -= take

    return FefoResult(
        medicine_name=medicine_name,
        total_dispensed=requested_qty,
        batches_consumed=consumed,
    )