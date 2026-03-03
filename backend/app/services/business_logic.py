import pandas as pd
from sqlalchemy.orm import Session
from ..models import Medicine, Batch, ReorderLog
from datetime import datetime
import io

class UploadService:
    @staticmethod
    def process_excel(db: Session, file_content: bytes):
        df = pd.read_excel(io.BytesIO(file_content))
        # Validate columns: medicine_name, batch_number, quantity, expiry_date, supplier
        required_columns = ["medicine_name", "batch_number", "quantity", "expiry_date", "supplier"]
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f"Missing columns. Required: {required_columns}")

        summary = {"added": 0, "updated": 0, "errors": 0}
        
        for index, row in df.iterrows():
            try:
                # 1. Find or create medicine
                medicine = db.query(Medicine).filter(Medicine.name == str(row["medicine_name"]).strip()).first()
                if not medicine:
                    medicine = Medicine(
                        name=str(row["medicine_name"]).strip(),
                        category="General", # Default or from sheet
                        unit_price=0.0 # Placeholder
                    )
                    db.add(medicine)
                    db.flush()
                
                # 2. Upsert Batch
                batch = db.query(Batch).filter(
                    Batch.medicine_id == medicine.id,
                    Batch.batch_number == str(row["batch_number"]).strip()
                ).first()
                
                if batch:
                    batch.quantity_remaining += int(row["quantity"])
                    batch.expiry_date = pd.to_datetime(row["expiry_date"])
                    summary["updated"] += 1
                else:
                    new_batch = Batch(
                        medicine_id=medicine.id,
                        batch_number=str(row["batch_number"]).strip(),
                        quantity_remaining=int(row["quantity"]),
                        expiry_date=pd.to_datetime(row["expiry_date"]),
                        supplier=str(row["supplier"]).strip(),
                        is_active=True
                    )
                    db.add(new_batch)
                    summary["added"] += 1
            except Exception as e:
                summary["errors"] += 1
                continue
        
        db.commit()
        return summary

class ReorderService:
    @staticmethod
    def trigger_reorder(db: Session, medicine_id: int):
        medicine = db.query(Medicine).filter(Medicine.id == medicine_id).first()
        if not medicine:
            return None
        
        # Log reorder
        reorder_log = ReorderLog(
            medicine_id=medicine_id,
            quantity_ordered=medicine.reorder_threshold * 2,
            status="pending"
        )
        db.add(reorder_log)
        db.commit()
        
        # Simulate Email (Mailtrap)
        # In real scenario, use smtplib. Send minimal snippet for simulation
        print(f"SIMULATED EMAIL: Reordering {medicine.name} - Qty: {reorder_log.quantity_ordered}")
        
        return reorder_log

class MLBridgeService:
    @staticmethod
    async def get_forecast(medicine_id: int, horizon_days: int):
        # In real scenario, use httpx to call http://localhost:8001/predict-demand
        # Simulation:
        import random
        return {
            "medicine_id": medicine_id,
            "forecast": [
                {"date": (datetime.now() + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), 
                 "predicted_qty": random.randint(10, 50)} 
                for i in range(1, horizon_days + 1)
            ]
        }
