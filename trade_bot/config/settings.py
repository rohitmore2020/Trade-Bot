"""
Typed Application and System Settings.

Uses Pydantic Settings for strictly validated, typed configurations.
Supports loading defaults, YAML configuration files, and environment variable overrides.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvironmentType(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"


class ExecutionMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(str, Enum):
    JSON = "JSON"
    CONSOLE = "CONSOLE"


class LoggingConfig(BaseModel):
    level: LogLevel = LogLevel.INFO
    format: LogFormat = LogFormat.JSON
    log_dir: str = "logs"
    audit_dir: str = "audit"
    enable_console: bool = True
    enable_file: bool = True


class MarketConfig(BaseModel):
    exchange: str = "NSE"
    segment: str = "EQ"
    market_open_time: str = "09:15:00"
    market_close_time: str = "15:30:00"
    intraday_square_off_time: str = "15:15:00"
    no_new_orders_after_time: str = "15:00:00"
    orb_opening_duration_minutes: int = Field(default=15, ge=1, le=60)


class SlippageConfig(BaseModel):
    type: str = "fixed_percentage"
    percentage: float = Field(default=0.0005, ge=0.0, le=0.05)


class CommissionConfig(BaseModel):
    brokerage_per_order: float = Field(default=20.0, ge=0.0)
    stt_percentage: float = Field(default=0.00025, ge=0.0)
    transaction_charges_percentage: float = Field(default=0.0000345, ge=0.0)
    gst_percentage: float = Field(default=0.18, ge=0.0)
    sebi_charges_percentage: float = Field(default=0.000001, ge=0.0)
    stamp_duty_percentage: float = Field(default=0.00003, ge=0.0)


class BrokerConfig(BaseModel):
    name: str = "BACKTEST"
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    access_token: Optional[str] = None
    slippage_model: SlippageConfig = Field(default_factory=SlippageConfig)
    commission_model: CommissionConfig = Field(default_factory=CommissionConfig)


class RiskConfig(BaseModel):
    initial_capital: float = Field(default=100000.0, gt=0.0)
    max_daily_loss: float = Field(default=5000.0, gt=0.0)
    max_loss_per_trade: float = Field(default=1500.0, gt=0.0)
    max_position_size_per_trade: float = Field(default=100000.0, gt=0.0)
    max_open_positions: int = Field(default=3, ge=1, le=20)
    max_daily_trades: int = Field(default=10, ge=1, le=100)
    risk_per_trade_percentage: float = Field(default=0.01, gt=0.0, le=0.10)
    enforce_stop_loss: bool = True
    circuit_breaker_enabled: bool = True


class ScannerConfig(BaseModel):
    universe_name: str = "NIFTY50"
    min_average_volume_30d: int = Field(default=500000, ge=0)
    min_turnover_cr: float = Field(default=10.0, ge=0.0)
    max_spread_percentage: float = Field(default=0.001, ge=0.0)


class SystemConfig(BaseModel):
    environment: EnvironmentType = EnvironmentType.BACKTEST
    mode: ExecutionMode = ExecutionMode.BACKTEST
    allow_live_trading: bool = False
    time_zone: str = "Asia/Kolkata"


class AppConfig(BaseSettings):
    """
    Root application configuration model with environment variable overrides.
    """
    model_config = SettingsConfigDict(
        env_prefix="TRADE_BOT_",
        env_nested_delimiter="__",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    system: SystemConfig = Field(default_factory=SystemConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Top-level environment bindings for convenience
    env: Optional[str] = None
    execution_mode: Optional[str] = None
    allow_live: Optional[bool] = None

    @field_validator("system")
    @classmethod
    def validate_safety_guards(cls, v: SystemConfig) -> SystemConfig:
        if v.mode == ExecutionMode.LIVE and not v.allow_live_trading:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: ExecutionMode is set to LIVE but allow_live_trading is False. "
                "You must explicitly enable allow_live_trading in configuration to run in LIVE mode."
            )
        return v

    @classmethod
    def load_from_yaml(cls, yaml_path: str | Path) -> "AppConfig":
        """Load configuration from a YAML file with environment variable overlays."""
        path = Path(yaml_path)
        data: Dict[str, Any] = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data = loaded

        # Overlay environment variables if present
        if os.getenv("TRADE_BOT_EXECUTION_MODE"):
            data.setdefault("system", {})["mode"] = os.getenv("TRADE_BOT_EXECUTION_MODE")
        if os.getenv("TRADE_BOT_ALLOW_LIVE"):
            data.setdefault("system", {})["allow_live_trading"] = (
                os.getenv("TRADE_BOT_ALLOW_LIVE", "").lower() in ("true", "1", "yes")
            )
        if os.getenv("UPSTOX_API_KEY"):
            data.setdefault("broker", {})["api_key"] = os.getenv("UPSTOX_API_KEY")
        if os.getenv("UPSTOX_API_SECRET"):
            data.setdefault("broker", {})["api_secret"] = os.getenv("UPSTOX_API_SECRET")
        if os.getenv("UPSTOX_ACCESS_TOKEN"):
            data.setdefault("broker", {})["access_token"] = os.getenv("UPSTOX_ACCESS_TOKEN")

        return cls(**data)
