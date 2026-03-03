from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Date, Boolean
from sqlalchemy.orm import relationship
from ..database import Base
import datetime

class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    batches = relationship("Batch", back_populates="supplier")
    medicines = relationship("Medicine", back_populates="preferred_supplier")

class Medicine(Base):
    __tablename__ = "medicines"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    generic_name = Column(String)
    category = Column(String, default="General")
    ndc = Column(String, unique=True, index=True)
    preferred_supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    unit = Column(String)
    reorder_threshold = Column(Integer, default=20)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    preferred_supplier = relationship("Supplier", back_populates="medicines")
    batches = relationship("Batch", back_populates="medicine")
    sale_items = relationship("SaleItem", back_populates="medicine")

class Batch(Base):
    __tablename__ = "batches"
    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"))
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    batch_number = Column(String, index=True)
    quantity_received = Column(Integer)
    quantity_remaining = Column(Integer)
    expiry_date = Column(Date)
    purchase_price = Column(Float)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    medicine = relationship("Medicine", back_populates="batches")
    supplier = relationship("Supplier", back_populates="batches")
    sale_items = relationship("SaleItem", back_populates="batch")

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True, index=True)
    total_amount = Column(Float)
    sale_date = Column(DateTime, default=datetime.datetime.utcnow)
    notes = Column(String)
    
    items = relationship("SaleItem", back_populates="sale")

class SaleItem(Base):
    __tablename__ = "sale_items"
    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"))
    medicine_id = Column(Integer, ForeignKey("medicines.id"))
    batch_id = Column(Integer, ForeignKey("batches.id"))
    quantity_sold = Column(Integer)
    unit_price = Column(Float)
    
    sale = relationship("Sale", back_populates="items")
    medicine = relationship("Medicine", back_populates="sale_items")
    batch = relationship("Batch", back_populates="sale_items")

class ReorderLog(Base):
    __tablename__ = "reorder_logs"
    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"))
    reorder_date = Column(DateTime, default=datetime.datetime.utcnow)
    quantity_ordered = Column(Integer)
    status = Column(String, default="pending")

class ExpiryLog(Base):
    __tablename__ = "expiry_logs"
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"))
    medicine_id = Column(Integer, ForeignKey("medicines.id"))
    quantity_expensing = Column(Integer)
    expensed_at = Column(DateTime, default=datetime.datetime.utcnow)
