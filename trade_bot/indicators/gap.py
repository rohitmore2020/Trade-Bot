"""
Overnight Gap Calculator Indicator.

Calculates the percentage gap between the current session opening price
and the previous session's closing price.
Used by the universe scanner to identify stocks with overnight momentum:
Gap % = ((Day_Open - Prev_Close) / Prev_Close) * 100
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class GapDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class GapInfo:
    """Detailed overnight gap breakdown."""
    prev_close: float
    day_open: float
    gap_points: float
    gap_pct: float
    absolute_gap_pct: float
    direction: GapDirection
    meets_threshold: bool


class GapCalculator:
    """
    Computes overnight percentage gap and evaluates scanner eligibility.
    """

    def __init__(self, min_gap_pct: float = 1.0) -> None:
        """
        Parameters:
            min_gap_pct: Minimum absolute gap percentage required (default 1.0%).
        """
        self.min_gap_pct = min_gap_pct

    def calculate(
        self,
        day_open: float,
        prev_close: float,
    ) -> Optional[GapInfo]:
        """
        Calculate overnight gap from day open and previous close.
        Returns None if prev_close <= 0 or day_open <= 0.
        """
        if prev_close <= 0 or day_open <= 0:
            return None

        gap_points = round(day_open - prev_close, 2)
        gap_pct = round((gap_points / prev_close) * 100.0, 4)
        abs_gap_pct = round(abs(gap_pct), 4)

        if gap_points > 0:
            direction = GapDirection.UP
        elif gap_points < 0:
            direction = GapDirection.DOWN
        else:
            direction = GapDirection.FLAT

        meets_threshold = abs_gap_pct >= self.min_gap_pct

        return GapInfo(
            prev_close=prev_close,
            day_open=day_open,
            gap_points=gap_points,
            gap_pct=gap_pct,
            absolute_gap_pct=abs_gap_pct,
            direction=direction,
            meets_threshold=meets_threshold,
        )
