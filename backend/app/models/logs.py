"""
SQLAlchemy model for ActivityLog.
Tracks inventory events: reorder triggers, alerts, stock movements.
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from ..database import Base


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    # e.g. "REORDER_TRIGGERED", "LOW_STOCK_ALERT", "BATCH_RECEIVED", "SALE_RECORDED"
    description = Column(Text, nullable=True)
    severity = Column(String(50), default="INFO")  # INFO | WARNING | CRITICAL
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self) -> str:
        return f"<ActivityLog id={self.id} type={self.event_type!r} severity={self.severity!r}>"
