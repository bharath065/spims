from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..schemas.schemas import MedicineResponse, MedicineDetailResponse, SaleCreate, SaleResponse, BatchCreate, PredictRequest, PredictResponse
from ..services.inventory_service import InventoryService, SalesService
from ..services.business_logic import UploadService, ReorderService, MLBridgeService
from ..models import ExpiryLog, Batch
import datetime
from sqlalchemy import func

router = APIRouter()

# --- INVENTORY ---
@router.get("/inventory", response_model=List[MedicineResponse])
def get_inventory(db: Session = Depends(get_db)):
    return InventoryService.get_inventory(db)

@router.get("/medicines", response_model=List[MedicineResponse])
def get_medicines(db: Session = Depends(get_db)):
    return InventoryService.get_inventory(db)

@router.get("/medicines/{medicine_id}", response_model=MedicineDetailResponse)
def get_medicine_details(medicine_id: int, db: Session = Depends(get_db)):
    details = InventoryService.get_medicine_details(db, medicine_id)
    if not details:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return details

# --- SALES ---
@router.post("/sales", response_model=SaleResponse)
def create_sale(sale_data: SaleCreate, db: Session = Depends(get_db)):
    # Simple logic to handle bulk sales in one request
    total_sale = None
    for item in sale_data.items:
        try:
            total_sale = SalesService.process_sale(db, item.medicine_id, item.quantity)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    # Return last sale item as summary or customize
    return {
        "sale_id": total_sale.id,
        "total_amount": total_sale.total_amount,
        "sale_date": total_sale.sale_date,
        "items": [{"medicine_id": i.medicine_id, "qty": i.quantity_sold} for i in total_sale.items]
    }

# --- ALERTS ---
@router.get("/alerts/low-stock")
def get_low_stock(db: Session = Depends(get_db)):
    inventory = InventoryService.get_inventory(db)
    return [m for m in inventory if m["low_stock"]]

@router.get("/alerts/expiry")
def get_expiry_alerts(days: int = 30, db: Session = Depends(get_db)):
    today = datetime.date.today()
    threshold_date = today + datetime.timedelta(days=days)
    
    # Filter: quantity_remaining > 0, active, and expiry <= threshold
    batches = db.query(Batch).filter(
        Batch.quantity_remaining > 0,
        Batch.is_active == True,
        Batch.expiry_date <= threshold_date
    ).order_by(Batch.expiry_date.asc()).all()
    return batches

@router.get("/alerts/waste")
def get_waste_analytics(db: Session = Depends(get_db)):
    today = datetime.date.today()
    
    # Sum quantity_remaining for all active batches where expiry_date < today
    waste_sum = db.query(func.sum(Batch.quantity_remaining)).filter(
        Batch.expiry_date < today,
        Batch.is_active == True
    ).scalar() or 0
    
    expired_count = db.query(Batch).filter(
        Batch.expiry_date < today,
        Batch.is_active == True
    ).count()

    return {
        "total_waste_stock": waste_sum,
        "expired_batches_count": expired_count,
        "checked_at": datetime.datetime.utcnow().isoformat(),
        "status": "success"
    }

# --- REORDER ---
@router.post("/reorder")
def trigger_reorder(medicine_id: int, db: Session = Depends(get_db)):
    log = ReorderService.trigger_reorder(db, medicine_id)
    if not log:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return log

# --- UPLOAD ---
@router.post("/upload/excel")
async def upload_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    try:
        summary = UploadService.process_excel(db, content)
        return summary
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- ML BRIDGE ---
@router.post("/predict-demand", response_model=PredictResponse)
async def predict_demand(req: PredictRequest):
    return await MLBridgeService.get_forecast(req.medicine_id, req.horizon_days)
