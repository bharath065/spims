"""
ARIMA forecasting model wrapper.

Uses statsmodels ARIMA as a classical time-series fallback.
Auto-tunes (p, d, q) order via pmdarima (auto_arima) when available;
falls back to a sensible default (1,1,1) otherwise.
"""

import logging
import os
from typing import Optional, Tuple

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default ARIMA order used when auto-tuning is unavailable
_DEFAULT_ORDER: Tuple[int, int, int] = (1, 1, 1)


class ArimaModel:
    """
    Wraps ARIMA for pharmacy demand forecasting.

    Usage
    -----
    model = ArimaModel(medicine_id=1)
    model.train(daily_df)
    result = model.predict(30)
    metrics = model.get_metrics()
    model.save("/path/to/saved_models")
    model.load("/path/to/saved_models")
    """

    def __init__(self, medicine_id: int):
        self.medicine_id = medicine_id
        self._model = None          # fitted ARIMA result object
        self._order: Tuple[int, int, int] = _DEFAULT_ORDER
        self.metrics: dict = {}
        self._is_trained: bool = False
        self._last_train_values: Optional[np.ndarray] = None   # for future forecasts

    # ── Training ──────────────────────────────────────────────────────────────

    def train(self, daily_df: pd.DataFrame, test_size: int = 30) -> dict:
        """
        Fit ARIMA on ``daily_df``.  Auto-tunes order if pmdarima is installed.

        Parameters
        ----------
        daily_df : pd.DataFrame
            Must have ``ds`` and ``y`` columns.
        test_size : int
            Trailing days used as hold-out test set.

        Returns
        -------
        dict  – evaluation metrics (mae, rmse, mape)
        """
        if daily_df is None or daily_df.empty:
            logger.warning("medicine_id=%d: empty DataFrame; skipping ARIMA training.", self.medicine_id)
            return {}

        series = daily_df["y"].astype(float).values

        if len(series) < test_size + 10:
            logger.warning(
                "medicine_id=%d: only %d rows; ARIMA training without test split.",
                self.medicine_id, len(series),
            )
            train_series, test_series = series, np.array([])
        else:
            train_series = series[: -test_size]
            test_series = series[-test_size :]

        # ── Order selection ──────────────────────────────────────────────────
        self._order = self._select_order(train_series)
        logger.info("medicine_id=%d: ARIMA order selected: %s", self.medicine_id, self._order)

        # ── Fit ───────────────────────────────────────────────────────────────
        from statsmodels.tsa.arima.model import ARIMA as _ARIMA
        arima = _ARIMA(train_series, order=self._order)
        try:
            self._model = arima.fit()
        except Exception as exc:
            logger.error("medicine_id=%d: ARIMA fit failed: %s — falling back to (1,1,1).", self.medicine_id, exc)
            self._order = _DEFAULT_ORDER
            self._model = _ARIMA(train_series, order=self._order).fit()

        self._last_train_values = train_series
        self._is_trained = True
        logger.info("medicine_id=%d: ARIMA fitted on %d rows.", self.medicine_id, len(train_series))

        # ── Evaluate ──────────────────────────────────────────────────────────
        if len(test_series) > 0:
            forecast_result = self._model.forecast(steps=len(test_series))
            y_pred = np.clip(forecast_result, 0, None)
            self.metrics = _compute_metrics(test_series, y_pred)
            logger.info(
                "medicine_id=%d: ARIMA metrics — MAE=%.2f, RMSE=%.2f, MAPE=%.2f%%",
                self.medicine_id, self.metrics["mae"], self.metrics["rmse"], self.metrics["mape"],
            )

        return self.metrics

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, horizon_days: int = 30) -> dict:
        """
        Predict total demand over the next ``horizon_days``.

        Returns
        -------
        dict – predicted_demand, daily_forecast, confidence_interval
        """
        if not self._is_trained or self._model is None:
            raise RuntimeError("ARIMA model is not trained yet. Call train() first.")

        forecast_result = self._model.get_forecast(steps=horizon_days)
        daily_values = np.clip(forecast_result.predicted_mean, 0, None).tolist()

        # 95% confidence interval
        conf_int = forecast_result.conf_int(alpha=0.05)
        lower_bound = np.clip(conf_int.iloc[:, 0], 0, None).tolist()
        upper_bound = np.clip(conf_int.iloc[:, 1], 0, None).tolist()

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
        path = os.path.join(model_dir, f"medicine_{self.medicine_id}_arima.pkl")
        joblib.dump({
            "model": self._model,
            "order": self._order,
            "metrics": self.metrics,
        }, path)
        logger.info("ARIMA model saved → %s", path)
        return path

    def load(self, model_dir: str) -> bool:
        """Load a previously saved model. Returns True on success."""
        path = os.path.join(model_dir, f"medicine_{self.medicine_id}_arima.pkl")
        if not os.path.exists(path):
            return False
        payload = joblib.load(path)
        self._model = payload["model"]
        self._order = payload.get("order", _DEFAULT_ORDER)
        self.metrics = payload.get("metrics", {})
        self._is_trained = True
        logger.info("ARIMA model loaded ← %s", path)
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        return self.metrics

    def is_trained(self) -> bool:
        return self._is_trained

    @staticmethod
    def _select_order(series: np.ndarray) -> Tuple[int, int, int]:
        """
        Try pmdarima auto_arima for order selection; fall back to (1,1,1).
        """
        try:
            import pmdarima as pm  # optional dependency
            auto = pm.auto_arima(
                series,
                start_p=0, max_p=3,
                start_q=0, max_q=3,
                d=None,          # let ADF test decide
                seasonal=False,
                information_criterion="aic",
                stepwise=True,
                suppress_warnings=True,
                error_action="ignore",
            )
            return auto.order
        except Exception:
            return _DEFAULT_ORDER


# ── Shared metric computation ─────────────────────────────────────────────────

def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mask = y_true != 0
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100) if mask.any() else 0.0
    return {"mae": round(mae, 4), "rmse": round(rmse, 4), "mape": round(mape, 4)}
