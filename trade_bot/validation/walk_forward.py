"""
Walk-Forward Validation Engine.

Divides historical data into sequential rolling In-Sample (IS) and Out-Of-Sample (OOS)
windows to evaluate forward-testing persistence and calculate Walk-Forward Efficiency (WFE).
"""

from __future__ import annotations

from typing import Any, Callable, List

from trade_bot.portfolio.models import CompletedTrade
from trade_bot.validation.models import WalkForwardAnalysisResult, WalkForwardFoldResult


class WalkForwardValidator:
    """
    Evaluates strategy parameter stability across rolling train/test partitions.
    """

    @classmethod
    def evaluate_folds(
        cls,
        folds_data: List[dict[str, Any]],
    ) -> WalkForwardAnalysisResult:
        """
        Processes executed fold data and computes Walk-Forward Efficiency (WFE).
        Each entry in folds_data contains:
        - fold_index: int
        - is_period: str
        - oos_period: str
        - is_trades: List[CompletedTrade]
        - oos_trades: List[CompletedTrade]
        """
        if not folds_data:
            return WalkForwardAnalysisResult(
                folds=[],
                mean_wfe=0.0,
                median_wfe=0.0,
                profitable_oos_folds_ratio=0.0,
                consistency_score=0.0,
            )

        fold_results: List[WalkForwardFoldResult] = []

        for fold in folds_data:
            is_trades: List[CompletedTrade] = fold.get("is_trades", [])
            oos_trades: List[CompletedTrade] = fold.get("oos_trades", [])

            is_pnl = round(sum(t.net_pnl for t in is_trades), 2)
            oos_pnl = round(sum(t.net_pnl for t in oos_trades), 2)

            is_gross_win = sum(t.gross_pnl for t in is_trades if t.gross_pnl > 0.0)
            is_gross_loss = sum(abs(t.gross_pnl) for t in is_trades if t.gross_pnl < 0.0)
            is_pf = round(is_gross_win / is_gross_loss, 4) if is_gross_loss > 0 else (float("inf") if is_gross_win > 0 else 0.0)

            oos_gross_win = sum(t.gross_pnl for t in oos_trades if t.gross_pnl > 0.0)
            oos_gross_loss = sum(abs(t.gross_pnl) for t in oos_trades if t.gross_pnl < 0.0)
            oos_pf = round(oos_gross_win / oos_gross_loss, 4) if oos_gross_loss > 0 else (float("inf") if oos_gross_win > 0 else 0.0)

            # WFE calculation: OOS return / IS return normalized
            wfe = round((oos_pnl / is_pnl), 4) if is_pnl > 0.0 else (1.0 if (is_pnl <= 0 and oos_pnl >= 0) else 0.0)

            fold_results.append(
                WalkForwardFoldResult(
                    fold_index=fold.get("fold_index", 1),
                    in_sample_period=fold.get("is_period", "IS"),
                    out_of_sample_period=fold.get("oos_period", "OOS"),
                    is_profit_factor=is_pf,
                    oos_profit_factor=oos_pf,
                    is_net_pnl=is_pnl,
                    oos_net_pnl=oos_pnl,
                    is_trades=len(is_trades),
                    oos_trades=len(oos_trades),
                    walk_forward_efficiency=wfe,
                )
            )

        wfes = [f.walk_forward_efficiency for f in fold_results]
        mean_wfe = round(sum(wfes) / len(wfes), 4) if wfes else 0.0
        sorted_wfes = sorted(wfes)
        median_wfe = sorted_wfes[len(sorted_wfes) // 2] if sorted_wfes else 0.0

        n_profitable_oos = sum(1 for f in fold_results if f.oos_net_pnl > 0.0)
        profitable_ratio = round(n_profitable_oos / len(fold_results), 4) if fold_results else 0.0

        # Consistency score based on profitable OOS folds and WFE
        consistency = round(min(1.0, max(0.0, (profitable_ratio * 0.6 + min(1.0, max(0.0, mean_wfe)) * 0.4))), 4)

        return WalkForwardAnalysisResult(
            folds=fold_results,
            mean_wfe=mean_wfe,
            median_wfe=median_wfe,
            profitable_oos_folds_ratio=profitable_ratio,
            consistency_score=consistency,
        )
