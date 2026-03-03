from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date

class SupplierBase(BaseModel):
    name: str
    phone: Optional[str] = None

class SupplierResponse(SupplierBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class BatchBase(BaseModel):
    batch_number: str
    expiry_date: date
    quantity_remaining: int
    quantity_received: int
    purchase_price: float
    supplier_id: int

class BatchCreate(BatchBase):
    medicine_id: int

class BatchResponse(BatchBase):
    id: int
    medicine_id: int
    received_at: datetime
    is_active: bool

    class Config:
        from_attributes = True

class MedicineBase(BaseModel):
    name: str
    generic_name: Optional[str] = None
    category: str = "General"
    ndc: str
    unit: str = "UNIT"
    reorder_threshold: int = 20

class MedicineResponse(MedicineBase):
    id: int
    total_stock: int
    low_stock: bool
    preferred_supplier_id: Optional[int]
    batches: List[BatchResponse] = []

    class Config:
        from_attributes = True

class MedicineDetailResponse(MedicineResponse):
    batches: List[BatchResponse]

class SaleItemBase(BaseModel):
    medicine_id: int
    quantity: int

class SaleCreate(BaseModel):
    items: List[SaleItemBase]

class SaleResponse(BaseModel):
    sale_id: int
    total_amount: float
    sale_date: datetime
    items: List[dict]

class ReorderLogResponse(BaseModel):
    id: int
    medicine_id: int
    reorder_date: datetime
    quantity_ordered: int
    status: str

    class Config:
        from_attributes = True

class PredictRequest(BaseModel):
    medicine_id: int
    horizon_days: int

class PredictResponse(BaseModel):
    medicine_id: int
    forecast: List[dict]
