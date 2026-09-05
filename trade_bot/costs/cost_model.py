"""
Configurable Indian Equity Transaction Cost Model and Slippage Implementation.

Provides exact statutory calculations for Indian NSE cash equity intraday trading:
- Brokerage: min(flat_fee, pct_cap * turnover)
- STT: 0.025% on sell side turnover
- Exchange transaction charges: 0.00345%
- SEBI charges: ₹10 per crore (0.0001%)
- GST: 18% on (Brokerage + Exchange charges + SEBI charges)
- Stamp Duty: 0.003% on buy side turnover
- Slippage: Fixed tick, percentage, volatility-adaptive, or volume-impact
"""

from __future__ import annotations

from typing import List, Optional

from trade_bot.costs.interfaces import ICostModel, ISlippageModel
from trade_bot.costs.models import (
    AggregateCostReport,
    CostBreakdown,
    CostModelConfig,
    RoundTripCostBreakdown,
    SlippageConfig,
    SlippageModelType,
)
from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Candle


class StandardSlippageModel(ISlippageModel):
    """
    Computes adverse execution slippage based on configuration.
    """

    def __init__(self, config: Optional[SlippageConfig] = None) -> None:
        self._config = config or SlippageConfig.standard()

    @property
    def config(self) -> SlippageConfig:
        return self._config

    def calculate_slippage_price(
        self,
        price: float,
        side: OrderSide,
        candle: Optional[Candle] = None,
    ) -> float:
        """
        Calculates adverse fill price for BUY or SELL orders.
        Slippage is strictly adverse (added for BUY, subtracted for SELL).
        """
        slip_amt = self._calculate_per_share_slippage(price, candle)
        if side == OrderSide.BUY:
            return round(price + slip_amt, 2)
        else:
            return round(max(0.05, price - slip_amt), 2)

    def calculate_slippage_cost(
        self,
        expected_price: Optional[float],
        actual_price: float,
        quantity: int,
    ) -> float:
        """Monetary slippage: |actual - expected| * quantity."""
        if expected_price is None or expected_price <= 0.0:
            return 0.0
        return round(abs(actual_price - expected_price) * quantity, 2)

    def _calculate_per_share_slippage(self, price: float, candle: Optional[Candle] = None) -> float:
        cfg = self._config
        base_slip: float
        if cfg.model_type == SlippageModelType.FIXED_TICK:
            base_slip = cfg.fixed_tick_size
        elif cfg.model_type == SlippageModelType.PERCENTAGE:
            base_slip = price * cfg.percentage
        elif cfg.model_type == SlippageModelType.VOLATILITY_ADAPTIVE:
            ref_range = candle.range if candle else (price * 0.01)
            base_slip = ref_range * cfg.volatility_mult
        elif cfg.model_type == SlippageModelType.VOLUME_IMPACT:
            base_slip = max(cfg.fixed_tick_size, price * cfg.percentage)
        else:
            base_slip = cfg.fixed_tick_size

        return round(base_slip * cfg.multiplier, 4)


