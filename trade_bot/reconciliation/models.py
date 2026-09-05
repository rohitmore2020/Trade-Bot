"""
Reconciliation Domain Models and Data Structures.

Provides structured types for discrepancy categorization, audit records,
and reconciliation reports between broker and internal platform state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from trade_bot.domain.models import utc_now


class DiscrepancySeverity(str, Enum):
    """Severity of a detected state discrepancy."""
    CRITICAL = "CRITICAL"  # Financial/risk violation; requires halt & manual intervention
    WARNING = "WARNING"    # Non-fatal mismatch (e.g. price rounding, auto-synchronized status)
    INFO = "INFO"          # Informational alignment (e.g. expected delay)


class DiscrepancyType(str, Enum):
    """Categorization of discrepancy between broker and internal state."""
    POSITION_BROKER_ONLY = "POSITION_BROKER_ONLY"                # Broker has position, bot is flat (rogue position)
    POSITION_BOT_ONLY = "POSITION_BOT_ONLY"                      # Bot believes position exists, broker is flat (phantom position)
    POSITION_QUANTITY_MISMATCH = "POSITION_QUANTITY_MISMATCH"    # Quantities differ on same symbol
    POSITION_PRICE_MISMATCH = "POSITION_PRICE_MISMATCH"          # Average price differs beyond tolerance
    ORDER_UNKNOWN_BROKER = "ORDER_UNKNOWN_BROKER"                # Untracked order active on broker
    ORDER_STATUS_MISMATCH = "ORDER_STATUS_MISMATCH"              # Order status differs between broker and bot
    ORDER_DUPLICATE = "ORDER_DUPLICATE"                          # Duplicate orders on broker
    PROTECTIVE_STOP_MISSING = "PROTECTIVE_STOP_MISSING"          # Active position lacks active protective SL order
    PROTECTIVE_STOP_QUANTITY_MISMATCH = "PROTECTIVE_STOP_QUANTITY_MISMATCH" # SL order qty != position qty
    FILL_MISSING_LOCALLY = "FILL_MISSING_LOCALLY"                # Broker confirmed fill not recorded in local ledger


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """Individual discrepancy detected during reconciliation."""
    discrepancy_type: DiscrepancyType
    severity: DiscrepancySeverity
    symbol: Optional[str]
    details: Dict[str, Any]
    is_auto_resolved: bool = False
    resolution_note: Optional[str] = None
    detected_at: datetime = field(default_factory=utc_now)


@dataclass
class ReconciliationReport:
    """Consolidated report produced by a reconciliation run."""
    timestamp: datetime = field(default_factory=utc_now)
    is_clean: bool = True
    discrepancies: List[Discrepancy] = field(default_factory=list)
    auto_resolved_count: int = 0
    requires_manual_intervention: bool = False
    halt_trading: bool = False
    execution_time_ms: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.WARNING)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "is_clean": self.is_clean,
            "discrepancies_count": len(self.discrepancies),
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "auto_resolved_count": self.auto_resolved_count,
            "requires_manual_intervention": self.requires_manual_intervention,
            "halt_trading": self.halt_trading,
            "execution_time_ms": self.execution_time_ms,
            "discrepancies": [
                {
                    "type": d.discrepancy_type.value,
                    "severity": d.severity.value,
                    "symbol": d.symbol,
                    "is_auto_resolved": d.is_auto_resolved,
                    "resolution_note": d.resolution_note,
                    "details": d.details,
                    "detected_at": d.detected_at.isoformat(),
                }
                for d in self.discrepancies
            ],
        }
