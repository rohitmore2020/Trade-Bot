"""
NSE Trading Calendar and Session Management.

Manages official market hours (09:15 to 15:30 IST), trading days, weekends,
and official Indian exchange holidays to enable deterministic bar grid calculations.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Optional, Set
from zoneinfo import ZoneInfo
from trade_bot.config.constants import (
    IST_TIMEZONE,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
)

# Standard NSE Holidays for 2023-2026 (Major national and financial holidays)
NSE_HOLIDAYS: Set[date] = {
    # 2023
    date(2023, 1, 26),  # Republic Day
    date(2023, 3, 7),   # Holi
    date(2023, 3, 30),  # Ram Navami
    date(2023, 4, 4),   # Mahavir Jayanti
    date(2023, 4, 7),   # Good Friday
    date(2023, 4, 14),  # Dr. Ambedkar Jayanti
    date(2023, 4, 21),  # Id-Ul-Fitr
    date(2023, 5, 1),   # Maharashtra Day
    date(2023, 6, 29),  # Bakri Id
    date(2023, 8, 15),  # Independence Day
    date(2023, 9, 19),  # Ganesh Chaturthi
    date(2023, 10, 2),  # Mahatma Gandhi Jayanti
    date(2023, 10, 24), # Dussehra
    date(2023, 11, 14), # Diwali Balipratipada
    date(2023, 11, 27), # Gurunanak Jayanti
    date(2023, 12, 25), # Christmas
    # 2024
    date(2024, 1, 22),  # Special Holiday
    date(2024, 1, 26),  # Republic Day
    date(2024, 3, 8),   # Mahashivratri
    date(2024, 3, 25),  # Holi
    date(2024, 3, 29),  # Good Friday
    date(2024, 4, 11),  # Id-Ul-Fitr
    date(2024, 4, 17),  # Ram Navami
    date(2024, 5, 1),   # Maharashtra Day
    date(2024, 5, 20),  # Parliamentary Elections (Mumbai)
    date(2024, 6, 17),  # Bakri Id
    date(2024, 7, 17),  # Muharram
    date(2024, 8, 15),  # Independence Day
    date(2024, 10, 2),  # Mahatma Gandhi Jayanti
    date(2024, 11, 1),  # Diwali Laxmi Pujan
    date(2024, 11, 15), # Gurunanak Jayanti
    date(2024, 11, 20), # Maharashtra Assembly Elections
    date(2024, 12, 25), # Christmas
    # 2025
    date(2025, 1, 26),  # Republic Day (Sunday)
    date(2025, 2, 26),  # Mahashivratri
    date(2025, 3, 14),  # Holi
    date(2025, 3, 31),  # Id-Ul-Fitr
    date(2025, 4, 10),  # Mahavir Jayanti
    date(2025, 4, 14),  # Dr. Ambedkar Jayanti
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 1),   # Maharashtra Day
    date(2025, 6, 7),   # Bakri Id
    date(2025, 8, 15),  # Independence Day
    date(2025, 8, 27),  # Ganesh Chaturthi
    date(2025, 10, 2),  # Mahatma Gandhi Jayanti
    date(2025, 10, 21), # Diwali Laxmi Pujan
    date(2025, 10, 22), # Diwali Balipratipada
    date(2025, 11, 5),  # Gurunanak Jayanti
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 17),  # Holi
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 12, 25), # Christmas
}


class NSETradingCalendar:
    """
    Validates trading dates and generates expected intraday candle timestamps.
    """

    def __init__(self, additional_holidays: Optional[Set[date]] = None) -> None:
        self.holidays: Set[date] = set(NSE_HOLIDAYS)
        if additional_holidays:
            self.holidays.update(additional_holidays)

    def is_trading_day(self, d: date) -> bool:
        """Return True if `d` is a weekday (Monday-Friday) and not a scheduled holiday."""
        if d.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            return False
        return d not in self.holidays

    def get_trading_days(self, start_date: date, end_date: date) -> List[date]:
        """Return sorted list of trading days between start_date and end_date (inclusive)."""
        current = start_date
        days: List[date] = []
        while current <= end_date:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def get_expected_bar_timestamps(
        self,
        trading_date: date,
        timeframe_seconds: int = 300,
    ) -> List[datetime]:
        """
        Generate expected start timestamps for continuous session bars (09:15 to 15:30 IST).
        For 5-minute bars (300s), generates exactly 75 bar timestamps:
        09:15:00, 09:20:00, ..., 15:25:00.
        """
        if not self.is_trading_day(trading_date):
            return []

        open_dt = datetime.combine(trading_date, MARKET_OPEN_TIME, tzinfo=IST_TIMEZONE)
        close_dt = datetime.combine(trading_date, MARKET_CLOSE_TIME, tzinfo=IST_TIMEZONE)

        delta = timedelta(seconds=timeframe_seconds)
        timestamps: List[datetime] = []
        current = open_dt
        while current < close_dt:
            timestamps.append(current)
            current += delta

        return timestamps

    def get_expected_bars_count(self, timeframe_seconds: int = 300) -> int:
        """Return the expected count of bars in a normal trading day (75 for 5m, 375 for 1m)."""
        session_seconds = (15 * 3600 + 30 * 60) - (9 * 3600 + 15 * 60)  # 22500 seconds (375 mins)
        return session_seconds // timeframe_seconds
