"""
response_builder.py — Pure message formatting layer.

Rules:
 - NO business logic.
 - NO arithmetic on stock numbers.
 - NO direct API calls.
 - Formats raw API data into pharmacist-friendly strings and structured dicts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_date(date_str: Optional[str]) -> str:
    """Convert ISO date string to human-readable format."""
    if not date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d %B %Y")
    except Exception:
        return date_str


def _medicine_name(data: Dict) -> str:
    return data.get("name") or data.get("medicine_name") or "Unknown Medicine"


def _units(value: Any) -> str:
    try:
        return f"{int(value):,} units"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Stock Query
# ---------------------------------------------------------------------------


def build_stock_response(medicine_data: Dict) -> Dict:
    name = _medicine_name(medicine_data)
    stock = medicine_data.get("quantity_in_stock") or medicine_data.get("stock_quantity") or medicine_data.get("stock")
    threshold = medicine_data.get("minimum_threshold") or medicine_data.get("reorder_level") or medicine_data.get("min_stock")
    batch = medicine_data.get("batch_number") or medicine_data.get("batch")

    lines = [f"Stock status for {name}:"]
    lines.append(f"  • Current stock : {_units(stock)}")
    if threshold is not None:
        lines.append(f"  • Minimum threshold : {_units(threshold)}")
    if batch:
        lines.append(f"  • Active batch : {batch}")

    return {"message": "\n".join(lines), "data": medicine_data}


def build_low_stock_response(medicines: List[Dict]) -> Dict:
    if not medicines:
        message = "No medicines are currently below their minimum stock threshold."
    else:
        lines = [f"The following {len(medicines)} medicine(s) are below minimum stock levels:\n"]
        for med in medicines:
            name = _medicine_name(med)
            stock = med.get("quantity_in_stock") or med.get("stock_quantity") or med.get("stock")
            lines.append(f"  • {name} — {_units(stock)}")
        message = "\n".join(lines)

    return {"message": message, "data": medicines}


# ---------------------------------------------------------------------------
# Expiry Check
# ---------------------------------------------------------------------------


def build_expiry_response(medicines: List[Dict]) -> Dict:
    if not medicines:
        message = "No medicines are approaching their expiry date within the requested period."
    else:
        lines = [f"{len(medicines)} medicine batch(es) expiring soon:\n"]
        for med in medicines:
            name = _medicine_name(med)
            expiry = _fmt_date(med.get("expiry_date") or med.get("expiration_date"))
            batch = med.get("batch_number") or med.get("batch") or "N/A"
            lines.append(f"  • {name} | Batch: {batch} | Expires: {expiry}")
        message = "\n".join(lines)

    return {"message": message, "data": medicines}


# ---------------------------------------------------------------------------
# Product Info
# ---------------------------------------------------------------------------


def build_product_info_response(medicine_data: Dict) -> Dict:
    name = _medicine_name(medicine_data)
    lines = [f"Product details for {name}:\n"]
    field_map = {
        "id": "Medicine ID",
        "category": "Category",
        "unit": "Unit",
        "manufacturer": "Manufacturer",
        "description": "Description",
        "quantity_in_stock": "Current Stock",
        "minimum_threshold": "Minimum Threshold",
        "expiry_date": "Expiry Date",
    }
    for key, label in field_map.items():
        value = medicine_data.get(key)
        if value is not None:
            if "date" in key.lower():
                value = _fmt_date(str(value))
            elif "quantity" in key.lower() or "threshold" in key.lower():
                value = _units(value)
            lines.append(f"  • {label} : {value}")

    return {"message": "\n".join(lines), "data": medicine_data}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_sales_report_response(report: Dict) -> Dict:
    lines = ["Sales Report Summary:\n"]
    field_map = {
        "total_sales": "Total Sales",
        "total_revenue": "Total Revenue",
        "period": "Period",
        "top_medicine": "Top Selling Medicine",
        "transactions": "Total Transactions",
    }
    for key, label in field_map.items():
        value = report.get(key)
        if value is not None:
            lines.append(f"  • {label} : {value}")
    if len(lines) == 1:
        lines.append("  Report data received — please review attached data object.")

    return {"message": "\n".join(lines), "data": report}


def build_waste_report_response(report: Dict) -> Dict:
    lines = ["Waste Report Summary:\n"]
    field_map = {
        "total_waste": "Total Units Wasted",
        "waste_value": "Estimated Waste Value",
        "period": "Period",
        "top_wasted_medicine": "Highest Waste Medicine",
    }
    for key, label in field_map.items():
        value = report.get(key)
        if value is not None:
            lines.append(f"  • {label} : {value}")
    if len(lines) == 1:
        lines.append("  Waste report data received — please review attached data object.")

    return {"message": "\n".join(lines), "data": report}


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def build_forecast_response(forecast: Dict, current_stock: Optional[int] = None) -> Dict:
    predicted = forecast.get("predicted_demand")
    confidence = forecast.get("confidence")

    lines = ["Demand Forecast:\n"]
    if predicted is not None:
        lines.append(f"  • Predicted demand (30 days) : {_units(predicted)}")
    if confidence is not None:
        conf_pct = f"{float(confidence) * 100:.0f}%"
        lines.append(f"  • Forecast confidence       : {conf_pct}")
    if current_stock is not None:
        lines.append(f"  • Current stock             : {_units(current_stock)}")

    # Recommendation purely based on API data, no arithmetic
    if predicted is not None and current_stock is not None:
        if int(current_stock) < int(predicted):
            lines.append("\nRecommendation: Current stock is below predicted demand.\nA reorder is recommended before the period begins.")
        else:
            lines.append("\nCurrent stock appears sufficient for the forecasted demand period.")

    return {"message": "\n".join(lines), "data": forecast}


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


def build_reorder_suggestion_response(suggestion: Dict) -> Dict:
    medicine = suggestion.get("medicine_name") or suggestion.get("name") or "the requested medicine"
    qty = suggestion.get("suggested_quantity") or suggestion.get("quantity") or suggestion.get("recommended_quantity")
    supplier = suggestion.get("supplier_name") or suggestion.get("supplier")

    lines = [f"Reorder suggestion for {medicine}:\n"]
    if qty is not None:
        lines.append(f"  • Suggested quantity : {_units(qty)}")
    if supplier:
        lines.append(f"  • Preferred supplier : {supplier}")
    lines.append("\nWould you like me to confirm and place this reorder?")

    return {
        "message": "\n".join(lines),
        "data": suggestion,
        "awaiting_confirmation": True,
    }


def build_reorder_confirmation_response(confirmation: Dict, supplier_notification: Dict) -> Dict:
    medicine = confirmation.get("medicine_name") or confirmation.get("name") or "the medicine"
    qty = confirmation.get("quantity") or confirmation.get("confirmed_quantity")
    supplier = supplier_notification.get("supplier_name", "the supplier")
    delivery = _fmt_date(supplier_notification.get("expected_delivery"))

    message = (
        f"Reorder confirmed.\n\n"
        f"  • Medicine  : {medicine}\n"
        f"  • Quantity  : {_units(qty)}\n"
        f"  • Supplier  : {supplier}\n"
        f"  • Expected delivery : {delivery}\n\n"
        f"Supplier {supplier} has been notified. (Notification: SIMULATED)"
    )

    return {
        "message": message,
        "data": confirmation,
        "supplier_notification": supplier_notification,
    }


# ---------------------------------------------------------------------------
# Supplier Notification (stub)
# ---------------------------------------------------------------------------


def build_supplier_notification(
    medicine_name: str,
    supplier_name: str,
    quantity: int,
) -> Dict:
    """
    Constructs a simulated supplier notification payload.
    No real email or API call is made — this is a stub only.
    """
    # Delivery estimate: 7 days from now
    today = datetime.utcnow()
    delivery_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    return {
        "supplier_name": supplier_name,
        "medicine": medicine_name,
        "quantity": quantity,
        "expected_delivery": delivery_date,
        "notification_status": "SIMULATED",
    }


# ---------------------------------------------------------------------------
# Error / Unknown
# ---------------------------------------------------------------------------


def build_error_response(reason: str = "service_unavailable") -> Dict:
    messages = {
        "service_unavailable": (
            "The pharmacy system is temporarily unavailable.\n"
            "Please try again in a moment or contact your system administrator."
        ),
        "unknown_intent": (
            "I could not understand your request.\n\n"
            "You can ask me about:\n"
            "  • Medication stock levels\n"
            "  • Expiry dates\n"
            "  • Demand forecasts\n"
            "  • Reorder suggestions\n"
            "  • Sales and waste reports"
        ),
        "missing_medicine": (
            "I was unable to identify the specific medicine in your request.\n"
            "Please include the medicine name or ID, for example:\n"
            '  "How much Paracetamol is in stock?"\n'
            '  "Forecast demand for medicine ID 5"'
        ),
    }
    return {"message": messages.get(reason, "An unexpected error occurred. Please try again.")}
