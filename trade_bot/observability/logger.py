"""
Structured Logging Configuration.

Supports JSON structured logs and formatted console output with context tracking.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict
from trade_bot.config.settings import LogFormat, LoggingConfig, LogLevel


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "context") and isinstance(record.context, dict):
            log_obj.update(record.context)
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def configure_logging(config: LoggingConfig) -> logging.Logger:
    """Configure root and application loggers."""
    root = logging.getLogger("trade_bot")
    root.setLevel(getattr(logging, config.level.value))

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()

    # Formatter selection
    if config.format == LogFormat.JSON:
        formatter: logging.Formatter = JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Console Handler
    if config.enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # File Handler
    if config.enable_file and config.log_dir:
        log_dir = Path(config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "trade_bot.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger under 'trade_bot'."""
    return logging.getLogger(f"trade_bot.{name}")
