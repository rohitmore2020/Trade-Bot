"""
Portfolio Manager Implementation.

Maintains ledger of cash balance, open positions, realized and unrealized P&L,
order lifecycles, and intraday risk/session states.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Union

from trade_bot.domain.enums import OrderSide, OrderStatus, TradingSessionStatus
from trade_bot.domain.models import AccountBalance, Order, Position, Trade, utc_now
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.portfolio.models import (
    DailyRiskState,
    Fill,
    PortfolioSnapshot,
    TradingSession,
)
from trade_bot.portfolio.order_tracker import OrderLifecycleTracker
from trade_bot.portfolio.pnl import PnLCalculator
from trade_bot.portfolio.position_ledger import PositionLedger


class PortfolioManager(IPortfolioManager):
    """
    Coordinates portfolio accounting, position ledger, order tracking, and session state.
    Enforces strict idempotency and zero double-counting on fills and order events.
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        currency: str = "INR",
        max_daily_loss_pct: float = 0.02,
        max_trades_limit: int = 6,
        max_positions_limit: int = 3,
        max_sector_exposure_pct: float = 0.40,
    ) -> None:
        self.initial_capital = float(initial_capital)
        self.available_cash = float(initial_capital)
        self.currency = currency

        self._ledger = PositionLedger()
        self._order_tracker = OrderLifecycleTracker()

        today = utc_now().date()
        self._session = TradingSession(
            session_id=f"SESSION_{today.isoformat()}",
            trading_date=today,
            status=TradingSessionStatus.OPEN,
            start_time=utc_now(),
        )
        self._daily_risk = DailyRiskState(
            daily_loss_limit=round(self.initial_capital * max_daily_loss_pct, 2),
            max_trades_limit=max_trades_limit,
            max_positions_limit=max_positions_limit,
            max_sector_exposure_pct=max_sector_exposure_pct,
        )

    @property
    def current_session(self) -> TradingSession:
        return self._session

    @property
    def daily_risk_state(self) -> DailyRiskState:
        return self._daily_risk

    @property
    def completed_trades(self) -> list:
        return self._ledger.completed_trades

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a given symbol."""
        pos = self._ledger.get_position(symbol)
        return pos if not pos.is_flat or pos.realized_pnl != 0.0 else None

    def get_all_positions(self) -> Dict[str, Position]:
        """Return snapshot of all positions."""
        return self._ledger.positions

    def get_open_positions(self) -> List[Position]:
        """Return list of all non-flat positions."""
        return self._ledger.open_positions

    def register_order(self, order: Order) -> Order:
        """Register an order with the portfolio tracker."""
        return self._order_tracker.register_order(order)

    def transition_order(
        self,
        client_order_id: str,
        to_status: OrderStatus,
        reason: Optional[str] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> Order:
        """Transition order status with strict lifecycle checks and idempotency."""
        return self._order_tracker.transition_order(
            client_order_id=client_order_id,
            to_status=to_status,
            reason=reason,
            event_id=event_id,
            timestamp=timestamp,
        )

    def process_fill(self, fill: Union[Fill, Trade]) -> Position:
        """
        Processes an execution fill into the position ledger and cash accounting.
        Safe against duplicate fill events (idempotent).
        """
        # Convert domain Trade to Fill if necessary
        fill_model: Fill
        if isinstance(fill, Trade):
            fill_model = Fill(
                fill_id=fill.trade_id,
                order_id=fill.order_id,
                client_order_id=fill.client_order_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                timestamp=fill.timestamp,
                brokerage=fill.brokerage,
                stt_and_taxes=fill.stt_and_taxes,
                exchange=fill.exchange,
            )
        else:
            fill_model = fill

        # Apply to position ledger
        pos, completed_trade, is_new_fill = self._ledger.apply_fill(fill_model)

        # Update cash and risk state ONLY if this is a newly applied fill
        if is_new_fill:
            tx_costs = (
                fill_model.brokerage + fill_model.stt_and_taxes
                if (fill_model.brokerage > 0.0 or fill_model.stt_and_taxes > 0.0)
                else PnLCalculator.calculate_transaction_costs(
                    fill_model.price, fill_model.quantity, fill_model.side
                )
            )
            gross_value = fill_model.price * fill_model.quantity

            if fill_model.side == OrderSide.BUY:
                self.available_cash = round(self.available_cash - (gross_value + tx_costs), 2)
            else:
                self.available_cash = round(self.available_cash + (gross_value - tx_costs), 2)

            # Update order tracking if registered
            if self._order_tracker.get_order(fill_model.client_order_id):
                self._order_tracker.record_fill_on_order(fill_model, event_id=f"EVT_{fill_model.fill_id}")

            # Update daily risk metrics
            if completed_trade:
                self._daily_risk.trades_executed_today += 1

            self._daily_risk.current_open_positions = len(self.get_open_positions())
            total_loss = -(self.get_account_balance().total_realized_pnl + self.get_account_balance().total_unrealized_pnl)
            self._daily_risk.current_daily_loss = max(0.0, total_loss)
            if total_loss >= self._daily_risk.daily_loss_limit:
                self._daily_risk.max_daily_loss_breached = True

        return pos

    def update_market_price(self, symbol: str, current_price: float) -> None:
        """Update unrealized P&L on the active position."""
        self._ledger.update_market_price(symbol, current_price)

    def get_account_balance(self) -> AccountBalance:
        """Compute current account balance and total equity."""
        pnl_breakdown = self._ledger.get_pnl_breakdown()
        used_margin = sum(p.market_value for p in self.get_open_positions())

        return AccountBalance(
            initial_capital=self.initial_capital,
            available_cash=round(self.available_cash, 2),
            used_margin=round(used_margin, 2),
            total_realized_pnl=pnl_breakdown.net_realized,
            total_unrealized_pnl=pnl_breakdown.unrealized,
            currency=self.currency,
            timestamp=utc_now(),
        )

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Generates an immutable snapshot of complete portfolio state."""
        balance = self.get_account_balance()
        pnl = self._ledger.get_pnl_breakdown()
        open_positions = {p.symbol: p for p in self.get_open_positions()}
        total_exposure = sum(p.market_value for p in open_positions.values())

        return PortfolioSnapshot(
            timestamp=utc_now(),
            session_id=self._session.session_id,
            initial_capital=self.initial_capital,
            available_cash=balance.available_cash,
            used_margin=balance.used_margin,
            total_equity=balance.total_equity,
            pnl=pnl,
            total_exposure=round(total_exposure, 2),
            open_positions_count=len(open_positions),
            open_positions=open_positions,
            daily_trade_count=self._daily_risk.trades_executed_today,
            daily_order_count=self._order_tracker.daily_order_count,
        )

    def reset_daily_session(
        self,
        trading_date: Optional[date] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Resets portfolio state at intraday session open (09:15 IST boundary).
        Preserves rolling equity and cash while clearing intraday counters.
        """
        t_date = trading_date or utc_now().date()
        s_id = session_id or f"SESSION_{t_date.isoformat()}"

        # Close previous session if active
        if self._session.is_active:
            self._session.close()

        self._session = TradingSession(
            session_id=s_id,
            trading_date=t_date,
            status=TradingSessionStatus.OPEN,
            start_time=utc_now(),
        )

        # Reset components
        self._ledger.reset_daily_session()
        self._order_tracker.reset_daily_session()

        # Update initial capital to current equity for the new trading day
        current_equity = self.get_account_balance().total_equity
        self.initial_capital = current_equity

        self._daily_risk.trades_executed_today = 0
        self._daily_risk.current_daily_loss = 0.0
        self._daily_risk.max_daily_loss_breached = False
        self._daily_risk.current_open_positions = len(self.get_open_positions())
        self._daily_risk.daily_loss_limit = round(self.initial_capital * 0.02, 2)