class IndianEquityCostModel(ICostModel):
    """
    Standard Indian NSE cash equity intraday transaction cost model.
    Fully configurable, versioned, and decoupled from broker and strategy logic.
    """

    def __init__(
        self,
        config: Optional[CostModelConfig] = None,
        slippage_model: Optional[ISlippageModel] = None,
    ) -> None:
        self._config = config or CostModelConfig.standard()
        self._slippage_model = slippage_model or StandardSlippageModel()

    @property
    def version(self) -> str:
        return self._config.version

    @property
    def config(self) -> CostModelConfig:
        return self._config

    @property
    def slippage_model(self) -> ISlippageModel:
        return self._slippage_model

    @classmethod
    def standard(cls) -> IndianEquityCostModel:
        """Standard baseline Indian equity cost model."""
        return cls(config=CostModelConfig.standard(), slippage_model=StandardSlippageModel())

    @classmethod
    def stress_plus_50_pct(cls) -> IndianEquityCostModel:
        """Stress configuration with +50% costs across all statutory levies and brokerage."""
        return cls(
            config=CostModelConfig.stress_plus_50_pct(),
            slippage_model=StandardSlippageModel(),
        )

    @classmethod
    def with_stress_scenarios(
        cls,
        cost_multiplier: float = 1.0,
        doubled_slippage: bool = False,
    ) -> IndianEquityCostModel:
        """Factory creating stress scenario configurations."""
        cost_cfg = CostModelConfig.with_multiplier(cost_multiplier)
        slip_cfg = SlippageConfig.doubled_slippage() if doubled_slippage else SlippageConfig.standard()
        return cls(config=cost_cfg, slippage_model=StandardSlippageModel(config=slip_cfg))

    def calculate_per_order_cost(
        self,
        price: float,
        quantity: int,
        side: OrderSide,
    ) -> CostBreakdown:
        """
        Computes granular, statutory fee breakdown for a single order fill.
        """
        turnover = round(price * quantity, 2)
        if turnover <= 0.0 or quantity <= 0:
            return CostBreakdown(
                turnover=0.0,
                side=side,
                brokerage=0.0,
                stt=0.0,
                exchange_charges=0.0,
                sebi_charges=0.0,
                stamp_duty=0.0,
                gst=0.0,
                total_statutory_taxes=0.0,
                total_costs=0.0,
            )

        # 1. Brokerage: min(flat_fee, pct_cap * turnover)
        raw_brokerage = min(
            self._config.brokerage_per_order,
            turnover * self._config.brokerage_pct_cap,
        )
        brokerage = round(raw_brokerage, 2)

        # 2. STT: 0.025% on sell side only for equity intraday
        stt = round(turnover * self._config.stt_sell_pct, 2) if side == OrderSide.SELL else 0.0

        # 3. Exchange transaction charges (NSE)
        exchange_charges = round(turnover * self._config.exchange_turnover_pct, 2)

        # 4. SEBI turnover charges (₹10/crore = 0.0001%)
        sebi_charges = round(turnover * self._config.sebi_turnover_pct, 2)

        # 5. GST: 18% on (Brokerage + Exchange charges + SEBI charges)
        taxable_base = brokerage + exchange_charges + sebi_charges
        gst = round(taxable_base * self._config.gst_pct, 2)

        # 6. Stamp duty: 0.003% on buy side only
        stamp_duty = round(turnover * self._config.stamp_duty_buy_pct, 2) if side == OrderSide.BUY else 0.0

        total_taxes = round(stt + exchange_charges + sebi_charges + stamp_duty + gst, 2)
        total_costs = round(brokerage + total_taxes, 2)

        return CostBreakdown(
            turnover=turnover,
            side=side,
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange_charges,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            gst=gst,
            total_statutory_taxes=total_taxes,
            total_costs=total_costs,
        )

    def calculate_round_trip_cost(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int,
        entry_side: OrderSide = OrderSide.BUY,
        slippage: float = 0.0,
    ) -> RoundTripCostBreakdown:
        """
        Computes full round-trip friction across entry and exit legs.
        """
        exit_side = OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY

        entry_breakdown = self.calculate_per_order_cost(entry_price, quantity, entry_side)
        exit_breakdown = self.calculate_per_order_cost(exit_price, quantity, exit_side)

        total_turnover = round(entry_breakdown.turnover + exit_breakdown.turnover, 2)
        total_brokerage = round(entry_breakdown.brokerage + exit_breakdown.brokerage, 2)
        total_stt = round(entry_breakdown.stt + exit_breakdown.stt, 2)
        total_exchange = round(entry_breakdown.exchange_charges + exit_breakdown.exchange_charges, 2)
        total_sebi = round(entry_breakdown.sebi_charges + exit_breakdown.sebi_charges, 2)
        total_stamp = round(entry_breakdown.stamp_duty + exit_breakdown.stamp_duty, 2)
        total_gst = round(entry_breakdown.gst + exit_breakdown.gst, 2)
        total_taxes = round(entry_breakdown.total_statutory_taxes + exit_breakdown.total_statutory_taxes, 2)
        total_friction = round(total_brokerage + total_taxes + slippage, 2)

        cost_bps = round((total_friction / total_turnover) * 10000.0, 2) if total_turnover > 0 else 0.0

        return RoundTripCostBreakdown(
            entry_cost=entry_breakdown,
            exit_cost=exit_breakdown,
            total_turnover=total_turnover,
            total_brokerage=total_brokerage,
            total_stt=total_stt,
            total_exchange_charges=total_exchange,
            total_sebi_charges=total_sebi,
            total_stamp_duty=total_stamp,
            total_gst=total_gst,
            total_statutory_taxes=total_taxes,
            total_slippage=round(slippage, 2),
            total_frictional_costs=total_friction,
            cost_basis_points=cost_bps,
        )

    def calculate_aggregate_report(
        self,
        breakdowns: List[CostBreakdown],
        total_slippage: float = 0.0,
    ) -> AggregateCostReport:
        """
        Aggregates multiple individual order cost breakdowns into a comprehensive summary.
        """
        total_fills = len(breakdowns)
        if total_fills == 0:
            return AggregateCostReport(
                total_fills=0,
                total_turnover=0.0,
                total_brokerage=0.0,
                total_stt=0.0,
                total_exchange_charges=0.0,
                total_sebi_charges=0.0,
                total_stamp_duty=0.0,
                total_gst=0.0,
                total_statutory_taxes=0.0,
                total_slippage=0.0,
                total_costs=0.0,
                effective_friction_pct=0.0,
            )

        total_turnover = round(sum(b.turnover for b in breakdowns), 2)
        total_brokerage = round(sum(b.brokerage for b in breakdowns), 2)
        total_stt = round(sum(b.stt for b in breakdowns), 2)
        total_exchange = round(sum(b.exchange_charges for b in breakdowns), 2)
        total_sebi = round(sum(b.sebi_charges for b in breakdowns), 2)
        total_stamp = round(sum(b.stamp_duty for b in breakdowns), 2)
        total_gst = round(sum(b.gst for b in breakdowns), 2)
        total_taxes = round(sum(b.total_statutory_taxes for b in breakdowns), 2)
        total_costs = round(total_brokerage + total_taxes + total_slippage, 2)
        friction_pct = round((total_costs / total_turnover) * 100.0, 4) if total_turnover > 0 else 0.0

        return AggregateCostReport(
            total_fills=total_fills,
            total_turnover=total_turnover,
            total_brokerage=total_brokerage,
            total_stt=total_stt,
            total_exchange_charges=total_exchange,
            total_sebi_charges=total_sebi,
            total_stamp_duty=total_stamp,
            total_gst=total_gst,
            total_statutory_taxes=total_taxes,
            total_slippage=round(total_slippage, 2),
            total_costs=total_costs,
            effective_friction_pct=friction_pct,
        )
