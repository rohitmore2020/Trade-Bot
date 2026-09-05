"""
Historical Market Data Downloaders and Ingestion Adapters.

Modular, replaceable data downloaders supporting CSV imports, Yahoo Finance v8 chart feeds,
and Upstox historical endpoints. Converts external responses into normalized DataFrames.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
import requests
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.data.interfaces import IHistoricalDataProvider
from trade_bot.data.normalization import normalize_ohlcv_dataframe
from trade_bot.domain.exceptions import MarketDataError


class BaseHistoricalDownloader(IHistoricalDataProvider, ABC):
    """Abstract base class for replaceable historical data downloaders."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        ...


class CSVHistoricalDataLoader(BaseHistoricalDownloader):
    """
    Ingests historical data from local CSV files (e.g. broker intraday exports or NSE bhavcopies).
    """

    def __init__(self, data_directory: str | Path = "data/raw_csv") -> None:
        self.data_dir = Path(data_directory)

    @property
    def source_name(self) -> str:
        return "CSVHistoricalDataLoader"

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        file_path = self.data_dir / f"{symbol.upper()}_{timeframe_seconds}s.csv"
        if not file_path.exists():
            # Try plain symbol.csv
            file_path = self.data_dir / f"{symbol.upper()}.csv"
            if not file_path.exists():
                raise MarketDataError(f"No CSV data found for symbol '{symbol}' in {self.data_dir}")

        raw_df = pd.read_csv(file_path)
        normalized = normalize_ohlcv_dataframe(raw_df, symbol=symbol)

        # Filter date range
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=IST_TIMEZONE)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=IST_TIMEZONE)
        return normalized[(normalized["timestamp"] >= start_dt) & (normalized["timestamp"] <= end_dt)]


class YahooHistoricalDataLoader(BaseHistoricalDownloader):
    """
    Downloader for public historical feeds (NIFTY 50, India VIX, NSE stocks).
    Translates symbols:
      - NIFTY 50 -> ^NSEI
      - INDIA VIX -> ^INDIAVIX
      - RELIANCE -> RELIANCE.NS
    """

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    @property
    def source_name(self) -> str:
        return "YahooHistoricalDataLoader"

    def _format_symbol(self, symbol: str) -> str:
        sym = symbol.upper().strip()
        if sym in ("NIFTY", "NIFTY50", "NIFTY 50", "^NSEI"):
            return "^NSEI"
        if sym in ("INDIAVIX", "INDIA VIX", "VIX", "^INDIAVIX"):
            return "^INDIAVIX"
        if not sym.endswith(".NS") and not sym.startswith("^"):
            return f"{sym}.NS"
        return sym

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe_seconds: int = 300,
        start_date: date = date(2024, 1, 1),
        end_date: date = date(2024, 1, 31),
    ) -> pd.DataFrame:
        ticker = self._format_symbol(symbol)

        # Map interval (Yahoo supports: 1m, 2m, 5m, 15m, 30m, 60m, 1d)
        if timeframe_seconds == 60:
            interval = "1m"
        elif timeframe_seconds == 300:
            interval = "5m"
        elif timeframe_seconds == 900:
            interval = "15m"
        elif timeframe_seconds == 86400:
            interval = "1d"
        else:
            interval = "5m"

        start_ts = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).timestamp())

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {
            "period1": start_ts,
            "period2": end_ts,
            "interval": interval,
            "includePrePost": "false",
        }

        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                raise MarketDataError(
                    f"Yahoo API returned HTTP {resp.status_code} for {ticker}: {resp.text[:200]}"
                )
            data = resp.json()
            result = data.get("chart", {}).get("result")
            if not result:
                error_msg = data.get("chart", {}).get("error", {}).get("description", "Unknown error")
                raise MarketDataError(f"No chart data returned for {ticker}: {error_msg}")

            chart_data = result[0]
            timestamps = chart_data.get("timestamp", [])
            indicators = chart_data.get("indicators", {}).get("quote", [{}])[0]

            opens = indicators.get("open", [])
            highs = indicators.get("high", [])
            lows = indicators.get("low", [])
            closes = indicators.get("close", [])
            volumes = indicators.get("volume", [])

            if not timestamps:
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])

            records = []
            for i, ts_val in enumerate(timestamps):
                # Filter out None values
                if (
                    opens[i] is not None
                    and highs[i] is not None
                    and lows[i] is not None
                    and closes[i] is not None
                ):
                    dt_val = datetime.fromtimestamp(ts_val, tz=timezone.utc).astimezone(IST_TIMEZONE)
                    vol_val = volumes[i] if (i < len(volumes) and volumes[i] is not None) else 0
                    records.append({
                        "timestamp": dt_val,
                        "open": float(opens[i]),
                        "high": float(highs[i]),
                        "low": float(lows[i]),
                        "close": float(closes[i]),
                        "volume": int(vol_val),
                        "symbol": symbol.upper().replace(".NS", ""),
                    })

            df = pd.DataFrame(records)
            return normalize_ohlcv_dataframe(df, symbol=symbol)
        except Exception as e:
            if isinstance(e, MarketDataError):
                raise
            raise MarketDataError(f"Failed to fetch data for {symbol} from Yahoo API: {e}") from e
