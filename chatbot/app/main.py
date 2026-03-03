"""
main.py — FastAPI chatbot application.

Exposes: POST /chat
Port: 8002

Flow:
  1. Receive user message
  2. Detect intent
  3. Extract medicine name/ID from message
  4. Call appropriate backend/ML endpoints via api_caller
  5. Format response via response_builder
  6. Return structured JSON
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .api_caller import (
    confirm_reorder,
    get_all_alerts,
    get_all_medicines,
    get_expiring_medicines,
    get_low_stock_medicines,
    get_medicine_by_id,
    get_sales_report,
    get_waste_report,
    predict_demand,
    suggest_reorder,
)
from .config import settings
from .intent_detector import Intent, detect_intent
from .response_builder import (
    build_error_response,
    build_expiry_response,
    build_forecast_response,
    build_low_stock_response,
    build_product_info_response,
    build_reorder_confirmation_response,
    build_reorder_suggestion_response,
    build_sales_report_response,
    build_stock_response,
    build_supplier_notification,
    build_waste_report_response,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("chatbot")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Pharmacy Chatbot",
    description="A pharmacist-facing chatbot that communicates exclusively via HTTP APIs.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    # Optional context values the frontend can provide to assist routing
    medicine_id: Optional[int] = Field(None, description="Medicine ID if already known")
    session_id: Optional[str] = Field(None, description="Session identifier for follow-up handling")
    # Pending state: carries reorder context across a confirmation turn
    pending_reorder: Optional[Dict[str, Any]] = Field(
        None, description="Reorder context awaiting confirmation"
    )


class ChatResponse(BaseModel):
    intent: str
    data: Any = None
    message: str
    action_triggered: bool = False
    awaiting_confirmation: bool = False
    supplier_notification: Optional[Dict] = None


# ---------------------------------------------------------------------------
# Medicine extraction helpers
# ---------------------------------------------------------------------------

_MEDICINE_NAME_RE = re.compile(
    r"""
    (?:for|of|about|on|stock|reorder|expiry|forecast|predict|demand|info)\s+
    ([A-Za-z][A-Za-z0-9\s\-]{1,40})
    """,
    re.VERBOSE | re.IGNORECASE,
)

_MEDICINE_ID_RE = re.compile(r"\b(?:id|#|medicine[_\s]id)[:\s]*(\d+)\b", re.IGNORECASE)


def _extract_medicine_id_from_message(message: str) -> Optional[int]:
    m = _MEDICINE_ID_RE.search(message)
    if m:
        return int(m.group(1))
    # Bare numeric ID, e.g. "stock for 5"
    m2 = re.search(r"\b(\d{1,6})\b", message)
    if m2:
        return int(m2.group(1))
    return None


def _extract_medicine_name_from_message(message: str) -> Optional[str]:
    m = _MEDICINE_NAME_RE.search(message)
    if m:
        return m.group(1).strip()
    return None


async def _resolve_medicine_id(
    message: str,
    provided_id: Optional[int],
) -> Optional[int]:
    """
    Try to resolve a medicine ID from:
     1. Explicitly provided by frontend
     2. Extracted from message text
     3. Fuzzy name match via GET /medicines
    """
    if provided_id is not None:
        return provided_id

    mid = _extract_medicine_id_from_message(message)
    if mid:
        return mid

    name = _extract_medicine_name_from_message(message)
    if name:
        medicines = await get_all_medicines()
        if medicines:
            name_lower = name.lower().strip()
            for med in medicines:
                if name_lower in (med.get("name") or "").lower():
                    return med.get("id") or med.get("medicine_id")

    return None


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------


async def _handle_stock_query(message: str, medicine_id: Optional[int]) -> ChatResponse:
    mid = await _resolve_medicine_id(message, medicine_id)
    if mid is None:
        # No specific medicine — return low-stock list
        data = await get_low_stock_medicines()
        if data is None:
            built = build_error_response("service_unavailable")
            return ChatResponse(intent=Intent.STOCK_QUERY, message=built["message"])
        built = build_low_stock_response(data)
        return ChatResponse(intent=Intent.STOCK_QUERY, data=built["data"], message=built["message"])

    medicine = await get_medicine_by_id(mid)
    if medicine is None:
        built = build_error_response("service_unavailable")
        return ChatResponse(intent=Intent.STOCK_QUERY, message=built["message"])
    built = build_stock_response(medicine)
    return ChatResponse(intent=Intent.STOCK_QUERY, data=built["data"], message=built["message"])


async def _handle_expiry_check(message: str) -> ChatResponse:
    # Parse days from message if given, default to 30
    days = 30
    m = re.search(r"(\d+)\s*days?", message, re.IGNORECASE)
    if m:
        days = int(m.group(1))
    data = await get_expiring_medicines(days)
    if data is None:
        built = build_error_response("service_unavailable")
        return ChatResponse(intent=Intent.EXPIRY_CHECK, message=built["message"])
    built = build_expiry_response(data)
    return ChatResponse(intent=Intent.EXPIRY_CHECK, data=built["data"], message=built["message"])


async def _handle_product_info(message: str, medicine_id: Optional[int]) -> ChatResponse:
    mid = await _resolve_medicine_id(message, medicine_id)
    if mid is None:
        built = build_error_response("missing_medicine")
        return ChatResponse(intent=Intent.PRODUCT_INFO, message=built["message"])
    medicine = await get_medicine_by_id(mid)
    if medicine is None:
        built = build_error_response("service_unavailable")
        return ChatResponse(intent=Intent.PRODUCT_INFO, message=built["message"])
    built = build_product_info_response(medicine)
    return ChatResponse(intent=Intent.PRODUCT_INFO, data=built["data"], message=built["message"])


async def _handle_report(message: str) -> ChatResponse:
    lower = message.lower()
    if "waste" in lower:
        data = await get_waste_report()
        if data is None:
            built = build_error_response("service_unavailable")
            return ChatResponse(intent=Intent.REPORT, message=built["message"])
        built = build_waste_report_response(data)
    else:
        data = await get_sales_report()
        if data is None:
            built = build_error_response("service_unavailable")
            return ChatResponse(intent=Intent.REPORT, message=built["message"])
        built = build_sales_report_response(data)
    return ChatResponse(intent=Intent.REPORT, data=built["data"], message=built["message"])


async def _handle_forecast(message: str, medicine_id: Optional[int]) -> ChatResponse:
    mid = await _resolve_medicine_id(message, medicine_id)
    if mid is None:
        built = build_error_response("missing_medicine")
        return ChatResponse(intent=Intent.FORECAST, message=built["message"])

    # Parse period from message
    period = 30
    m = re.search(r"(\d+)\s*days?", message, re.IGNORECASE)
    if m:
        period = int(m.group(1))

    forecast = await predict_demand(mid, period)
    if forecast is None:
        built = build_error_response("service_unavailable")
        return ChatResponse(intent=Intent.FORECAST, message=built["message"])

    # Fetch current stock for context (best-effort — no crash if fails)
    current_stock: Optional[int] = None
    medicine = await get_medicine_by_id(mid)
    if medicine:
        current_stock = (
            medicine.get("quantity_in_stock")
            or medicine.get("stock_quantity")
            or medicine.get("stock")
        )

    built = build_forecast_response(forecast, current_stock)
    return ChatResponse(intent=Intent.FORECAST, data=built["data"], message=built["message"])


async def _handle_reorder_request(message: str, medicine_id: Optional[int]) -> ChatResponse:
    mid = await _resolve_medicine_id(message, medicine_id)
    if mid is None:
        built = build_error_response("missing_medicine")
        return ChatResponse(intent=Intent.REORDER_REQUEST, message=built["message"])

    suggestion = await suggest_reorder(mid)
    if suggestion is None:
        built = build_error_response("service_unavailable")
        return ChatResponse(intent=Intent.REORDER_REQUEST, message=built["message"])

    built = build_reorder_suggestion_response(suggestion)
    return ChatResponse(
        intent=Intent.REORDER_REQUEST,
        data=built["data"],
        message=built["message"],
        awaiting_confirmation=built.get("awaiting_confirmation", True),
    )


async def _handle_reorder_confirmation(pending_reorder: Optional[Dict]) -> ChatResponse:
    """
    Confirm a pending reorder. Expects pending_reorder to carry
    {medicine_id, quantity, medicine_name, supplier_name} from the previous turn.
    """
    if not pending_reorder:
        return ChatResponse(
            intent=Intent.REORDER_CONFIRMATION,
            message=(
                "I do not have an active reorder to confirm.\n"
                "Please first request a reorder suggestion, e.g.:\n"
                '  "Should we reorder Paracetamol?"'
            ),
        )

    medicine_id = pending_reorder.get("medicine_id")
    quantity = pending_reorder.get("quantity") or pending_reorder.get("suggested_quantity")
    medicine_name = pending_reorder.get("medicine_name") or pending_reorder.get("name") or "Medicine"
    supplier_name = pending_reorder.get("supplier_name") or pending_reorder.get("supplier") or "ABC Pharma"

    confirmation = await confirm_reorder(medicine_id, quantity)
    if confirmation is None:
        built = build_error_response("service_unavailable")
        return ChatResponse(
            intent=Intent.REORDER_CONFIRMATION,
            message=built["message"],
            action_triggered=False,
        )

    # Build simulated supplier notification
    supplier_notif = build_supplier_notification(
        medicine_name=medicine_name,
        supplier_name=supplier_name,
        quantity=quantity or 0,
    )

    built = build_reorder_confirmation_response(confirmation, supplier_notif)
    return ChatResponse(
        intent=Intent.REORDER_CONFIRMATION,
        data=built["data"],
        message=built["message"],
        action_triggered=True,
        supplier_notification=supplier_notif,
    )


async def _handle_supplier_notify(message: str, medicine_id: Optional[int]) -> ChatResponse:
    """
    Supplier notification: stub only. No real email sent.
    Requires pending_reorder information — treat similarly to confirmation.
    """
    mid = await _resolve_medicine_id(message, medicine_id)
    medicine_name = "the requested medicine"
    if mid:
        med = await get_medicine_by_id(mid)
        if med:
            medicine_name = med.get("name") or medicine_name

    supplier_notif = build_supplier_notification(
        medicine_name=medicine_name,
        supplier_name="ABC Pharma",
        quantity=0,
    )
    message_text = (
        f"Supplier notification logged (SIMULATED).\n\n"
        f"  • Medicine  : {medicine_name}\n"
        f"  • Supplier  : {supplier_notif['supplier_name']}\n"
        f"  • Expected delivery : {supplier_notif['expected_delivery']}\n\n"
        "No real communication has been sent."
    )
    return ChatResponse(
        intent=Intent.SUPPLIER_NOTIFY,
        data=supplier_notif,
        message=message_text,
        action_triggered=False,
        supplier_notification=supplier_notif,
    )


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    logger.info("Incoming message: %r | medicine_id=%s | session=%s",
                request.message, request.medicine_id, request.session_id)

    intent = detect_intent(request.message)
    logger.info("Classified intent: %s", intent)

    if intent == Intent.STOCK_QUERY:
        response = await _handle_stock_query(request.message, request.medicine_id)

    elif intent == Intent.EXPIRY_CHECK:
        response = await _handle_expiry_check(request.message)

    elif intent == Intent.PRODUCT_INFO:
        response = await _handle_product_info(request.message, request.medicine_id)

    elif intent == Intent.REPORT:
        response = await _handle_report(request.message)

    elif intent == Intent.FORECAST:
        response = await _handle_forecast(request.message, request.medicine_id)

    elif intent == Intent.REORDER_REQUEST:
        response = await _handle_reorder_request(request.message, request.medicine_id)

    elif intent == Intent.REORDER_CONFIRMATION:
        response = await _handle_reorder_confirmation(request.pending_reorder)

    elif intent == Intent.SUPPLIER_NOTIFY:
        response = await _handle_supplier_notify(request.message, request.medicine_id)

    else:
        built = build_error_response("unknown_intent")
        response = ChatResponse(intent=Intent.UNKNOWN, message=built["message"])

    logger.info("Response intent=%s action_triggered=%s", response.intent, response.action_triggered)
    return response


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "pharmacy-chatbot",
        "version": "1.0.0",
        "backend_url": settings.backend_url,
        "ml_url": settings.ml_url,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )
