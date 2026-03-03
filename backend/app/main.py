"""
Backend FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .config import settings

# ── Import all models so SQLAlchemy can create their tables ───────────────────
from .models import medicine, sale, batch, supplier  # noqa: F401

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup if they don't exist."""
    logger.info("Backend starting up — creating tables if needed.")
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Backend shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Mount routers ─────────────────────────────────────────────────────────────
from .routers import medicines, sales, alerts, reorder  # noqa: E402

app.include_router(medicines.router, prefix=f"{settings.API_V1_STR}/medicines", tags=["Medicines"])
app.include_router(sales.router, prefix=f"{settings.API_V1_STR}/sales", tags=["Sales"])
app.include_router(alerts.router, prefix=f"{settings.API_V1_STR}/alerts", tags=["Alerts"])
app.include_router(reorder.router, prefix=f"{settings.API_V1_STR}/reorder", tags=["Reorder"])


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "backend"}
