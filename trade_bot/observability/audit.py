"""
Financial Audit Trail Logger.

Append-only, structured audit logger for financial transactions, risk checks,
and state changes to guarantee compliance and retrospective determinism.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional


class AuditLogger:
    """
    Records immutable financial events to an append-only JSONL file.
    """

    def __init__(self, audit_dir: str = "audit", filename: Optional[str] = None) -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.file_path = self.audit_dir / (filename or f"audit_{date_str}.jsonl")

    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Append an audit record to disk."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "data": payload,
        }
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_order_event(self, event_type: str, client_order_id: str, details: Dict[str, Any]) -> None:
        """Convenience method for logging order lifecycle events."""
        self.record_event(
            event_type=f"ORDER_{event_type.upper()}",
            payload={"client_order_id": client_order_id, **details},
        )

    def log_risk_event(self, decision: str, reason: str, rule: str, details: Dict[str, Any]) -> None:
        """Convenience method for logging risk rejections or circuit breaker trips."""
        self.record_event(
            event_type=f"RISK_{decision.upper()}",
            payload={"rule": rule, "reason": reason, **details},
        )
