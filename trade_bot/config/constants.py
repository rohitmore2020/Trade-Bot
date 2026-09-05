"""
Indian NSE Market and System Constants.

All timestamps and market hours are aligned with the Indian Standard Time (IST) zone.
"""

from datetime import time
from zoneinfo import ZoneInfo

# Timezone
IST_TIMEZONE = ZoneInfo("Asia/Kolkata")

# NSE Cash Equity Trading Timings (IST)
MARKET_PRE_OPEN_START = time(9, 0, 0)
MARKET_PRE_OPEN_END = time(9, 8, 0)
MARKET_OPEN_TIME = time(9, 15, 0)
MARKET_CLOSE_TIME = time(15, 30, 0)

# Intraday Strategy Operational Timings
ORB_START_TIME = time(9, 15, 0)
ORB_END_TIME = time(9, 30, 0)  # Default 15-minute Opening Range
NO_NEW_ENTRIES_TIME = time(15, 0, 0)  # Stop opening new positions
INTRADAY_SQUARE_OFF_TIME = time(15, 15, 0)  # Mandatory square-off for MIS orders

# NSE Equity Defaults
DEFAULT_EXCHANGE = "NSE"
DEFAULT_SEGMENT = "EQ"
DEFAULT_CURRENCY = "INR"
NSE_DEFAULT_TICK_SIZE = 0.05  # Standard tick size for NSE Equities >= Rs 250
MIN_EQUITY_TICK_SIZE = 0.01  # For low price instruments or special series
LOT_SIZE_EQUITY = 1  # 1 share for cash equity segment
