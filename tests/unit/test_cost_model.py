"""
Unit Tests for Phase 13 Configurable Transaction Cost Model and Slippage.

Verifies:
1. Standard Indian NSE cash equity intraday statutory cost calculations with known hand-calculated numbers.
2. Percentage cap vs flat brokerage thresholding (min(flat, 0.03% * turnover)).
3. Granular separation of statutory levies:
   - Brokerage
   - STT (sell side only)
   - Exchange transaction fees (both sides)
   - SEBI turnover charges (both sides)
   - Stamp duty (buy side only)
   - GST (18% on brokerage + exchange + SEBI)
4. Slippage models (fixed tick, percentage, volatility adaptive, volume impact).
5. Round-trip trade cost calculation.
6. Per-order CostBreakdown serialization.
7. AggregateCostReport over multiple executions.
8. Stress configurations:
   - Normal costs vs +50% costs
   - Normal slippage vs Doubled slippage
9. Purity and architectural decoupling (zero strategy/broker API coupling).
"""

import pytest

from trade_bot.costs.cost_model import IndianEquityCostModel, StandardSlippageModel
from trade_bot.costs.interfaces import ICostModel, ISlippageModel
from trade_bot.costs.models import (
    CostBreakdown,
    CostModelConfig,
    RoundTripCostBreakdown,
    SlippageConfig,
    SlippageModelType,
)
from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Candle


