"""
SQLAlchemy model for Sale.
Each record represents one sale transaction line item — 
a specific quantity of a medicine sold from a specific batch.
"""

from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True)

    quantity_sold = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)

    sale_date = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    customer_ref = Column(String(255), nullable=True)   # Optional customer identifier
    notes = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    medicine = relationship("Medicine", back_populates="sales")
    batch = relationship("Batch", back_populates="sale_items")

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} medicine_id={self.medicine_id} "
            f"qty={self.quantity_sold} date={self.sale_date}>"
        )
