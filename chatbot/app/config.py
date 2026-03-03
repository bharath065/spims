"""
config.py — Chatbot configuration loaded from environment variables.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    backend_url: str
    ml_url: str
    timeout: float
    port: int
    log_level: str


def get_settings() -> Settings:
    return Settings(
        backend_url=os.getenv("BACKEND_URL", "http://backend:8000"),
        ml_url=os.getenv("ML_URL", "http://ml_module:8001"),
        timeout=float(os.getenv("TIMEOUT", "10.0")),
        port=int(os.getenv("CHATBOT_PORT", "8002")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


settings = get_settings()
