"""
Unit tests for the Historical Market Data Validation, Calendar, Normalization, and Storage Pipeline.
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import pandas as pd
import pytest
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.data.calendar import NSETradingCalendar
from trade_bot.data.normalization import (
    candles_to_dataframe,
    dataframe_to_candles,
    normalize_ohlcv_dataframe,
)
from trade_bot.data.quality_report import (
    generate_data_quality_markdown,
    validation_report_to_dict,
)
from trade_bot.data.storage import ParquetCandleStorage
from trade_bot.data.universe_history import HistoricalUniverseRegistry
from trade_bot.data.validator import CandleDataValidator
from trade_bot.domain.models import Candle


@pytest.fixture
def trading_calendar() -> NSETradingCalendar:
    return NSETradingCalendar()


@pytest.fixture
def validator(trading_calendar: NSETradingCalendar) -> CandleDataValidator:
    return CandleDataValidator(calendar=trading_calendar)


@pytest.fixture
def sample_valid_day_df() -> pd.DataFrame:
    """Creates a full valid 75-bar 5-minute session DataFrame for a normal trading day."""
    cal = NSETradingCalendar()
    # Wednesday, 2024-01-10 is a regular trading day
    t_date = date(2024, 1, 10)
    timestamps = cal.get_expected_bar_timestamps(t_date, timeframe_seconds=300)

    records = []
    base_price = 2500.0
    for i, ts in enumerate(timestamps):
        records.append({
            "timestamp": ts,
            "open": base_price + i * 0.1,
            "high": base_price + i * 0.1 + 1.0,
            "low": base_price + i * 0.1 - 0.5,
            "close": base_price + i * 0.1 + 0.5,
            "volume": 1000 + i * 10,
            "symbol": "RELIANCE",
        })
    return pd.DataFrame(records)


def test_calendar_trading_days_and_holidays(trading_calendar: NSETradingCalendar) -> None:
    # 2024-01-26 is Republic Day (Holiday)
    assert trading_calendar.is_trading_day(date(2024, 1, 26)) is False

    # 2024-01-27 is Saturday
    assert trading_calendar.is_trading_day(date(2024, 1, 27)) is False

    # 2024-01-24 is Wednesday (Trading day)
    assert trading_calendar.is_trading_day(date(2024, 1, 24)) is True

    # Check expected 5m bars for a normal session (09:15 to 15:30 = exactly 75 bars)
    expected_bars = trading_calendar.get_expected_bar_timestamps(date(2024, 1, 24), timeframe_seconds=300)
    assert len(expected_bars) == 75
    assert expected_bars[0].time() == time(9, 15, 0)
    assert expected_bars[-1].time() == time(15, 25, 0)


def test_normalization_column_mapping_and_types() -> None:
    raw_data = {
        "Date": ["2024-01-10 09:15:00", "2024-01-10 09:20:00"],
        "OPEN": [2500.123, 2505.456],
        "High": [2510.0, 2515.0],
        "LOW": [2495.0, 2500.0],
        "Close": [2505.0, 2510.0],
        "Vol": [100.0, 200.0],
    }
    raw_df = pd.DataFrame(raw_data)
    normalized = normalize_ohlcv_dataframe(raw_df, symbol="reliance")

    assert "symbol" in normalized.columns
    assert normalized["symbol"].iloc[0] == "RELIANCE"
    assert normalized["open"].iloc[0] == 2500.12  # Rounded to 2 decimals
    assert normalized["volume"].dtype == "int64"
    assert str(normalized["timestamp"].dt.tz) == "Asia/Kolkata"


def test_validator_detects_clean_dataset(
    validator: CandleDataValidator,
    sample_valid_day_df: pd.DataFrame,
) -> None:
    report = validator.validate_dataframe(sample_valid_day_df, symbol="RELIANCE", timeframe_seconds=300)
    assert report.is_valid is True
    assert report.total_bars == 75
    assert report.valid_bars == 75
    assert report.invalid_ohlc_bars == 0
    assert report.missing_bars == 0
    assert report.completeness_percentage == 100.0


def test_validator_detects_ohlc_and_volume_anomalies(validator: CandleDataValidator) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    bad_records = pd.DataFrame([
        # Bar 1: High < Low
        {"timestamp": ts, "open": 100.0, "high": 90.0, "low": 95.0, "close": 98.0, "volume": 10, "symbol": "TEST"},
        # Bar 2: Low > Open/Close
        {"timestamp": ts + timedelta(minutes=5), "open": 100.0, "high": 110.0, "low": 105.0, "close": 102.0, "volume": 10, "symbol": "TEST"},
        # Bar 3: Negative volume
        {"timestamp": ts + timedelta(minutes=10), "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": -50, "symbol": "TEST"},
        # Bar 4: Out of session (08:30 IST)
        {"timestamp": datetime(2024, 1, 10, 8, 30, tzinfo=IST_TIMEZONE), "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 10, "symbol": "TEST"},
    ])

    report = validator.validate_dataframe(bad_records, symbol="TEST", timeframe_seconds=300)
    assert report.is_valid is False
    assert report.invalid_ohlc_bars >= 2
    assert report.invalid_volume_bars >= 1
    assert report.out_of_session_bars >= 1
    assert len(report.errors) >= 4


def test_validator_missing_candles(
    validator: CandleDataValidator,
    sample_valid_day_df: pd.DataFrame,
) -> None:
    # Drop 5 bars from middle of the day
    partial_df = sample_valid_day_df.drop(index=[10, 11, 12, 13, 14]).reset_index(drop=True)
    report = validator.validate_dataframe(partial_df, symbol="RELIANCE", timeframe_seconds=300)

    assert report.missing_bars == 5
    assert len(report.missing_timestamps) == 5
    assert report.completeness_percentage < 100.0


def test_parquet_candle_storage_roundtrip(tmp_path: Path, sample_valid_day_df: pd.DataFrame) -> None:
    storage = ParquetCandleStorage(base_dir=tmp_path)

    # Store DataFrame
    rows_written = storage.store_candles(sample_valid_day_df, symbol="RELIANCE", timeframe_seconds=300)
    assert rows_written == 75

    # Check symbol is listed
    stored_syms = storage.list_stored_symbols(timeframe_seconds=300)
    assert "RELIANCE" in stored_syms

    # Load back as DataFrame
    loaded_df = storage.load_dataframe("RELIANCE", timeframe_seconds=300)
    assert len(loaded_df) == 75
    assert loaded_df["symbol"].iloc[0] == "RELIANCE"

    # Load back as domain Candle models
    candles = storage.load_candles("RELIANCE", timeframe_seconds=300)
    assert len(candles) == 75
    assert isinstance(candles[0], Candle)
    assert candles[0].symbol == "RELIANCE"


def test_quality_report_markdown_generation(
    validator: CandleDataValidator,
    sample_valid_day_df: pd.DataFrame,
) -> None:
    report = validator.validate_dataframe(sample_valid_day_df, symbol="RELIANCE", timeframe_seconds=300)
    md = generate_data_quality_markdown(report)
    assert "# Data Quality Audit Report: RELIANCE" in md
    assert "✅ PASSED" in md
    assert "Completeness**: 100.00%" in md

    report_dict = validation_report_to_dict(report)
    assert report_dict["is_valid"] is True
    assert report_dict["total_bars"] == 75


def test_historical_universe_registry_survivorship() -> None:
    reg = HistoricalUniverseRegistry()
    test_date = date(2024, 1, 15)

    # RELIANCE is a core constituent
    assert reg.is_fno_eligible_on_date("RELIANCE", test_date) is True

    # Register exclusion of a stock on 2024-01-01
    reg.register_exclusion("DELISTED_CO", date(2024, 1, 1))
    assert reg.is_fno_eligible_on_date("DELISTED_CO", test_date) is False

    # Register addition on 2024-02-01 (future date relative to test_date)
    reg.register_addition("NEW_CO", date(2024, 2, 1))
    # On 2024-01-15, it should not be eligible yet
    assert reg.is_fno_eligible_on_date("NEW_CO", test_date) is False
    # On 2024-02-05, it should be eligible
    assert reg.is_fno_eligible_on_date("NEW_CO", date(2024, 2, 5)) is True
