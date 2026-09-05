"""
Deterministic Simulation Clock.

Maintains strictly forward-advancing simulation time in IST timezone.
Provides session boundary and trading window checks.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.data.calendar import NSETradingCalendar
from trade_bot.indicators.exceptions import LookAheadViolationError


class SimulationClock:
    """
    Deterministic clock for event-driven backtesting.
    Enforces strictly non-decreasing time progression in Indian Standard Time (IST).
    """

    ORB_START = time(9, 15, 0)
    ORB_END = time(9, 30, 0)
    TRADING_WINDOW_START = time(9, 45, 0)
    TRADING_WINDOW_END = time(14, 30, 0)
    SESSION_CLOSE = time(15, 30, 0)

    def __init__(
        self,
        initial_time: Optional[datetime] = None,
        calendar: Optional[NSETradingCalendar] = None,
    ) -> None:
        self.tz = IST_TIMEZONE if isinstance(IST_TIMEZONE, ZoneInfo) else ZoneInfo(str(IST_TIMEZONE))
        self.calendar = calendar or NSETradingCalendar()

        if initial_time is not None:
            if initial_time.tzinfo is None:
                self._current_time = initial_time.replace(tzinfo=self.tz)
            else:
                self._current_time = initial_time.astimezone(self.tz)
        else:
            self._current_time = datetime(2024, 1, 1, 9, 15, 0, tzinfo=self.tz)

    @property
    def current_time(self) -> datetime:
        return self._current_time

    def advance_to(self, timestamp: datetime) -> None:
        """
        Advance clock forward in time.
        Raises LookAheadViolationError if an attempt is made to move backward in time.
        """
        target = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=self.tz)
        target_ist = target.astimezone(self.tz)

        if target_ist < self._current_time:
            raise LookAheadViolationError(
                f"Clock regression violation: cannot advance to past time {target_ist} from {self._current_time}"
            )

        self._current_time = target_ist

    def is_trading_day(self, dt: Optional[datetime] = None) -> bool:
        t = self._normalize(dt)
        return self.calendar.is_trading_day(t)

    def is_orb_period(self, dt: Optional[datetime] = None) -> bool:
        """True if time is between 09:15 and 09:30 IST."""
        t = self._normalize(dt).time()
        return self.ORB_START <= t < self.ORB_END

    def is_trading_window(self, dt: Optional[datetime] = None) -> bool:
        """True if time is within the allowed trading window (09:45 to 14:30 IST)."""
        t = self._normalize(dt).time()
        return self.TRADING_WINDOW_START <= t < self.TRADING_WINDOW_END

    def is_forced_exit_time(self, dt: Optional[datetime] = None) -> bool:
        """True if mandatory square-off time (14:30:00 IST) has been reached or exceeded."""
        t = self._normalize(dt).time()
        return t >= self.TRADING_WINDOW_END

    def is_session_close_time(self, dt: Optional[datetime] = None) -> bool:
        """True if official session end (15:30:00 IST) has been reached."""
        t = self._normalize(dt).time()
        return t >= self.SESSION_CLOSE

    def _normalize(self, dt: Optional[datetime]) -> datetime:
        if dt is None:
            return self._current_time
        if dt.tzinfo is None:
            return dt.replace(tzinfo=self.tz)
        return dt.astimezone(self.tz)
