"""
Market Data handling, aggregation, historical pipeline, and validation module.
"""

from trade_bot.data.aggregator import TimeframeCandleAggregator
from trade_bot.data.calendar import NSE_HOLIDAYS, NSETradingCalendar
from trade_bot.data.downloader import (
    BaseHistoricalDownloader,
    CSVHistoricalDataLoader,
    YahooHistoricalDataLoader,
)
from trade_bot.data.interfaces import (
    ICandleAggregator,
    ICandleStorage,
    IHistoricalDataLoader,
    IHistoricalDataProvider,
    IMarketDataProvider,
)
from trade_bot.data.memory_data_feed import InMemoryMarketDataFeed
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
from trade_bot.data.universe_history import (
    CORE_FNO_EQUITIES,
    HistoricalUniverseRegistry,
)
from trade_bot.data.validator import (
    CandleDataValidator,
    ValidationError,
    ValidationReport,
)

__all__ = [
    # Interfaces
    "ICandleAggregator",
    "ICandleStorage",
    "IHistoricalDataLoader",
    "IHistoricalDataProvider",
    "IMarketDataProvider",
    # Calendar & Session
    "NSETradingCalendar",
    "NSE_HOLIDAYS",
    # Normalization & Storage
    "ParquetCandleStorage",
    "normalize_ohlcv_dataframe",
    "dataframe_to_candles",
    "candles_to_dataframe",
    # Validation & Quality
    "CandleDataValidator",
    "ValidationError",
    "ValidationReport",
    "generate_data_quality_markdown",
    "validation_report_to_dict",
    # Ingestion & Downloaders
    "BaseHistoricalDownloader",
    "CSVHistoricalDataLoader",
    "YahooHistoricalDataLoader",
    "InMemoryMarketDataFeed",
    "TimeframeCandleAggregator",
    # Universe History
    "CORE_FNO_EQUITIES",
    "HistoricalUniverseRegistry",
]
