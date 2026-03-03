from fastapi import FastAPI
from .database import engine, Base
from .routers import api
from . import models
from sqlalchemy.orm import configure_mappers
from fastapi.middleware.cors import CORSMiddleware

# Ensure mappers are configured
configure_mappers()

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SPIMS - Smart Pharmacy Inventory Management System",
    description="Backend API for managing pharmacy inventory, FEFO sales, alerts, and reordering.",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(api.router, tags=["API"])

@app.get("/test-db")
def test_db():
    from sqlalchemy import text
    with engine.connect() as conn:
        res = conn.execute(text("SELECT name FROM medicines")).fetchall()
        return {"count": len(res), "medicines": [r[0] for r in res]}

@app.get("/")
def read_root():
    from .database import DATABASE_URL
    return {
        "message": "Welcome to SPIMS Backend API", 
        "version": "1.0.1 (Correct Project)",
        "port": 8001,
        "database": DATABASE_URL,
        "docs": "/docs"
    }
