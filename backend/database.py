"""
backend/database.py
───────────────────
SQLite connection factory and ALL raw database operations.

Design rules:
  - One connection per request, opened inside a context manager.
  - WAL mode + busy_timeout for safe concurrent access.
  - Every query uses parameterised placeholders (no string interpolation).
  - No business logic here — only SQL + connection management.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Generator

DB_PATH = os.environ.get("PHARMAI_DB", "pharmacy.db")

# ─────────────────────────────────────────────────────────────
# Connection factory
# ─────────────────────────────────────────────────────────────

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a WAL-mode SQLite connection.
    Commits on clean exit, rolls back on any exception, always closes.

    Usage:
        with get_db() as conn:
            conn.execute("SELECT 1")
    """
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=3000")  # wait up to 3 s on lock
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# Schema + seed
# ─────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS medicines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    category        TEXT    NOT NULL DEFAULT 'General',
    unit            TEXT    NOT NULL DEFAULT 'tablet',
    description     TEXT,
    min_stock_level INTEGER NOT NULL DEFAULT 50,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suppliers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    contact    TEXT,
    email      TEXT,
    lead_days  INTEGER NOT NULL DEFAULT 7
);

CREATE TABLE IF NOT EXISTS batches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id  INTEGER NOT NULL REFERENCES medicines(id),
    supplier_id  INTEGER REFERENCES suppliers(id),
    batch_number TEXT    NOT NULL,
    expiry_date  TEXT    NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity >= 0),
    unit_cost    REAL,
    received_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (medicine_id, batch_number)
);

CREATE TABLE IF NOT EXISTS dispensing_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id     INTEGER NOT NULL REFERENCES medicines(id),
    batch_id        INTEGER NOT NULL REFERENCES batches(id),
    quantity_taken  INTEGER NOT NULL CHECK (quantity_taken > 0),
    remaining_after INTEGER NOT NULL,
    sale_price      REAL,
    sold_at         TEXT    NOT NULL,
    logged_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS adjustment_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id   INTEGER NOT NULL REFERENCES medicines(id),
    batch_id      INTEGER NOT NULL REFERENCES batches(id),
    delta         INTEGER NOT NULL,
    reason        TEXT,
    adjusted_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reorder_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id      INTEGER NOT NULL REFERENCES medicines(id),
    supplier_id      INTEGER REFERENCES suppliers(id),
    quantity_ordered INTEGER NOT NULL,
    triggered_by     TEXT    NOT NULL DEFAULT 'system',
    status           TEXT    NOT NULL DEFAULT 'pending',
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_batches_med_exp ON batches(medicine_id, expiry_date ASC);
CREATE INDEX IF NOT EXISTS idx_batches_expiry  ON batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_log_medicine    ON dispensing_log(medicine_id, sold_at);
"""

_SEED = """
INSERT OR IGNORE INTO medicines (name, category, unit, min_stock_level) VALUES
    ('Amoxicillin 500mg',   'Antibiotic',       'capsule', 100),
    ('Ibuprofen 400mg',     'Analgesic',         'tablet',   80),
    ('Metformin 500mg',     'Antidiabetic',      'tablet',  120),
    ('Paracetamol 500mg',   'Analgesic',         'tablet',  150),
    ('Atorvastatin 10mg',   'Cardiovascular',    'tablet',   60),
    ('Omeprazole 20mg',     'Gastrointestinal',  'capsule',  70),
    ('Cetirizine 10mg',     'Antihistamine',     'tablet',   50),
    ('Salbutamol Inhaler',  'Respiratory',       'inhaler',  30);

INSERT OR IGNORE INTO suppliers (name, contact, lead_days) VALUES
    ('MedLine Pharma',      '+91-9800001111', 5),
    ('HealthBridge Supply', '+91-9800002222', 7),
    ('PharmaWorld Dist.',   '+91-9800003333', 10),
    ('CureFirst Logistics', '+91-9800004444', 3);

INSERT OR IGNORE INTO batches (medicine_id, supplier_id, batch_number, expiry_date, quantity, unit_cost) VALUES
    (1, 1, 'AMX-24-01', date('now', '+45 days'),  120, 12.50),
    (1, 1, 'AMX-24-02', date('now', '+200 days'), 200,  9.75),
    (2, 2, 'IBU-24-01', date('now', '+80 days'),   80,  4.20),
    (2, 2, 'IBU-24-02', date('now', '+300 days'), 150,  3.80),
    (3, 1, 'MET-24-01', date('now', '+60 days'),   60,  6.00),
    (3, 3, 'MET-24-02', date('now', '+250 days'), 300,  5.50),
    (4, 2, 'PAR-24-01', date('now', '+15 days'),   15,  2.10),
    (4, 2, 'PAR-24-02', date('now', '+180 days'), 250,  1.90),
    (5, 4, 'ATV-24-01', date('now', '+400 days'),  90, 18.00),
    (6, 1, 'OME-24-01', date('now', '+90 days'),   45, 11.00),
    (7, 3, 'CET-24-01', date('now', '+120 days'),   0,  5.00),
    (8, 4, 'SAL-24-01', date('now', '+30 days'),   12, 95.00);
