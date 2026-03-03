"""
Inventory Intelligence Inference Engine.

Given a medicine_id + current_stock + lead_time_days this module:
1. Auto-loads (or trains) Prophet & ARIMA models
2. Runs both models and picks the better one by MAPE
3. Calculates pharmacy-specific inventory KPIs:
   - Safety Stock  (service-level configurable, default 95 %)
   - Reorder Point
   - Reorder Quantity
   - Suggested Order Date
   - Risk Level      (CRITICAL / VOLATILE / OVERSTOCK / NORMAL)
   - Confidence Score (1 - MAPE/100, clamped 0–1)
"""

import logging
import math
import os
import sys
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

# ── Path helpers so this works standalone and as a FastAPI import ─────────────
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from models.prophet_model import ProphetModel
from models.arima_model import ArimaModel
from training.preprocess import preprocess_sales_data, get_demand_statistics
from training.train import (
    fetch_sales_data,
    fetch_medicine_metadata,
    train_for_medicine,
    _select_best_model,
)

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmacy_user:pharmacy_pass@localhost:5432/pharmacy_db",
)
SAVED_MODELS_DIR = os.getenv(
    "SAVED_MODELS_DIR",
    os.path.join(_APP_DIR, "saved_models"),
)

# Z-scores for common service levels
_Z_SCORES = {
    0.90: 1.282,
    0.95: 1.645,
    0.99: 2.326,
    0.999: 3.090,
}
_DEFAULT_SERVICE_LEVEL = 0.95

# Volatility threshold above which a medicine is flagged VOLATILE
_VOLATILE_THRESHOLD = 0.5

# If stock covers demand by this ratio, flag OVERSTOCK
_OVERSTOCK_RATIO = 2.0


# ────────────────────────────────────────────────────────────────────────────
# Core inventory KPI calculations
# ────────────────────────────────────────────────────────────────────────────

def calculate_safety_stock(
    demand_std: float,
    lead_time_days: int,
    service_level: float = _DEFAULT_SERVICE_LEVEL,
) -> float:
    """
    Safety Stock = Z × σ_demand × √(lead_time)

    Parameters
    ----------
    demand_std : float
        Standard deviation of daily demand.
    lead_time_days : int
        Supplier lead time in days.
    service_level : float
        Target fill-rate (0–1).  Default 0.95 → Z = 1.645.
    """
    z = _Z_SCORES.get(service_level, _Z_SCORES[_DEFAULT_SERVICE_LEVEL])
    return round(z * demand_std * math.sqrt(max(lead_time_days, 1)), 2)


def calculate_reorder_point(
    avg_daily_demand: float,
    lead_time_days: int,
    safety_stock: float,
) -> float:
    """
    Reorder Point = (avg_daily_demand × lead_time) + safety_stock
    """
    return round(avg_daily_demand * max(lead_time_days, 1) + safety_stock, 2)


def calculate_reorder_quantity(
    predicted_demand: float,
    current_stock: float,
    safety_stock: float,
    reorder_point: float,
) -> float:
    """
    If current_stock < reorder_point:
        reorder_quantity = predicted_demand - current_stock + safety_stock
    Else:
        reorder_quantity = 0
    Always clamp to zero (never order a negative amount).
    """
    if current_stock < reorder_point:
        qty = predicted_demand - current_stock + safety_stock
        return round(max(qty, 0.0), 2)
    return 0.0


def calculate_suggested_order_date(lead_time_days: int, reorder_quantity: float) -> Optional[str]:
    """
    If an order is required (reorder_quantity > 0), the suggested date
    is today + 1 day (place order tomorrow so goods arrive in lead_time).
    """
    if reorder_quantity <= 0:
        return None
    return (date.today() + timedelta(days=1)).isoformat()


def compute_confidence_score(mape: float) -> float:
    """
    confidence_score = 1 - (MAPE / 100), clamped to [0, 1].
    """
    return round(max(0.0, min(1.0, 1.0 - mape / 100.0)), 4)


def determine_risk_level(
    predicted_demand: float,
    current_stock: float,
    avg_volatility: float,
) -> str:
    """
    Risk classification:
        CRITICAL   → predicted_demand > current_stock
        VOLATILE   → high demand variability (CV > threshold)
        OVERSTOCK  → stock covers demand by OVERSTOCK_RATIO or more
        NORMAL     → everything looks healthy
    """
    if predicted_demand > current_stock:
        return "CRITICAL"
    if avg_volatility > _VOLATILE_THRESHOLD:
        return "VOLATILE"
    if current_stock >= _OVERSTOCK_RATIO * max(predicted_demand, 1):
        return "OVERSTOCK"
    return "NORMAL"


# ────────────────────────────────────────────────────────────────────────────
# Model loading helpers
# ────────────────────────────────────────────────────────────────────────────

