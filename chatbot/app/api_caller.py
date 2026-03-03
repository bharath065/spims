"""
api_caller.py — Async HTTP client for backend and ML service calls.

Rules:
- All URLs sourced from config only.
- Full async with httpx.AsyncClient.
- Graceful error fallback: never raises raw exceptions to callers.
- Configurable timeout.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.timeout)


async def _get(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict | List]:
    """Perform GET and return parsed JSON, or None on any error."""
    try:
        async with _client() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        logger.error("GET %s timed out after %.1fs", url, settings.timeout)
        return None
    except httpx.HTTPStatusError as exc:
        logger.error("GET %s returned HTTP %d: %s", url, exc.response.status_code, exc.response.text)
        return None
    except Exception as exc:
        logger.error("GET %s failed: %s", url, exc)
        return None


async def _post(url: str, payload: Dict[str, Any]) -> Optional[Dict]:
    """Perform POST and return parsed JSON, or None on any error."""
    try:
        async with _client() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        logger.error("POST %s timed out after %.1fs", url, settings.timeout)
        return None
    except httpx.HTTPStatusError as exc:
        logger.error("POST %s returned HTTP %d: %s", url, exc.response.status_code, exc.response.text)
        return None
    except Exception as exc:
        logger.error("POST %s failed: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Backend — Inventory
# ---------------------------------------------------------------------------

async def get_all_medicines() -> Optional[List]:
    url = f"{settings.backend_url}/medicines"
    return await _get(url)


async def get_medicine_by_id(medicine_id: int) -> Optional[Dict]:
    url = f"{settings.backend_url}/medicines/{medicine_id}"
    return await _get(url)


async def get_low_stock_medicines() -> Optional[List]:
    url = f"{settings.backend_url}/medicines/low-stock"
    return await _get(url)


async def get_expiring_medicines(days: int = 30) -> Optional[List]:
    url = f"{settings.backend_url}/medicines/expiring"
    return await _get(url, params={"days": days})


# ---------------------------------------------------------------------------
# Backend — Sales & Reports
# ---------------------------------------------------------------------------

async def get_sales_report() -> Optional[Dict]:
    url = f"{settings.backend_url}/sales/report"
    return await _get(url)


async def get_waste_report() -> Optional[Dict]:
    url = f"{settings.backend_url}/sales/waste-report"
    return await _get(url)


# ---------------------------------------------------------------------------
# Backend — Alerts
# ---------------------------------------------------------------------------

async def get_all_alerts() -> Optional[List]:
    url = f"{settings.backend_url}/alerts"
    return await _get(url)


async def get_expiry_alerts() -> Optional[List]:
    url = f"{settings.backend_url}/alerts/expiry"
    return await _get(url)


async def get_stock_alerts() -> Optional[List]:
    url = f"{settings.backend_url}/alerts/stock"
    return await _get(url)


# ---------------------------------------------------------------------------
# Backend — Reorder
# ---------------------------------------------------------------------------

async def suggest_reorder(medicine_id: int) -> Optional[Dict]:
    url = f"{settings.backend_url}/reorder/suggest"
    return await _post(url, {"medicine_id": medicine_id})


async def confirm_reorder(medicine_id: int, quantity: int) -> Optional[Dict]:
    url = f"{settings.backend_url}/reorder/confirm"
    return await _post(url, {"medicine_id": medicine_id, "quantity": quantity})


# ---------------------------------------------------------------------------
# ML Service — Demand Forecasting
# ---------------------------------------------------------------------------

async def predict_demand(medicine_id: int, period_days: int = 30) -> Optional[Dict]:
    url = f"{settings.ml_url}/predict-demand"
    return await _post(url, {"medicine_id": medicine_id, "period_days": period_days})
