"""
SQLAlchemy model for Batch.
Each batch represents a purchase/receipt of a medicine from a supplier.
FEFO (First-Expiry First-Out) logic depends on expiry_date.
"""

from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    batch_number = Column(String(100), nullable=False)

    quantity_received = Column(Integer, nullable=False)
    quantity_remaining = Column(Integer, nullable=False)
    unit_cost = Column(Float, nullable=True)

    manufacture_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=False, index=True)   # Critical for FEFO
    received_date = Column(Date, nullable=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    medicine = relationship("Medicine", back_populates="batches")
    supplier = relationship("Supplier", back_populates="batches")
    sale_items = relationship("Sale", back_populates="batch")

    def __repr__(self) -> str:
        return (
            f"<Batch id={self.id} medicine_id={self.medicine_id} "
            f"batch={self.batch_number!r} exp={self.expiry_date}>"
        )