"""


def init_db() -> None:
    """Create tables and seed sample data. Idempotent — safe to call on startup."""
    with get_db() as conn:
        conn.executescript(_DDL)
        conn.executescript(_SEED)


# ─────────────────────────────────────────────────────────────
# Medicine queries
# ─────────────────────────────────────────────────────────────

def db_get_all_medicines(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Aggregated stock summary, one row per medicine."""
    return conn.execute("""
        SELECT
            m.id,
            m.name,
            m.category,
            m.unit,
            m.min_stock_level,
            COALESCE(SUM(b.quantity), 0) AS total_stock,
            COUNT(DISTINCT b.id)          AS batch_count,
            MIN(b.expiry_date)            AS nearest_expiry
        FROM medicines m
        LEFT JOIN batches b ON b.medicine_id = m.id AND b.quantity > 0
        GROUP BY m.id
        ORDER BY m.name ASC
    """).fetchall()


def db_get_medicine_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM medicines WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()


# ─────────────────────────────────────────────────────────────
# Batch queries
# ─────────────────────────────────────────────────────────────

def db_get_batches_fefo(conn: sqlite3.Connection, medicine_id: int) -> list[sqlite3.Row]:
    """Return all non-zero batches for a medicine, sorted expiry ASC (FEFO order)."""
    return conn.execute("""
        SELECT b.id, b.batch_number, b.expiry_date, b.quantity,
               b.unit_cost, s.name AS supplier_name
        FROM   batches b
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        WHERE  b.medicine_id = ? AND b.quantity > 0
        ORDER  BY b.expiry_date ASC
    """, (medicine_id,)).fetchall()


def db_get_all_batches(conn: sqlite3.Connection, medicine_id: int) -> list[sqlite3.Row]:
    """Return every batch for a medicine (including empty ones), expiry ASC."""
    return conn.execute("""
        SELECT b.id, b.batch_number, b.expiry_date, b.quantity,
               b.unit_cost, s.name AS supplier_name
        FROM   batches b
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        WHERE  b.medicine_id = ?
        ORDER  BY b.expiry_date ASC
    """, (medicine_id,)).fetchall()


def db_upsert_batch(
    conn: sqlite3.Connection,
    medicine_id: int,
    supplier_id: int | None,
    batch_number: str,
    expiry_date: str,
    quantity: int,
    unit_cost: float | None,
) -> None:
    """Insert a new batch, or add quantity to an existing one (upsert)."""
    conn.execute("""
        INSERT INTO batches
            (medicine_id, supplier_id, batch_number, expiry_date, quantity, unit_cost)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (medicine_id, batch_number) DO UPDATE SET
            quantity    = quantity + excluded.quantity,
            expiry_date = excluded.expiry_date,
            updated_at  = datetime('now')
    """, (medicine_id, supplier_id, batch_number, expiry_date, quantity, unit_cost))


def db_deduct_from_batch(conn: sqlite3.Connection, batch_id: int, qty: int) -> int:
    """
    Atomically deduct qty from a batch.
    Returns the new remaining quantity.
    Raises ValueError if this would make quantity negative.
    """
    row = conn.execute(
        "SELECT quantity FROM batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Batch id={batch_id} does not exist.")
    new_qty = row["quantity"] - qty
    if new_qty < 0:
        raise ValueError(
            f"Cannot deduct {qty} from batch {batch_id} "
            f"(current stock: {row['quantity']})."
        )
    conn.execute(
        "UPDATE batches SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
        (new_qty, batch_id),
    )
    return new_qty


