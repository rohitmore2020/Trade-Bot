"""
Data Normalization Pipeline.

Normalizes raw vendor/exchange data into clean, standardized DataFrames and domain Candle objects.
Enforces explicit Asia/Kolkata timezone awareness, uppercase symbols, and numeric precision.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import numpy as np
import pandas as pd
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.exceptions import DomainValidationError
from trade_bot.domain.models import Candle


REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def normalize_ohlcv_dataframe(
    df: pd.DataFrame,
    symbol: str,
    target_timezone: str = "Asia/Kolkata",
) -> pd.DataFrame:
    """
    Standardize an arbitrary OHLCV DataFrame into production schema:
    Columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']
    - Timestamp: tz-aware datetime64[ns, Asia/Kolkata]
    - Prices: float64
    - Volume: int64
    - Symbol: uppercase string
    - Sorted chronologically and deduplicated.
    """
    if df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS + ["symbol"])

    # Map case-insensitive column names
    col_map = {}
    for col in df.columns:
        clean = str(col).strip().lower()
        if clean in ("timestamp", "datetime", "date", "time"):
            col_map[col] = "timestamp"
        elif clean in ("open", "o"):
            col_map[col] = "open"
        elif clean in ("high", "h"):
            col_map[col] = "high"
        elif clean in ("low", "l"):
            col_map[col] = "low"
        elif clean in ("close", "c", "adj close", "adj_close"):
            if "close" not in col_map.values():
                col_map[col] = "close"
        elif clean in ("volume", "vol", "v"):
            col_map[col] = "volume"

    cleaned_df = df.rename(columns=col_map).copy()

    # Verify all required columns exist
    missing = [c for c in REQUIRED_COLUMNS if c not in cleaned_df.columns]
    if missing:
        raise DomainValidationError(f"DataFrame is missing required OHLCV columns: {missing}")

    # Standardize Timestamps
    if not pd.api.types.is_datetime64_any_dtype(cleaned_df["timestamp"]):
        cleaned_df["timestamp"] = pd.to_datetime(cleaned_df["timestamp"], utc=True)

    # Convert to target timezone (Asia/Kolkata)
    if cleaned_df["timestamp"].dt.tz is None:
        cleaned_df["timestamp"] = cleaned_df["timestamp"].dt.tz_localize(target_timezone)
    else:
        cleaned_df["timestamp"] = cleaned_df["timestamp"].dt.tz_convert(target_timezone)

    # Standardize numeric types
    cleaned_df["open"] = pd.to_numeric(cleaned_df["open"], errors="coerce").astype(float)
    cleaned_df["high"] = pd.to_numeric(cleaned_df["high"], errors="coerce").astype(float)
    cleaned_df["low"] = pd.to_numeric(cleaned_df["low"], errors="coerce").astype(float)
    cleaned_df["close"] = pd.to_numeric(cleaned_df["close"], errors="coerce").astype(float)
    cleaned_df["volume"] = pd.to_numeric(cleaned_df["volume"], errors="coerce").fillna(0).astype("int64")

    # Round prices to 2 decimal places (NSE tick precision)
    cleaned_df["open"] = cleaned_df["open"].round(2)
    cleaned_df["high"] = cleaned_df["high"].round(2)
    cleaned_df["low"] = cleaned_df["low"].round(2)
    cleaned_df["close"] = cleaned_df["close"].round(2)

    # Attach symbol
    cleaned_df["symbol"] = symbol.upper().strip()

    # Drop NaNs in price data
    cleaned_df = cleaned_df.dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()

    # Sort strictly chronologically
    cleaned_df = cleaned_df.sort_values(by="timestamp").reset_index(drop=True)

    # Deduplicate timestamps (keep last recorded update)
    cleaned_df = cleaned_df.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    return cleaned_df[REQUIRED_COLUMNS + ["symbol"]]


def dataframe_to_candles(
    df: pd.DataFrame,
    timeframe_seconds: int = 300,
) -> List[Candle]:
    """Convert a normalized DataFrame into a list of immutable domain Candle instances."""
    candles: List[Candle] = []
    for row in df.itertuples(index=False):
        ts = row.timestamp.to_pydatetime() if hasattr(row.timestamp, "to_pydatetime") else row.timestamp
        candles.append(
            Candle(
                symbol=row.symbol,
                timestamp=ts,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=int(row.volume),
                timeframe_seconds=timeframe_seconds,
                is_closed=True,
            )
        )
    return candles


def candles_to_dataframe(candles: List[Candle]) -> pd.DataFrame:
    """Convert a list of domain Candle instances into a normalized DataFrame."""
    if not candles:
        return pd.DataFrame(columns=REQUIRED_COLUMNS + ["symbol"])

    records = [
        {
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "symbol": c.symbol,
        }
        for c in candles
    ]
    df = pd.DataFrame(records)
    return normalize_ohlcv_dataframe(df, symbol=candles[0].symbol)
