"""
Prophet forecasting model wrapper.

Wraps Facebook Prophet for per-medicine demand forecasting.
Handles training, evaluation (MAPE / MAE / RMSE), and 30-day prediction.
"""

import logging
import os
from typing import Optional

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ProphetModel:
    """
    Wraps Prophet for pharmacy demand forecasting.

    Usage
    -----
    model = ProphetModel(medicine_id=1)
    model.train(daily_df)           # Fit on historical data
    result = model.predict(30)      # Forecast next 30 days
    metrics = model.get_metrics()
    model.save("/path/to/saved_models")
    model.load("/path/to/saved_models")
    """

    def __init__(self, medicine_id: int):
        self.medicine_id = medicine_id
        self._model = None
        self.metrics: dict = {}
        self._is_trained: bool = False

    # ── Training ──────────────────────────────────────────────────────────────

    def train(self, daily_df: pd.DataFrame, test_size: int = 30) -> dict:
        """
        Fit Prophet on ``daily_df`` and evaluate on a held-out tail.

        Parameters
        ----------
        daily_df : pd.DataFrame
            Must have columns ``ds`` (datetime) and ``y`` (float demand).
        test_size : int
            Number of trailing days used as a test set.

        Returns
        -------
        dict
            Evaluation metrics: mae, rmse, mape.
        """
        try:
            from prophet import Prophet  # lazy import — not always installed
        except ImportError as exc:
            raise ImportError(
                "prophet is not installed. Run: pip install prophet"
            ) from exc

        if daily_df is None or daily_df.empty:
            logger.warning("medicine_id=%d: empty DataFrame; skipping Prophet training.", self.medicine_id)
            return {}

        df = daily_df[["ds", "y"]].copy()
        df["ds"] = pd.to_datetime(df["ds"])

        if len(df) < test_size + 10:
            # Not enough data — train on everything without evaluation
            logger.warning(
                "medicine_id=%d: only %d rows; training Prophet without test split.",
                self.medicine_id, len(df),
            )
            train_df, test_df = df, pd.DataFrame()
        else:
            train_df = df.iloc[: -test_size]
            test_df = df.iloc[-test_size :]

        # ── Fit ───────────────────────────────────────────────────────────────
        self._model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            seasonality_mode="multiplicative",
            interval_width=0.95,
        )
        self._model.fit(train_df)
        self._is_trained = True
        logger.info("medicine_id=%d: Prophet fitted on %d rows.", self.medicine_id, len(train_df))

        # ── Evaluate ──────────────────────────────────────────────────────────
        if not test_df.empty:
            future = self._model.make_future_dataframe(periods=test_size)
            forecast = self._model.predict(future)
            y_pred = forecast.tail(test_size)["yhat"].clip(lower=0).values
            y_true = test_df["y"].values
            self.metrics = _compute_metrics(y_true, y_pred)
            logger.info(
                "medicine_id=%d: Prophet metrics — MAE=%.2f, RMSE=%.2f, MAPE=%.2f%%",
                self.medicine_id, self.metrics["mae"], self.metrics["rmse"], self.metrics["mape"],
            )

        return self.metrics

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, horizon_days: int = 30) -> dict:
        """
        Predict total demand over the next ``horizon_days``.

        Returns
        -------
        dict
            predicted_demand (total), daily_forecast (list), confidence bands
        """
        if not self._is_trained or self._model is None:
            raise RuntimeError("Prophet model is not trained yet. Call train() first.")

        future = self._model.make_future_dataframe(periods=horizon_days)
        forecast = self._model.predict(future)
        fc_tail = forecast.tail(horizon_days)

        daily_values = fc_tail["yhat"].clip(lower=0).tolist()
        lower_bound = fc_tail["yhat_lower"].clip(lower=0).tolist()
        upper_bound = fc_tail["yhat_upper"].clip(lower=0).tolist()

        return {
            "predicted_demand": float(sum(daily_values)),
            "daily_forecast": [round(v, 2) for v in daily_values],
            "lower_bound": [round(v, 2) for v in lower_bound],
            "upper_bound": [round(v, 2) for v in upper_bound],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, model_dir: str) -> str:
        """Serialize the fitted model to disk."""
        if not self._is_trained:
            raise RuntimeError("Cannot save: model has not been trained.")
        os.makedirs(model_dir, exist_ok=True)
        path = os.path.join(model_dir, f"medicine_{self.medicine_id}_prophet.pkl")
        joblib.dump({"model": self._model, "metrics": self.metrics}, path)
        logger.info("Prophet model saved → %s", path)
        return path

    def load(self, model_dir: str) -> bool:
        """Load a previously saved model. Returns True on success."""
        path = os.path.join(model_dir, f"medicine_{self.medicine_id}_prophet.pkl")
        if not os.path.exists(path):
            return False
        payload = joblib.load(path)
        self._model = payload["model"]
        self.metrics = payload.get("metrics", {})
        self._is_trained = True
        logger.info("Prophet model loaded ← %s", path)
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        return self.metrics

    def is_trained(self) -> bool:
        return self._is_trained


# ── Shared metric computation ─────────────────────────────────────────────────

def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """MAE, RMSE, MAPE — safe against zero-division."""
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    # Avoid division by zero in MAPE
    mask = y_true != 0
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100) if mask.any() else 0.0
    return {"mae": round(mae, 4), "rmse": round(rmse, 4), "mape": round(mape, 4)}
