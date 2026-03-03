"""
ML Module — FastAPI Application Entry Point

Exposes:
  POST /predict-demand   → Full inventory intelligence for a medicine
  POST /train            → Trigger / force-retrain models for a medicine
  GET  /health           → Health check
  GET  /model-info/{id}  → Loaded model metadata and metrics
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Path setup ────────────────────────────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from inference import run_inference
from training.train import train_for_medicine

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Environment ───────────────────────────────────────────────────────────────
SAVED_MODELS_DIR = os.getenv(
    "SAVED_MODELS_DIR",
    os.path.join(_APP_DIR, "saved_models"),
)


# ────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ────────────────────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    medicine_id: int = Field(..., gt=0, description="Primary key of the medicine")
    current_stock: float = Field(..., ge=0, description="Units currently in stock")
    lead_time_days: int = Field(default=7, ge=1, description="Supplier lead time in days")
    horizon_days: int = Field(default=30, ge=1, le=365, description="Forecast window in days")
    service_level: float = Field(
        default=0.95,
        ge=0.5,
        le=0.999,
        description="Inventory service level (e.g. 0.95 = 95%)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "medicine_id": 1,
                "current_stock": 150,
                "lead_time_days": 5,
                "horizon_days": 30,
                "service_level": 0.95,
            }
        }


class PredictResponse(BaseModel):
    medicine_id: int
    predicted_demand_30_days: float
    safety_stock: float
    reorder_point: float
    reorder_quantity: float
    suggested_order_date: Optional[str]
    risk_level: str
    confidence_score: float
    model_used: str
    avg_daily_demand: float
    demand_std: float
    demand_volatility: float
    prophet_mape: Optional[float]
    arima_mape: Optional[float]
    daily_forecast: list


class TrainRequest(BaseModel):
    medicine_id: int = Field(..., gt=0)
    force_retrain: bool = Field(default=False, description="Force retraining even if models exist")

    class Config:
        json_schema_extra = {"example": {"medicine_id": 1, "force_retrain": False}}


class TrainResponse(BaseModel):
    medicine_id: int
    status: str
    model_used: Optional[str]
    prophet_metrics: Optional[dict]
    arima_metrics: Optional[dict]
    demand_stats: Optional[dict]


# ────────────────────────────────────────────────────────────────────────────
# App lifecycle
# ────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create saved_models directory on startup."""
    os.makedirs(SAVED_MODELS_DIR, exist_ok=True)
    logger.info("ML Module started. saved_models dir: %s", SAVED_MODELS_DIR)
    yield
    logger.info("ML Module shutting down.")


# ────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Smart Pharmacy — ML Demand Forecasting Module",
    description=(
        "Forecasts medicine demand using Prophet and ARIMA models. "
        "Returns safety stock, reorder point, reorder quantity, risk level, "
        "and confidence score."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    """Simple health probe — used by Docker / load balancers."""
    return {"status": "ok", "service": "ml_module"}


@app.post(
    "/predict-demand",
    response_model=PredictResponse,
    tags=["Forecasting"],
    summary="Predict demand and compute inventory KPIs for a medicine",
)
def predict_demand(request: PredictRequest):
    """
    **Steps performed internally:**
    1. Load (or train) Prophet & ARIMA models for the given `medicine_id`
    2. Run both models; select the winner by lowest MAPE
    3. Compute Safety Stock, Reorder Point, Reorder Quantity
    4. Classify risk level and calculate confidence score

    **Risk levels:**
    - `CRITICAL`  — predicted demand exceeds current stock
    - `VOLATILE`  — high demand variability (CV > 0.5)
    - `OVERSTOCK` — stock covers demand by 2× or more
    - `NORMAL`    — all inventory metrics healthy
    """
    logger.info(
        "POST /predict-demand — medicine_id=%d stock=%s lead_time=%d",
        request.medicine_id, request.current_stock, request.lead_time_days,
    )
    try:
        result = run_inference(
            medicine_id=request.medicine_id,
            current_stock=request.current_stock,
            lead_time_days=request.lead_time_days,
            horizon_days=request.horizon_days,
            service_level=request.service_level,
            model_dir=SAVED_MODELS_DIR,
        )
    except RuntimeError as exc:
        logger.error("Inference failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during inference: %s", exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")

    return PredictResponse(**result)


@app.post(
    "/train",
    response_model=TrainResponse,
    tags=["Training"],
    summary="Train (or retrain) demand forecasting models for a medicine",
)
def trigger_training(request: TrainRequest, background_tasks: BackgroundTasks):
    """
    Triggers the full training pipeline for a given `medicine_id`.

    - Fetches historical sales from the database
    - Trains both Prophet and ARIMA models
    - Evaluates and saves models as `.pkl` files
    - Returns evaluation metrics

    Set `force_retrain=true` to retrain even if a cached model exists.
    """
    logger.info(
        "POST /train — medicine_id=%d force=%s",
        request.medicine_id, request.force_retrain,
    )
    try:
        result = train_for_medicine(
            medicine_id=request.medicine_id,
            model_dir=SAVED_MODELS_DIR,
            force_retrain=request.force_retrain,
        )
    except Exception as exc:
        logger.exception("Training failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Training error: {exc}")

    if result.get("status") == "error":
        raise HTTPException(status_code=422, detail=result.get("detail", "Training failed"))

    return TrainResponse(
        medicine_id=request.medicine_id,
        status=result["status"],
        model_used=result.get("model_used"),
        prophet_metrics=result.get("prophet_metrics"),
        arima_metrics=result.get("arima_metrics"),
        demand_stats=result.get("demand_stats"),
    )


@app.get(
    "/model-info/{medicine_id}",
    tags=["Models"],
    summary="Get saved model metadata and metrics for a medicine",
)
def get_model_info(medicine_id: int):
    """
    Returns the persisted metrics for both Prophet and ARIMA models
    for the specified medicine, without running inference.
    """
    from models.prophet_model import ProphetModel
    from models.arima_model import ArimaModel

    prophet = ProphetModel(medicine_id)
    arima = ArimaModel(medicine_id)

    prophet_loaded = prophet.load(SAVED_MODELS_DIR)
    arima_loaded = arima.load(SAVED_MODELS_DIR)

    if not prophet_loaded and not arima_loaded:
        raise HTTPException(
            status_code=404,
            detail=f"No trained models found for medicine_id={medicine_id}. "
                   "Call POST /train first.",
        )

    return {
        "medicine_id": medicine_id,
        "prophet": {
            "loaded": prophet_loaded,
            "metrics": prophet.get_metrics() if prophet_loaded else None,
        },
        "arima": {
            "loaded": arima_loaded,
            "metrics": arima.get_metrics() if arima_loaded else None,
        },
        "saved_models_dir": SAVED_MODELS_DIR,
    }


# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("ML_HOST", "0.0.0.0"),
        port=int(os.getenv("ML_PORT", "8001")),
        reload=os.getenv("DEBUG", "false").lower() == "true",
        log_level="info",
    )
