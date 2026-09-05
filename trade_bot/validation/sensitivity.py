"""
Parameter Sensitivity and Cliff Detection Engine.

Evaluates strategy stability across the approved parameter ranges from the strategy specification.
Identifies overfitted parameter spikes and unstable cliff edges.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List

from trade_bot.validation.models import (
    ExperimentSummary,
    ParameterSensitivityResult,
    ParameterVariationResult,
)


class ParameterSensitivityAnalyzer:
    """
    Analyzes parameter variations and identifies fragility or cliff edges.
    """

    @classmethod
    def analyze_parameter(
        cls,
        parameter_name: str,
        default_value: Any,
        variations_data: List[dict[str, Any]],
    ) -> ParameterSensitivityResult:
        """
        Analyzes a sweep of parameter variations.
        Each item in variations_data contains:
        - value: Any
        - summary: ExperimentSummary
        """
        if not variations_data:
            return ParameterSensitivityResult(
                parameter_name=parameter_name,
                default_value=default_value,
                tested_values=[],
                variations=[],
                profit_factor_cv=0.0,
                is_stable=True,
                cliff_detected=False,
            )

        tested_values = [v["value"] for v in variations_data]
        pfs = [max(0.0, min(10.0, v["summary"].profit_factor)) for v in variations_data]

        # Calculate Coefficient of Variation (CV) of Profit Factor
        mean_pf = sum(pfs) / len(pfs)
        if len(pfs) >= 2 and mean_pf > 0:
            variance = sum((pf - mean_pf) ** 2 for pf in pfs) / (len(pfs) - 1)
            std_pf = math.sqrt(variance)
            cv_pf = round(std_pf / mean_pf, 4)
        else:
            cv_pf = 0.0

        # Cliff detection across adjacent neighbors
        cliff_detected = False
        cliff_details = None
        variation_results: List[ParameterVariationResult] = []

        default_summary = next((v["summary"] for v in variations_data if v["value"] == default_value), variations_data[0]["summary"])
        default_pf = default_summary.profit_factor

        for i, v in enumerate(variations_data):
            curr_val = v["value"]
            curr_summary: ExperimentSummary = v["summary"]
            dev_pct = round(((curr_summary.profit_factor - default_pf) / default_pf) * 100.0, 2) if default_pf > 0 else 0.0

            # Check for sudden cliff vs previous neighbor
            if i > 0:
                prev_summary = variations_data[i - 1]["summary"]
                if prev_summary.profit_factor > 0:
                    neighbor_drop = (prev_summary.profit_factor - curr_summary.profit_factor) / prev_summary.profit_factor
                    if neighbor_drop >= 0.50:  # > 50% drop between adjacent parameter steps
                        cliff_detected = True
                        cliff_details = (
                            f"Cliff detected between {parameter_name}={variations_data[i-1]['value']} "
                            f"(PF={prev_summary.profit_factor:.2f}) and {curr_val} (PF={curr_summary.profit_factor:.2f}): "
                            f"{neighbor_drop*100:.1f}% drop"
                        )

            variation_results.append(
                ParameterVariationResult(
                    parameter_name=parameter_name,
                    parameter_value=curr_val,
                    summary=curr_summary,
                    neighbor_deviation_pct=dev_pct,
                )
            )

        is_stable = (not cliff_detected) and (cv_pf <= 0.40)

        return ParameterSensitivityResult(
            parameter_name=parameter_name,
            default_value=default_value,
            tested_values=tested_values,
            variations=variation_results,
            profit_factor_cv=cv_pf,
            is_stable=is_stable,
            cliff_detected=cliff_detected,
            cliff_details=cliff_details,
        )
