"""
Training orchestrator for pharmacy demand forecasting.

Responsibilities:
- Fetch historical sales data from the pharmacy database
- Preprocess and engineer features via preprocess.py
- Train both Prophet and ARIMA models
- Evaluate and compare via MAPE; select the winner
- Persist both models to disk
- Return rich evaluation results
"""

import logging
import os
import sys
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

# ── Path resolution so this module works as a CLI script ─────────────────────
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from training.preprocess import preprocess_sales_data, get_demand_statistics
from models.prophet_model import ProphetModel
from models.arima_model import ArimaModel

logger = logging.getLogger(__name__)

# ── Configuration from environment ───────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmacy_user:pharmacy_pass@localhost:5432/pharmacy_db",
)
SAVED_MODELS_DIR = os.getenv(
    "SAVED_MODELS_DIR",
    os.path.join(_APP_DIR, "saved_models"),
)


# ────────────────────────────────────────────────────────────────────────────
# Database helpers
# ────────────────────────────────────────────────────────────────────────────

def fetch_sales_data(medicine_id: int) -> pd.DataFrame:
    """
    Query the ``sales`` table for a specific medicine and return a DataFrame.

    Returns
    -------
    pd.DataFrame with columns: sale_date, quantity_sold
    """
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    query = text(
        """
        SELECT sale_date, quantity_sold
        FROM   sales
        WHERE  medicine_id = :medicine_id
        ORDER  BY sale_date ASC
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"medicine_id": medicine_id})
    logger.info("medicine_id=%d: fetched %d raw sale rows.", medicine_id, len(df))
    return df


def fetch_medicine_metadata(medicine_id: int) -> dict:
    """
    Fetch lead_time_days and current_stock for the given medicine.
    """
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    query = text(
        """
        SELECT lead_time_days, current_stock
        FROM   medicines
        WHERE  id = :medicine_id
        """
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"medicine_id": medicine_id}).mappings().fetchone()
    if result is None:
        logger.warning("medicine_id=%d: not found in medicines table.", medicine_id)
        return {"lead_time_days": 7, "current_stock": 0}
    return dict(result)


# ────────────────────────────────────────────────────────────────────────────
# Model selection
# ────────────────────────────────────────────────────────────────────────────

def _select_best_model(
    prophet_metrics: dict,
    arima_metrics: dict,
) -> str:
    """
    Compare Prophet vs ARIMA by MAPE.
    Lower MAPE wins; fall back to Prophet on ties or missing data.
    """
    prophet_mape = prophet_metrics.get("mape", float("inf"))
    arima_mape = arima_metrics.get("mape", float("inf"))

    if prophet_mape <= arima_mape:
        return "Prophet"
    return "ARIMA"


# ────────────────────────────────────────────────────────────────────────────
# Public training entry point
# ────────────────────────────────────────────────────────────────────────────

def train_for_medicine(
    medicine_id: int,
    model_dir: Optional[str] = None,
    force_retrain: bool = False,
) -> dict:
    """
    End-to-end training pipeline for one medicine.

    Parameters
    ----------
    medicine_id : int
    model_dir : str, optional
        Where to save .pkl files (defaults to SAVED_MODELS_DIR env var).
    force_retrain : bool
        If True, retrain even if saved models already exist.

    Returns
    -------
    dict
        {
            model_used, prophet_metrics, arima_metrics,
            demand_stats, model_dir, status
        }
    """
    model_dir = model_dir or SAVED_MODELS_DIR
    os.makedirs(model_dir, exist_ok=True)

    # ── Check if models already exist ────────────────────────────────────────
    prophet_path = os.path.join(model_dir, f"medicine_{medicine_id}_prophet.pkl")
    arima_path = os.path.join(model_dir, f"medicine_{medicine_id}_arima.pkl")
    already_exists = os.path.exists(prophet_path) and os.path.exists(arima_path)

    if already_exists and not force_retrain:
        logger.info("medicine_id=%d: saved models found; skipping training.", medicine_id)
        # Load metrics from saved models for reporting
        prophet = ProphetModel(medicine_id)
        arima = ArimaModel(medicine_id)
        prophet.load(model_dir)
        arima.load(model_dir)
        best = _select_best_model(prophet.get_metrics(), arima.get_metrics())
        return {
            "status": "loaded_from_cache",
            "model_used": best,
            "prophet_metrics": prophet.get_metrics(),
            "arima_metrics": arima.get_metrics(),
            "demand_stats": {},
            "model_dir": model_dir,
        }

    # ── Fetch & preprocess ───────────────────────────────────────────────────
    logger.info("medicine_id=%d: starting training pipeline.", medicine_id)
    try:
        raw_df = fetch_sales_data(medicine_id)
    except Exception as exc:
        logger.error("medicine_id=%d: DB fetch failed: %s", medicine_id, exc)
        return {"status": "error", "detail": str(exc)}

    daily_df = preprocess_sales_data(raw_df, medicine_id)
    if daily_df.empty:
        return {"status": "error", "detail": "No sales data available for this medicine."}

    demand_stats = get_demand_statistics(daily_df)

    # ── Train Prophet ─────────────────────────────────────────────────────────
    prophet = ProphetModel(medicine_id)
    try:
        prophet_metrics = prophet.train(daily_df)
        prophet.save(model_dir)
    except Exception as exc:
        logger.error("medicine_id=%d: Prophet training failed: %s", medicine_id, exc)
        prophet_metrics = {}

    # ── Train ARIMA ───────────────────────────────────────────────────────────
    arima = ArimaModel(medicine_id)
    try:
        arima_metrics = arima.train(daily_df)
        arima.save(model_dir)
    except Exception as exc:
        logger.error("medicine_id=%d: ARIMA training failed: %s", medicine_id, exc)
        arima_metrics = {}

    # ── Select best ───────────────────────────────────────────────────────────
    best_model = _select_best_model(prophet_metrics, arima_metrics)
    logger.info("medicine_id=%d: best model → %s", medicine_id, best_model)

    return {
        "status": "trained",
        "model_used": best_model,
        "prophet_metrics": prophet_metrics,
        "arima_metrics": arima_metrics,
        "demand_stats": demand_stats,
        "model_dir": model_dir,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

    parser = argparse.ArgumentParser(description="Train demand forecasting models")
    parser.add_argument("medicine_id", type=int, help="Medicine ID to train on")
    parser.add_argument("--force", action="store_true", help="Force retraining even if models exist")
    parser.add_argument("--model-dir", default=None, help="Directory to save models")
    args = parser.parse_args()

    result = train_for_medicine(
        medicine_id=args.medicine_id,
        model_dir=args.model_dir,
        force_retrain=args.force,
    )
    print(json.dumps(result, indent=2))
