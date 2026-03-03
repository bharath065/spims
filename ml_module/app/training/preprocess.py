"""
Feature engineering and data preprocessing for demand forecasting.

Performs:
- Daily sales aggregation per medicine
- Gap-filling for missing dates (zero-demand days)
- Lag features: 1, 7, 30 days
- Rolling statistics: mean (7-day), std-dev (7-day)
- Demand Volatility Index (CV = std / mean)
- Day-of-week and month encoding
"""

import logging
from typing import Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def preprocess_sales_data(
    df_raw: pd.DataFrame,
    medicine_id: int,
    date_col: str = "sale_date",
    qty_col: str = "quantity_sold",
) -> pd.DataFrame:
    """
    Transform raw sale rows into a daily feature-engineered DataFrame.

    Parameters
    ----------
    df_raw : pd.DataFrame
        Raw rows from the ``sales`` table filtered by medicine_id.
        Must have at least ``date_col`` and ``qty_col`` columns.
    medicine_id : int
        Used only for logging context.
    date_col : str
        Name of the timestamp column in df_raw.
    qty_col : str
        Name of the quantity column in df_raw.

    Returns
    -------
    pd.DataFrame
        Indexed by date with engineered features, sorted ascending.
        Columns:
            ds        – date (datetime64)
            y         – daily demand (float)
            lag_1     – 1-day lag
            lag_7     – 7-day lag
            lag_30    – 30-day lag
            roll_mean_7  – 7-day rolling mean
            roll_std_7   – 7-day rolling std
            volatility   – coefficient of variation (roll_std / roll_mean)
            dow          – day of week (0=Monday … 6=Sunday)
            month        – month (1–12)
    """
    if df_raw is None or df_raw.empty:
        logger.warning("medicine_id=%d: no raw sales data; returning empty DataFrame.", medicine_id)
        return pd.DataFrame()

    df = df_raw[[date_col, qty_col]].copy()

    # ── Step 1: Parse and floor to date ──────────────────────────────────────
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()

    # ── Step 2: Daily aggregation ─────────────────────────────────────────────
    daily = (
        df.groupby(date_col)[qty_col]
        .sum()
        .reset_index()
        .rename(columns={date_col: "ds", qty_col: "y"})
    )
    daily["ds"] = pd.to_datetime(daily["ds"])
    daily = daily.sort_values("ds").reset_index(drop=True)

    # ── Step 3: Fill missing calendar days with 0 demand ─────────────────────
    full_range = pd.date_range(start=daily["ds"].min(), end=daily["ds"].max(), freq="D")
    daily = daily.set_index("ds").reindex(full_range, fill_value=0.0).reset_index()
    daily.rename(columns={"index": "ds"}, inplace=True)
    daily["y"] = daily["y"].astype(float)

    # ── Step 4: Lag features ──────────────────────────────────────────────────
    daily["lag_1"] = daily["y"].shift(1).fillna(0.0)
    daily["lag_7"] = daily["y"].shift(7).fillna(0.0)
    daily["lag_30"] = daily["y"].shift(30).fillna(0.0)

    # ── Step 5: Rolling statistics (min_periods=1 to avoid NaN at start) ─────
    daily["roll_mean_7"] = daily["y"].rolling(window=7, min_periods=1).mean()
    daily["roll_std_7"] = daily["y"].rolling(window=7, min_periods=1).std().fillna(0.0)

    # ── Step 6: Demand Volatility Index (coefficient of variation) ────────────
    daily["volatility"] = np.where(
        daily["roll_mean_7"] > 0,
        daily["roll_std_7"] / daily["roll_mean_7"],
        0.0,
    )

    # ── Step 7: Calendar encodings ────────────────────────────────────────────
    daily["dow"] = daily["ds"].dt.dayofweek       # 0 = Monday
    daily["month"] = daily["ds"].dt.month

    logger.info(
        "medicine_id=%d: preprocessed %d records → %d daily rows (%.1f%% gap-fill).",
        medicine_id,
        len(df_raw),
        len(daily),
        100.0 * (len(daily) - df_raw.shape[0]) / max(len(daily), 1),
    )

    return daily


def get_demand_statistics(daily_df: pd.DataFrame) -> dict:
    """
    Compute summary statistics used by the inference engine.

    Returns
    -------
    dict
        avg_daily_demand, std_daily_demand, avg_volatility
    """
    if daily_df.empty:
        return {"avg_daily_demand": 0.0, "std_daily_demand": 0.0, "avg_volatility": 0.0}

    return {
        "avg_daily_demand": float(daily_df["y"].mean()),
        "std_daily_demand": float(daily_df["y"].std(ddof=1)) if len(daily_df) > 1 else 0.0,
        "avg_volatility": float(daily_df["volatility"].mean()) if "volatility" in daily_df.columns else 0.0,
    }
