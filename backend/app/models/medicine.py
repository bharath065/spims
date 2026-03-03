"""
SQLAlchemy model for Medicine.
Represents a pharmaceutical product in the inventory.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base


class Medicine(Base):
    __tablename__ = "medicines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    generic_name = Column(String(255), nullable=True)
    brand_name = Column(String(255), nullable=True)
    manufacturer = Column(String(255), nullable=True)
    category = Column(String(100), nullable=True, index=True)
    dosage_form = Column(String(100), nullable=True)   # tablet, syrup, injection…
    strength = Column(String(100), nullable=True)      # e.g. "500mg"
    unit = Column(String(50), nullable=True, default="units")

    # Inventory thresholds
    reorder_level = Column(Integer, default=50)
    reorder_quantity = Column(Integer, default=100)
    current_stock = Column(Integer, default=0)
    lead_time_days = Column(Integer, default=7)

    # Pricing
    unit_price = Column(Float, nullable=True)
    selling_price = Column(Float, nullable=True)

    # Metadata
    is_active = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    batches = relationship("Batch", back_populates="medicine", cascade="all, delete-orphan")
    sales = relationship("Sale", back_populates="medicine")

    def __repr__(self) -> str:
        return f"<Medicine id={self.id} name={self.name!r}>"
