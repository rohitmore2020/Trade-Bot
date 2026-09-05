"""
Command Line Interface (CLI) for Trade-Bot.

Provides commands to validate configurations, run simulations, and inspect system state.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from trade_bot.config.settings import AppConfig, ExecutionMode
from trade_bot.orchestration.factory import TradingEngineFactory
from trade_bot.scanner.universe import DEFAULT_NIFTY50_SYMBOLS


def validate_config_command(args: argparse.Namespace) -> int:
    """Validate system configuration and print summary."""
    config_path = args.config
    print(f"Loading configuration from: {config_path or 'default settings + .env'}")
    try:
        if config_path and Path(config_path).exists():
            config = AppConfig.load_from_yaml(config_path)
        else:
            config = AppConfig()

        print("\n--- Trade-Bot Configuration Summary ---")
        print(f"Environment         : {config.system.environment.value}")
        print(f"Execution Mode      : {config.system.mode.value}")
        print(f"Live Trading Allowed: {config.system.allow_live_trading}")
        print(f"Broker Adapter      : {config.broker.name}")
        print(f"Initial Capital     : Rs {config.risk.initial_capital:,.2f}")
        print(f"Max Daily Loss      : Rs {config.risk.max_daily_loss:,.2f}")
        print(f"Max Loss Per Trade  : Rs {config.risk.max_loss_per_trade:,.2f}")
        print(f"Max Open Positions  : {config.risk.max_open_positions}")
        print(f"Risk Per Trade      : {config.risk.risk_per_trade_percentage * 100:.1f}%")
        print(f"Log Level           : {config.logging.level.value}")
        print("---------------------------------------")
        print("Configuration is VALID.")
        return 0
    except Exception as e:
        print(f"Configuration ERROR: {e}", file=sys.stderr)
        return 1


def run_session(args: argparse.Namespace, mode: ExecutionMode) -> int:
    """Start an engine session in the given mode."""
    config_path = args.config
    if config_path and Path(config_path).exists():
        config = AppConfig.load_from_yaml(config_path)
    else:
        config = AppConfig()

    config.system.mode = mode
    print(f"Initializing Trade-Bot in {mode.value} mode...")

    try:
        engine = TradingEngineFactory.build_engine(config)
        symbols = args.symbols.split(",") if args.symbols else DEFAULT_NIFTY50_SYMBOLS[:3]
        print(f"Starting session for symbols: {symbols}")
        engine.start(symbols)
        print("Session started successfully. Press Ctrl+C to stop.")
        engine.stop()
        print("Session stopped cleanly.")
        return 0
    except Exception as e:
        print(f"Runtime ERROR: {e}", file=sys.stderr)
        return 1


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="trade-bot",
        description="Trade-Bot: Automated Intraday Trading Platform for Indian NSE Equities",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # validate-config
    val_parser = subparsers.add_parser("validate-config", help="Validate configuration settings")
    val_parser.add_argument("--config", "-c", type=str, default="config.example.yaml", help="Path to config YAML")

    # backtest
    bt_parser = subparsers.add_parser("backtest", help="Run backtest session")
    bt_parser.add_argument("--config", "-c", type=str, default="config.example.yaml", help="Path to config YAML")
    bt_parser.add_argument("--symbols", "-s", type=str, default="RELIANCE,TCS,INFY", help="Comma-separated symbols")

    # paper
    paper_parser = subparsers.add_parser("paper", help="Run paper trading session")
    paper_parser.add_argument("--config", "-c", type=str, default="config.example.yaml", help="Path to config YAML")
    paper_parser.add_argument("--symbols", "-s", type=str, default="RELIANCE,TCS,INFY", help="Comma-separated symbols")

    # live
    live_parser = subparsers.add_parser("live", help="Run live trading session (guarded)")
    live_parser.add_argument("--config", "-c", type=str, default="config.example.yaml", help="Path to config YAML")
    live_parser.add_argument("--symbols", "-s", type=str, default="RELIANCE", help="Comma-separated symbols")

    args = parser.parse_args()

    if args.command == "validate-config":
        sys.exit(validate_config_command(args))
    elif args.command == "backtest":
        sys.exit(run_session(args, ExecutionMode.BACKTEST))
    elif args.command == "paper":
        sys.exit(run_session(args, ExecutionMode.PAPER))
    elif args.command == "live":
        print("SAFETY GUARD: Live mode requested. Validating live safety flags...")
        sys.exit(run_session(args, ExecutionMode.LIVE))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
