"""
Multi-Dimensional Performance Breakdown Engine.

Segments completed trades across:
- Stock / Symbol
- Day
- Month
- Market Regime
- Direction (Long vs Short)
- Entry Time Bucket
- Exit Reason
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List

from trade_bot.analytics.models import GroupBreakdown
from trade_bot.domain.enums import OrderSide
from trade_bot.portfolio.models import CompletedTrade


class BreakdownEngine:
    """
    Groups completed trades into multi-dimensional slices and computes attribution metrics.
    """

    @classmethod
    def group_trades(
        cls,
        trades: List[CompletedTrade],
        category: str,
        key_fn: Callable[[CompletedTrade], str],
    ) -> List[GroupBreakdown]:
        """Generic aggregator grouping trades by key function."""
        grouped: Dict[str, List[CompletedTrade]] = defaultdict(list)
        for t in trades:
            key = key_fn(t)
            grouped[key].append(t)

        results: List[GroupBreakdown] = []
        for key in sorted(grouped.keys()):
            group_list = grouped[key]
            n_trades = len(group_list)
            n_wins = sum(1 for t in group_list if t.net_pnl > 0.0)
            n_losses = sum(1 for t in group_list if t.net_pnl < 0.0)
            win_rate = round(n_wins / n_trades, 4) if n_trades > 0 else 0.0

            gross = round(sum(t.gross_pnl for t in group_list), 2)
            costs = round(sum(t.transaction_costs for t in group_list), 2)
            slip = round(sum(t.slippage for t in group_list), 2)
            net = round(sum(t.net_pnl for t in group_list), 2)

            gross_wins = sum(t.gross_pnl for t in group_list if t.gross_pnl > 0.0)
            gross_losses = sum(abs(t.gross_pnl) for t in group_list if t.gross_pnl < 0.0)
            if gross_losses > 0.0:
                pf = round(gross_wins / gross_losses, 4)
            elif gross_wins > 0.0:
                pf = float("inf")
            else:
                pf = 0.0

            results.append(
                GroupBreakdown(
                    category=category,
                    group_key=key,
                    trades_count=n_trades,
                    winning_trades=n_wins,
                    losing_trades=n_losses,
                    win_rate=win_rate,
                    gross_pnl=gross,
                    transaction_costs=costs,
                    slippage=slip,
                    net_pnl=net,
                    profit_factor=pf,
                )
            )

        return results

    @classmethod
    def break_down_by_stock(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        return cls.group_trades(trades, "stock", lambda t: t.symbol)

    @classmethod
    def break_down_by_day(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        return cls.group_trades(trades, "day", lambda t: t.exit_time.strftime("%Y-%m-%d"))

    @classmethod
    def break_down_by_month(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        return cls.group_trades(trades, "month", lambda t: t.exit_time.strftime("%Y-%m"))

    @classmethod
    def break_down_by_regime(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        return cls.group_trades(
            trades,
            "market_regime",
            lambda t: getattr(t, "market_regime", None) or "UNKNOWN",
        )

    @classmethod
    def break_down_by_direction(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        def get_direction(t: CompletedTrade) -> str:
            if t.side == OrderSide.BUY or t.side == "BUY":
                return "LONG"
            return "SHORT"

        return cls.group_trades(trades, "direction", get_direction)

    @classmethod
    def break_down_by_entry_time(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        def get_time_bucket(t: CompletedTrade) -> str:
            hour = t.entry_time.hour
            minute = t.entry_time.minute
            total_mins = hour * 60 + minute

            if total_mins < 600:      # Before 10:00
                return "09:15-10:00"
            elif total_mins < 690:    # 10:00 to 11:30
                return "10:00-11:30"
            elif total_mins < 780:    # 11:30 to 13:00
                return "11:30-13:00"
            elif total_mins < 870:    # 13:00 to 14:30
                return "13:00-14:30"
            else:
                return "14:30+"

        return cls.group_trades(trades, "entry_time", get_time_bucket)

    @classmethod
    def break_down_by_exit_reason(cls, trades: List[CompletedTrade]) -> List[GroupBreakdown]:
        return cls.group_trades(
            trades,
            "exit_reason",
            lambda t: t.exit_reason or "UNSPECIFIED",
        )