def _load_or_train_models(
    medicine_id: int,
    model_dir: str,
) -> tuple:
    """
    Try to load cached Prophet + ARIMA models.
    If they don't exist, trigger training and then load.

    Returns
    -------
    (ProphetModel, ArimaModel, daily_df)  where daily_df may be None
    if models were loaded from cache.
    """
    prophet = ProphetModel(medicine_id)
    arima = ArimaModel(medicine_id)

    prophet_loaded = prophet.load(model_dir)
    arima_loaded = arima.load(model_dir)

    if prophet_loaded and arima_loaded:
        logger.info("medicine_id=%d: models loaded from cache.", medicine_id)
        return prophet, arima, None

    # ── Trigger training ──────────────────────────────────────────────────────
    logger.info("medicine_id=%d: models not found; triggering training.", medicine_id)
    train_result = train_for_medicine(medicine_id, model_dir=model_dir)
    if train_result.get("status") == "error":
        raise RuntimeError(f"Training failed: {train_result.get('detail')}")

    # Reload freshly trained models
    prophet.load(model_dir)
    arima.load(model_dir)

    # Also return the daily_df so we can compute demand stats
    raw_df = fetch_sales_data(medicine_id)
    daily_df = preprocess_sales_data(raw_df, medicine_id)

    return prophet, arima, daily_df


# ────────────────────────────────────────────────────────────────────────────
# Main inference function
# ────────────────────────────────────────────────────────────────────────────

def run_inference(
    medicine_id: int,
    current_stock: float,
    lead_time_days: int,
    horizon_days: int = 30,
    service_level: float = _DEFAULT_SERVICE_LEVEL,
    model_dir: Optional[str] = None,
) -> dict:
    """
    Full demand-intelligence pipeline for one medicine.

    Parameters
    ----------
    medicine_id : int
    current_stock : float
        Units currently available in stock.
    lead_time_days : int
        Days from order placement to delivery.
    horizon_days : int
        Forecast window (default 30 days).
    service_level : float
        Inventory service level for safety-stock Z-score (default 0.95).
    model_dir : str, optional
        Override for the saved_models directory.

    Returns
    -------
    dict  ← see FastAPI schema in main.py
    """
    model_dir = model_dir or SAVED_MODELS_DIR

    # ── Load / train models ───────────────────────────────────────────────────
    prophet, arima, daily_df = _load_or_train_models(medicine_id, model_dir)

    # ── Run both forecasts ────────────────────────────────────────────────────
    try:
        prophet_result = prophet.predict(horizon_days)
    except Exception as exc:
        logger.warning("medicine_id=%d: Prophet predict failed: %s", medicine_id, exc)
        prophet_result = None

    try:
        arima_result = arima.predict(horizon_days)
    except Exception as exc:
        logger.warning("medicine_id=%d: ARIMA predict failed: %s", medicine_id, exc)
        arima_result = None

    if prophet_result is None and arima_result is None:
        raise RuntimeError("Both Prophet and ARIMA prediction failed.")

    # ── Select best model ─────────────────────────────────────────────────────
    best_label = _select_best_model(prophet.get_metrics(), arima.get_metrics())

    if best_label == "Prophet" and prophet_result is not None:
        chosen_result = prophet_result
        chosen_metrics = prophet.get_metrics()
    elif arima_result is not None:
        chosen_result = arima_result
        chosen_metrics = arima.get_metrics()
    else:
        chosen_result = prophet_result
        chosen_metrics = prophet.get_metrics()
        best_label = "Prophet"

    predicted_demand = chosen_result["predicted_demand"]

    # ── Demand statistics (need daily_df) ─────────────────────────────────────
    if daily_df is not None and not daily_df.empty:
        demand_stats = get_demand_statistics(daily_df)
    else:
        # Re-fetch from DB for KPI calculation
        try:
            raw_df = fetch_sales_data(medicine_id)
            daily_df = preprocess_sales_data(raw_df, medicine_id)
            demand_stats = get_demand_statistics(daily_df)
        except Exception:
            demand_stats = {
                "avg_daily_demand": predicted_demand / horizon_days,
                "std_daily_demand": 0.0,
                "avg_volatility": 0.0,
            }

    avg_daily = demand_stats["avg_daily_demand"]
    std_daily = demand_stats["std_daily_demand"]
    avg_volatility = demand_stats["avg_volatility"]

    # ── Inventory KPIs ────────────────────────────────────────────────────────
    safety_stock = calculate_safety_stock(std_daily, lead_time_days, service_level)
    reorder_point = calculate_reorder_point(avg_daily, lead_time_days, safety_stock)
    reorder_quantity = calculate_reorder_quantity(
        predicted_demand, current_stock, safety_stock, reorder_point
    )
    suggested_order_date = calculate_suggested_order_date(lead_time_days, reorder_quantity)
    risk_level = determine_risk_level(predicted_demand, current_stock, avg_volatility)
    confidence_score = compute_confidence_score(chosen_metrics.get("mape", 0.0))

    return {
        "medicine_id": medicine_id,
        "predicted_demand_30_days": round(predicted_demand, 2),
        "safety_stock": safety_stock,
        "reorder_point": round(reorder_point, 2),
        "reorder_quantity": round(reorder_quantity, 2),
        "suggested_order_date": suggested_order_date,
        "risk_level": risk_level,
        "confidence_score": confidence_score,
        "model_used": best_label,
        # ── Supplementary diagnostics ────────────────────────────────────
        "avg_daily_demand": round(avg_daily, 4),
        "demand_std": round(std_daily, 4),
        "demand_volatility": round(avg_volatility, 4),
        "prophet_mape": prophet.get_metrics().get("mape"),
        "arima_mape": arima.get_metrics().get("mape"),
        "daily_forecast": chosen_result.get("daily_forecast", []),
    }
