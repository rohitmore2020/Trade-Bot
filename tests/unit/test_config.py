"""
Unit tests for Configuration loading, validation, and safety guards.
"""

import pytest
from trade_bot.config.settings import AppConfig, ExecutionMode, SystemConfig


def test_default_config_loads_successfully() -> None:
    config = AppConfig()
    assert config.system.mode == ExecutionMode.BACKTEST
    assert config.system.allow_live_trading is False
    assert config.risk.initial_capital > 0
    assert config.risk.max_daily_loss > 0


def test_live_safety_guard_raises_on_disallowed_live_mode() -> None:
    # Attempting LIVE mode without allow_live_trading=True must raise ValueError
    with pytest.raises(ValueError, match="CRITICAL SAFETY VIOLATION"):
        AppConfig(
            system=SystemConfig(
                mode=ExecutionMode.LIVE,
                allow_live_trading=False,
            )
        )


def test_live_safety_guard_permits_when_explicitly_authorized() -> None:
    config = AppConfig(
        system=SystemConfig(
            mode=ExecutionMode.LIVE,
            allow_live_trading=True,
        )
    )
    assert config.system.mode == ExecutionMode.LIVE
    assert config.system.allow_live_trading is True


def test_load_from_yaml_file(tmp_path) -> None:
    yaml_content = """
system:
  environment: "BACKTEST"
  mode: "BACKTEST"
  allow_live_trading: false
risk:
  initial_capital: 250000.0
  max_daily_loss: 7500.0
"""
    cfg_file = tmp_path / "test_config.yaml"
    cfg_file.write_text(yaml_content)

    loaded = AppConfig.load_from_yaml(cfg_file)
    assert loaded.risk.initial_capital == 250000.0
    assert loaded.risk.max_daily_loss == 7500.0
