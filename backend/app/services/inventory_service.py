from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models import Medicine, Batch, Sale, SaleItem, ReorderLog
import datetime

class SalesService:
    @staticmethod
    def process_sale(db: Session, medicine_id: int, quantity: int):
        batches = db.query(Batch).filter(
            Batch.medicine_id == medicine_id,
            Batch.quantity_remaining > 0,
            Batch.is_active == True
        ).order_by(Batch.expiry_date.asc()).all()

        total_available = sum(b.quantity_remaining for b in batches)
        if total_available < quantity:
            raise ValueError(f"Insufficient stock. Available: {total_available}")

        # Create Sale record
        new_sale = Sale(total_amount=0.0)
        db.add(new_sale)
        db.flush()

        remaining_to_deduct = quantity
        total_sale_amount = 0.0

        for batch in batches:
            if remaining_to_deduct <= 0:
                break
            
            deduct = min(batch.quantity_remaining, remaining_to_deduct)
            batch.quantity_remaining -= deduct
            if batch.quantity_remaining == 0:
                batch.is_active = False
            
            # Use a dummy unit price for now as it's not and-to-end yet
            unit_price = 10.0 # Placeholder
            subtotal = deduct * unit_price
            total_sale_amount += subtotal
            
            sale_item = SaleItem(
                sale_id=new_sale.id,
                medicine_id=medicine_id,
                batch_id=batch.id,
                quantity_sold=deduct,
                unit_price=unit_price
            )
            db.add(sale_item)
            remaining_to_deduct -= deduct

        new_sale.total_amount = total_sale_amount
        
        # Check reorder threshold
        medicine = db.query(Medicine).filter(Medicine.id == medicine_id).first()
        new_total_stock = db.query(func.sum(Batch.quantity_remaining)).filter(
            Batch.medicine_id == medicine_id,
            Batch.is_active == True
        ).scalar() or 0
        
        if new_total_stock < medicine.reorder_threshold:
            existing_reorder = db.query(ReorderLog).filter(
                ReorderLog.medicine_id == medicine_id,
                ReorderLog.status == "pending"
            ).first()
            if not existing_reorder:
                reorder_log = ReorderLog(
                    medicine_id=medicine_id,
                    quantity_ordered=medicine.reorder_threshold * 2,
                    status="pending"
                )
                db.add(reorder_log)

        db.commit()
        db.refresh(new_sale)
        return new_sale

class InventoryService:
    @staticmethod
    def get_inventory(db: Session):
        medicines = db.query(Medicine).all()
        print(f"DEBUG: get_inventory called. Medicines found in DB: {len(medicines)}")
        results = []
        for med in medicines:
            print(f"DEBUG: Processing medicine: {med.name} (ID: {med.id})")
            
            # Subquery or separate query for stock (already exists)
            total_stock = db.query(func.sum(Batch.quantity_remaining)).filter(
                Batch.medicine_id == med.id,
                Batch.is_active == True
            ).scalar() or 0
            
            # Get batches for this medicine
            active_batches = db.query(Batch).filter(
                Batch.medicine_id == med.id,
                Batch.is_active == True
            ).all()

            results.append({
                "id": med.id,
                "name": med.name,
                "generic_name": med.generic_name,
                "category": med.category,
                "ndc": med.ndc,
                "unit": med.unit,
                "reorder_threshold": med.reorder_threshold,
                "preferred_supplier_id": med.preferred_supplier_id,
                "total_stock": total_stock,
                "low_stock": total_stock < med.reorder_threshold,
                "batches": active_batches
            })
        return results

    @staticmethod
    def get_medicine_details(db: Session, medicine_id: int):
        medicine = db.query(Medicine).filter(Medicine.id == medicine_id).first()
        if not medicine:
            return None
        
        batches = db.query(Batch).filter(
            Batch.medicine_id == medicine_id,
            Batch.is_active == True
        ).order_by(Batch.expiry_date.asc()).all()
        
        total_stock = sum(b.quantity_remaining for b in batches)
        
        return {
            "id": medicine.id,
            "name": medicine.name,
            "generic_name": medicine.generic_name,
            "ndc": medicine.ndc,
            "unit": medicine.unit,
            "reorder_threshold": medicine.reorder_threshold,
            "preferred_supplier_id": medicine.preferred_supplier_id,
            "total_stock": total_stock,
            "low_stock": total_stock < medicine.reorder_threshold,
            "batches": batches
        }