def db_adjust_batch(
    conn: sqlite3.Connection,
    medicine_id: int,
    batch_number: str,
    delta: int,
    reason: str | None,
) -> int:
    """
    Apply delta to a specific batch.
    Returns the new quantity.
    Raises ValueError if batch not found or result would be negative.
    """
    row = conn.execute(
        "SELECT id, quantity FROM batches WHERE medicine_id = ? AND batch_number = ?",
        (medicine_id, batch_number),
    ).fetchone()
    if not row:
        raise ValueError(f"Batch '{batch_number}' not found.")
    new_qty = row["quantity"] + delta
    if new_qty < 0:
        raise ValueError(
            f"Adjustment of {delta:+d} would cause negative stock "
            f"(current: {row['quantity']}) on batch '{batch_number}'."
        )
    conn.execute(
        "UPDATE batches SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
        (new_qty, row["id"]),
    )
    conn.execute(
        """INSERT INTO adjustment_log (medicine_id, batch_id, delta, reason)
           VALUES (?, ?, ?, ?)""",
        (medicine_id, row["id"], delta, reason),
    )
    return new_qty


# ─────────────────────────────────────────────────────────────
# Dispensing log
# ─────────────────────────────────────────────────────────────

def db_log_dispensing(
    conn: sqlite3.Connection,
    medicine_id: int,
    batch_id: int,
    qty_taken: int,
    remaining: int,
    sale_price: float | None,
    sold_at: datetime,
) -> None:
    conn.execute(
        """INSERT INTO dispensing_log
               (medicine_id, batch_id, quantity_taken, remaining_after, sale_price, sold_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (medicine_id, batch_id, qty_taken, remaining, sale_price, sold_at.isoformat()),
    )


# ─────────────────────────────────────────────────────────────
# Alert queries
# ─────────────────────────────────────────────────────────────

def db_get_low_stock(
    conn: sqlite3.Connection, threshold: int | None = None
) -> list[sqlite3.Row]:
    """
    Return medicines at or below threshold.
    If threshold is None, each medicine's own min_stock_level is used.
    """
    return conn.execute("""
        SELECT
            m.id,
            m.name,
            m.category,
            m.min_stock_level,
            COALESCE(SUM(b.quantity), 0) AS total_stock,
            COUNT(DISTINCT b.id)          AS batch_count
        FROM medicines m
        LEFT JOIN batches b ON b.medicine_id = m.id AND b.quantity > 0
        GROUP BY m.id
        HAVING total_stock <= COALESCE(?, m.min_stock_level)
        ORDER BY total_stock ASC
    """, (threshold,)).fetchall()


def db_get_expiry_alerts(
    conn: sqlite3.Connection, days: int = 30
) -> list[sqlite3.Row]:
    """Return batches expiring within the next `days` days that still have stock."""
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    return conn.execute("""
        SELECT
            b.id AS batch_id,
            b.batch_number,
            b.expiry_date,
            b.quantity,
            m.name     AS medicine_name,
            m.category,
            CAST(julianday(b.expiry_date) - julianday('now') AS INTEGER) AS days_left
        FROM batches b
        JOIN medicines m ON m.id = b.medicine_id
        WHERE b.quantity > 0
          AND b.expiry_date <= ?
        ORDER BY b.expiry_date ASC
    """, (cutoff,)).fetchall()


# ─────────────────────────────────────────────────────────────
# Reorder queries
# ─────────────────────────────────────────────────────────────

def db_get_reorder_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """
    Return medicines whose total stock is at or below min_stock_level,
    together with their most-used supplier.
    """
    return conn.execute("""
        SELECT
            m.id,
            m.name,
            m.category,
            m.min_stock_level,
            COALESCE(SUM(b.quantity), 0) AS current_stock,
            s.name     AS preferred_supplier,
            s.lead_days
        FROM medicines m
        LEFT JOIN batches b  ON b.medicine_id = m.id AND b.quantity > 0
        LEFT JOIN suppliers s ON s.id = (
            SELECT supplier_id
            FROM   batches
            WHERE  medicine_id = m.id AND supplier_id IS NOT NULL
            GROUP  BY supplier_id
            ORDER  BY COUNT(*) DESC
            LIMIT  1
        )
        GROUP BY m.id
        HAVING current_stock <= m.min_stock_level
        ORDER BY current_stock ASC
    """).fetchall()


def db_log_reorder(
    conn: sqlite3.Connection,
    medicine_id: int,
    supplier_id: int | None,
    quantity: int,
    triggered_by: str = "system",
) -> None:
    conn.execute(
        """INSERT INTO reorder_logs
               (medicine_id, supplier_id, quantity_ordered, triggered_by)
           VALUES (?, ?, ?, ?)""",
        (medicine_id, supplier_id, quantity, triggered_by),
    )


# ─────────────────────────────────────────────────────────────
# Supplier lookup
# ─────────────────────────────────────────────────────────────

def db_get_supplier_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM suppliers WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()