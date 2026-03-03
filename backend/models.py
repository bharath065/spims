"""
backend/models.py
─────────────────
All Pydantic v2 request and response schemas.
No business logic lives here — pure data shape definitions.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _parse_date(v: object) -> date:
    """Accept YYYY-MM-DD or DD/MM/YYYY and return a date object."""
    if isinstance(v, date):
        return v
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {v!r}. Use YYYY-MM-DD or DD/MM/YYYY.")


# ─────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────

class AddStockRequest(BaseModel):
    """Payload to add a new batch or top up an existing one."""
    medicine_name: str       = Field(..., min_length=1, max_length=200)
    batch_number:  str       = Field(..., min_length=1, max_length=100)
    expiry_date:   date
    quantity:      int       = Field(..., ge=1, description="Units to add (>= 1)")
    supplier_name: Optional[str]   = Field(None, max_length=200)
    unit_cost:     Optional[float] = Field(None, ge=0)

    @field_validator("expiry_date", mode="before")
    @classmethod
    def parse_expiry(cls, v: object) -> date:
        return _parse_date(v)

    @field_validator("medicine_name", "batch_number", "supplier_name", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class SellRequest(BaseModel):
    """Payload for a FEFO-based dispensing / sale."""
    medicine_name: str             = Field(..., min_length=1, max_length=200)
    quantity:      int             = Field(..., ge=1)
    sale_price:    Optional[float]    = Field(None, ge=0)
    sold_at:       Optional[datetime] = None

    @field_validator("medicine_name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class AdjustRequest(BaseModel):
    """
    Manual stock correction.
      delta > 0  ->  stock return or count correction upward
      delta < 0  ->  damage write-off or removal
    """
    medicine_name: str           = Field(..., min_length=1, max_length=200)
    batch_number:  str           = Field(..., min_length=1, max_length=100)
    delta:         int           = Field(..., description="Non-zero. Positive=add, Negative=remove.")
    reason:        Optional[str] = Field(None, max_length=500)

    @field_validator("medicine_name", "batch_number", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def delta_nonzero(self) -> "AdjustRequest":
        if self.delta == 0:
            raise ValueError("delta must be non-zero.")
        return self


# ─────────────────────────────────────────────────────────────
# Response schemas
# ─────────────────────────────────────────────────────────────

class MedicineSummary(BaseModel):
    id:              int
    name:            str
    category:        str
    unit:            str
    total_stock:     int
    min_stock_level: int
    batch_count:     int
    nearest_expiry:  Optional[str]
    stock_status:    str   # "ok" | "low" | "critical" | "out"


class BatchInfo(BaseModel):
    id:                int
    batch_number:      str
    expiry_date:       str
    quantity:          int
    unit_cost:         Optional[float]
    supplier_name:     Optional[str]
    days_until_expiry: int


class SellResponseBatch(BaseModel):
    batch_number:   str
    expiry_date:    str
    quantity_taken: int
    remaining:      int


class SellResponse(BaseModel):
    medicine_name:    str
    total_dispensed:  int
    batches_consumed: list[SellResponseBatch]


class LowStockAlert(BaseModel):
    id:              int
    name:            str
    category:        str
    total_stock:     int
    min_stock_level: int
    shortage:        int
    batches:         int


class ExpiryAlert(BaseModel):
    batch_id:      int
    medicine_name: str
    category:      str
    batch_number:  str
    expiry_date:   str
    quantity:      int
    days_left:     int
    urgency:       str   # "expired" | "critical" | "warning" | "watch"


class ReorderSuggestion(BaseModel):
    medicine_id:        int
    medicine_name:      str
    category:           str
    current_stock:      int
    min_stock_level:    int
    suggested_quantity: int
    preferred_supplier: Optional[str]
    lead_days:          Optional[int]


class AddStockResponse(BaseModel):
    medicine_name: str
    batch_number:  str
    expiry_date:   str
    new_quantity:  int
    status:        str = "success"


class AdjustResponse(BaseModel):
    medicine_name: str
    batch_number:  str
    delta:         int
    new_quantity:  int
    reason:        Optional[str]
    status:        str = "success"