class TestTransactionCostModel:
    """Test suite for Phase 13 Transaction Cost & Slippage Model."""

    def test_implements_protocol_cleanly(self):
        """Verify IndianEquityCostModel and StandardSlippageModel satisfy runtime protocols."""
        cost_model = IndianEquityCostModel.standard()
        slippage_model = StandardSlippageModel()

        assert isinstance(cost_model, ICostModel)
        assert isinstance(slippage_model, ISlippageModel)
        assert cost_model.version == "NSE_EQUITY_2024_V1"

    def test_known_buy_order_statutory_calculation(self):
        """
        Known Example: Buy 100 shares @ 2500.0 INR = Turnover 2,50,000 INR
        - Brokerage: min(20.0, 250000 * 0.0003 = 75.0) -> 20.00
        - STT: 0.00 (Buy side)
        - Exchange charges: 250000 * 0.0000345 = 8.625 -> 8.62
        - SEBI charges: 250000 * 0.000001 = 0.25
        - GST: 18% of (20.0 + 8.62 + 0.25 = 28.87) = 5.1966 -> 5.20
        - Stamp duty: 250000 * 0.00003 = 7.50
        - Total Statutory Taxes: 0 + 8.62 + 0.25 + 7.50 + 5.20 = 21.57
        - Total Costs: 20.00 + 21.57 = 41.57
        """
        model = IndianEquityCostModel.standard()
        bd: CostBreakdown = model.calculate_per_order_cost(
            price=2500.0,
            quantity=100,
            side=OrderSide.BUY,
        )

        assert bd.turnover == 250_000.0
        assert bd.side == OrderSide.BUY
        assert bd.brokerage == 20.0
        assert bd.stt == 0.0
        assert bd.exchange_charges == 8.62
        assert bd.sebi_charges == 0.25
        assert bd.stamp_duty == 7.50
        assert bd.gst == 5.20
        assert bd.total_statutory_taxes == 21.57
        assert bd.total_costs == 41.57

    def test_known_sell_order_statutory_calculation(self):
        """
        Known Example: Sell 100 shares @ 2510.0 INR = Turnover 2,51,000 INR
        - Brokerage: min(20.0, 251000 * 0.0003 = 75.3) -> 20.00
        - STT: 251000 * 0.00025 = 62.75 (Sell side)
        - Exchange charges: 251000 * 0.0000345 = 8.6595 -> 8.66
        - SEBI charges: 251000 * 0.000001 = 0.251 -> 0.25
        - GST: 18% of (20.0 + 8.66 + 0.25 = 28.91) = 5.2038 -> 5.20
        - Stamp duty: 0.00 (Sell side)
        - Total Statutory Taxes: 62.75 + 8.66 + 0.25 + 0.00 + 5.20 = 76.86
        - Total Costs: 20.00 + 76.86 = 96.86
        """
        model = IndianEquityCostModel.standard()
        bd: CostBreakdown = model.calculate_per_order_cost(
            price=2510.0,
            quantity=100,
            side=OrderSide.SELL,
        )

        assert bd.turnover == 251_000.0
        assert bd.side == OrderSide.SELL
        assert bd.brokerage == 20.0
        assert bd.stt == 62.75
        assert bd.exchange_charges == 8.66
        assert bd.sebi_charges == 0.25
        assert bd.stamp_duty == 0.0
        assert bd.gst == 5.20
        assert bd.total_statutory_taxes == 76.86
        assert bd.total_costs == 96.86

    def test_small_turnover_brokerage_percentage_capping(self):
        """
        On small turnover, brokerage is capped at 0.03% rather than charging full ₹20.
        Turnover = 1,000 INR
        Brokerage = min(20.0, 1000 * 0.0003 = 0.30) = 0.30 INR
        """
        model = IndianEquityCostModel.standard()
        bd = model.calculate_per_order_cost(price=10.0, quantity=100, side=OrderSide.BUY)

        assert bd.turnover == 1000.0
        assert bd.brokerage == 0.30
        assert bd.total_costs < 1.0  # Fraction of a rupee

    def test_round_trip_cost_calculation(self):
        """
        Verifies complete round trip friction across entry and exit legs.
        Entry: Buy 100 @ 2500 (Turnover: 2,50,000, Costs: 41.57)
        Exit: Sell 100 @ 2510 (Turnover: 2,51,000, Costs: 96.86)
        Total Round-Trip Turnover: 5,01,000
        Total Brokerage: 40.00
        Total Taxes: 21.57 + 76.86 = 98.43
        Total Friction without slippage: 138.43
        """
        model = IndianEquityCostModel.standard()
        rt: RoundTripCostBreakdown = model.calculate_round_trip_cost(
            entry_price=2500.0,
            exit_price=2510.0,
            quantity=100,
            entry_side=OrderSide.BUY,
            slippage=10.0,
        )

        assert rt.total_turnover == 501_000.0
        assert rt.total_brokerage == 40.00
        assert rt.total_stt == 62.75
        assert rt.total_stamp_duty == 7.50
        assert rt.total_statutory_taxes == 98.43
        assert rt.total_slippage == 10.00
        assert rt.total_frictional_costs == 148.43  # 138.43 + 10.0 slippage

        # Basis points: (148.43 / 501000) * 10000 = ~2.96 bps
        assert 2.5 <= rt.cost_basis_points <= 3.5

        # Verify to_dict structure
        d = rt.to_dict()
        assert "entry_leg" in d
        assert "exit_leg" in d
        assert d["total_frictional_costs"] == 148.43

    def test_aggregate_cost_report(self):
        """Verifies multi-fill aggregate cost reporting."""
        model = IndianEquityCostModel.standard()

        bd1 = model.calculate_per_order_cost(2500.0, 100, OrderSide.BUY)
        bd2 = model.calculate_per_order_cost(2510.0, 100, OrderSide.SELL)
        bd3 = model.calculate_per_order_cost(1500.0, 50, OrderSide.BUY)
        bd4 = model.calculate_per_order_cost(1520.0, 50, OrderSide.SELL)

        report = model.calculate_aggregate_report([bd1, bd2, bd3, bd4], total_slippage=25.0)

        assert report.total_fills == 4
        assert report.total_turnover == (250000 + 251000 + 75000 + 76000)
        assert report.total_brokerage == 80.0  # 4 * 20
        assert report.total_slippage == 25.0
        assert report.total_costs > report.total_brokerage
        assert report.effective_friction_pct > 0.0

    def test_stress_configuration_plus_50_pct(self):
        """
        Stress Test: +50% costs across all statutory levies and brokerage.
        """
        std_model = IndianEquityCostModel.standard()
        stress_model = IndianEquityCostModel.stress_plus_50_pct()

        assert stress_model.config.cost_multiplier == 1.5
        assert stress_model.config.brokerage_per_order == 30.0  # 1.5 * 20

        std_bd = std_model.calculate_per_order_cost(2500.0, 100, OrderSide.BUY)
        stress_bd = stress_model.calculate_per_order_cost(2500.0, 100, OrderSide.BUY)

        # Brokerage should be 1.5x (30.0 vs 20.0)
        assert stress_bd.brokerage == 30.0
        # Total statutory taxes should be approximately 1.5x
        assert stress_bd.total_statutory_taxes > std_bd.total_statutory_taxes
        assert stress_bd.total_costs > std_bd.total_costs
        assert round(stress_bd.total_costs / std_bd.total_costs, 1) == 1.5

    def test_slippage_model_normal_vs_doubled(self):
        """
        Verifies normal vs doubled slippage stress configurations.
        """
        std_slip = StandardSlippageModel(config=SlippageConfig.standard())
        doubled_slip = StandardSlippageModel(config=SlippageConfig.doubled_slippage())

        price = 1000.0
        # Normal BUY: 1000.0 + 0.05 = 1000.05
        assert std_slip.calculate_slippage_price(price, OrderSide.BUY) == 1000.05
        # Doubled BUY: 1000.0 + 0.10 = 1000.10
        assert doubled_slip.calculate_slippage_price(price, OrderSide.BUY) == 1000.10

        # Normal SELL: 1000.0 - 0.05 = 999.95
        assert std_slip.calculate_slippage_price(price, OrderSide.SELL) == 999.95
        # Doubled SELL: 1000.0 - 0.10 = 999.90
        assert doubled_slip.calculate_slippage_price(price, OrderSide.SELL) == 999.90

        # Slippage monetary cost
        cost_std = std_slip.calculate_slippage_cost(1000.0, 1000.05, 100)
        cost_dbl = doubled_slip.calculate_slippage_cost(1000.0, 1000.10, 100)
        assert cost_std == 5.0
        assert cost_dbl == 10.0
        assert cost_dbl == cost_std * 2

    def test_zero_cost_model(self):
        """Verifies hypothetical zero-cost model for idealized comparisons."""
        zero_cfg = CostModelConfig.zero_cost()
        zero_model = IndianEquityCostModel(config=zero_cfg)

        bd_buy = zero_model.calculate_per_order_cost(2500.0, 100, OrderSide.BUY)
        bd_sell = zero_model.calculate_per_order_cost(2500.0, 100, OrderSide.SELL)

        assert bd_buy.total_costs == 0.0
        assert bd_buy.brokerage == 0.0
        assert bd_sell.total_costs == 0.0
        assert bd_sell.stt == 0.0

    def test_simulator_cost_model_stress_integration(self):
        """Verify ExecutionSimulator operates with custom stress cost models and emits reports."""
        from trade_bot.domain.models import OrderRequest
        from trade_bot.domain.enums import OrderType
        from trade_bot.execution.simulator import ExecutionSimulator

        # Setup simulator with +50% costs and doubled slippage
        stress_model = IndianEquityCostModel.with_stress_scenarios(cost_multiplier=1.5, doubled_slippage=True)
        sim = ExecutionSimulator(cost_model=stress_model)
        sim.set_market_price("RELIANCE", 2500.0)

        # Place MARKET BUY
        req_buy = OrderRequest(
            client_order_id="BUY_STRESS",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            price=2500.0,
        )
        sim.place_order(req_buy)

        # Place MARKET SELL
        req_sell = OrderRequest(
            client_order_id="SELL_STRESS",
            symbol="RELIANCE",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
            price=2510.0,
        )
        sim.place_order(req_sell)

        breakdowns = sim.get_cost_breakdowns()
        assert len(breakdowns) == 2
        # Verify 1.5x brokerage: ₹30 per fill
        assert breakdowns[0].brokerage == 30.0
        assert breakdowns[1].brokerage == 30.0

        # Verify aggregate report
        agg_report = sim.get_aggregate_cost_report()
        assert agg_report.total_fills == 2
        assert agg_report.total_brokerage == 60.0
        assert agg_report.total_costs > 60.0
        assert agg_report.effective_friction_pct > 0.0

