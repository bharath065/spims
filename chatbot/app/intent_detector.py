"""
intent_detector.py — Hybrid intent classification: keyword rules + fallback scoring.

Returns an Intent enum value given a user message string.
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    STOCK_QUERY = "STOCK_QUERY"
    EXPIRY_CHECK = "EXPIRY_CHECK"
    PRODUCT_INFO = "PRODUCT_INFO"
    REPORT = "REPORT"
    FORECAST = "FORECAST"
    REORDER_REQUEST = "REORDER_REQUEST"
    REORDER_CONFIRMATION = "REORDER_CONFIRMATION"
    SUPPLIER_NOTIFY = "SUPPLIER_NOTIFY"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Keyword rules: (pattern_list, weight) per intent
# ---------------------------------------------------------------------------
_RULES: List[Tuple[Intent, List[str], int]] = [
    # Reorder confirmation — must come before REORDER_REQUEST
    (
        Intent.REORDER_CONFIRMATION,
        [
            r"\byes\b",
            r"\bconfirm\b",
            r"\bproceed\b",
            r"\bgo ahead\b",
            r"\bapprove\b",
            r"\bdo it\b",
            r"\bconfirm.{0,15}reorder\b",
            r"\breorder.{0,15}confirm\b",
        ],
        10,
    ),
    # Reorder request
    (
        Intent.REORDER_REQUEST,
        [
            r"\breorder\b",
            r"\border.{0,10}more\b",
            r"\bplace.{0,10}order\b",
            r"\bshould.{0,15}order\b",
            r"\bneed.{0,15}order\b",
            r"\brestock\b",
            r"\breplenish\b",
        ],
        8,
    ),
    # Forecast
    (
        Intent.FORECAST,
        [
            r"\bforecast\b",
            r"\bpredict\b",
            r"\bdemand\b",
            r"\bhow much.{0,20}need\b",
            r"\bnext.{0,10}month\b",
            r"\bnext.{0,10}week\b",
            r"\bwill.{0,15}need\b",
            r"\bprojected?\b",
        ],
        8,
    ),
    # Expiry check
    (
        Intent.EXPIRY_CHECK,
        [
            r"\bexpir\b",
            r"\bexpiry\b",
            r"\bexpiration\b",
            r"\bexpired?\b",
            r"\bshelf.?life\b",
            r"\buse.?by\b",
            r"\bbest.?before\b",
        ],
        8,
    ),
    # Report
    (
        Intent.REPORT,
        [
            r"\breport\b",
            r"\bsales\b",
            r"\bwaste\b",
            r"\banalytics\b",
            r"\bsummary\b",
            r"\boverview\b",
            r"\bstatistic\b",
            r"\bperformance\b",
        ],
        6,
    ),
    # Supplier notify
    (
        Intent.SUPPLIER_NOTIFY,
        [
            r"\bsupplier\b",
            r"\bnotif\b",
            r"\bcontact.{0,10}supplier\b",
            r"\bemail.{0,10}supplier\b",
            r"\bsend.{0,10}order\b",
        ],
        7,
    ),
    # Stock query
    (
        Intent.STOCK_QUERY,
        [
            r"\bstock\b",
            r"\bhow much\b",
            r"\bhow many\b",
            r"\bavailable\b",
            r"\binventory\b",
            r"\bunits?\b",
            r"\bquantity\b",
            r"\bremaining\b",
            r"\bleft\b",
            r"\blow.?stock\b",
        ],
        6,
    ),
    # Product info
    (
        Intent.PRODUCT_INFO,
        [
            r"\binfo\b",
            r"\binformation\b",
            r"\bdetails?\b",
            r"\bdescription\b",
            r"\bwhat is\b",
            r"\btell me about\b",
            r"\bshow.{0,10}medicine\b",
        ],
        4,
    ),
]


def _score_message(message: str) -> Dict[Intent, int]:
    """Score each intent by counting weighted keyword matches."""
    lower = message.lower()
    scores: Dict[Intent, int] = {intent: 0 for intent in Intent}

    for intent, patterns, weight in _RULES:
        for pattern in patterns:
            if re.search(pattern, lower):
                scores[intent] += weight

    return scores


def detect_intent(message: str) -> Intent:
    """
    Primary entry point.
    Returns the best-matching Intent or Intent.UNKNOWN if no threshold is met.
    """
    if not message or not message.strip():
        logger.warning("Empty message received — returning UNKNOWN intent.")
        return Intent.UNKNOWN

    scores = _score_message(message)
    best_intent = max(scores, key=lambda k: scores[k])
    best_score = scores[best_intent]

    logger.debug(
        "Intent scores: %s | Best: %s (%d)",
        {k.value: v for k, v in scores.items() if v > 0},
        best_intent.value,
        best_score,
    )

    # Minimum score threshold to avoid noise
    if best_score < 4:
        logger.info("No intent matched confidently (best score=%d). Returning UNKNOWN.", best_score)
        return Intent.UNKNOWN

    logger.info("Detected intent: %s (score=%d)", best_intent.value, best_score)
    return best_intent
