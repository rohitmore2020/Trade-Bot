"""
Data Quality Reporting.

Generates human-readable Markdown and structured dictionary audits of data quality and completeness.
"""

from __future__ import annotations

from typing import Any, Dict
from trade_bot.data.validator import ValidationReport


def generate_data_quality_markdown(report: ValidationReport) -> str:
    """Format validation metrics into an audit report in GitHub markdown."""
    status_badge = "✅ PASSED" if report.is_valid and report.completeness_percentage >= 95.0 else "⚠️ WARNING / FAILED"

    lines = [
        f"# Data Quality Audit Report: {report.symbol}",
        "",
        f"**Audit Status**: {status_badge}",
        f"- **Timeframe**: {report.timeframe_seconds} seconds ({report.timeframe_seconds // 60}m)",
        f"- **Total Bars Received**: {report.total_bars:,}",
        f"- **Expected Bars (NSE Calendar)**: {report.expected_bars:,}",
        f"- **Completeness**: {report.completeness_percentage:.2f}%",
        "",
        "## Integrity Check Summary",
        "",
        "| Validation Check | Count | Status |",
        "|---|---|---|",
        f"| Valid Bars | {report.valid_bars:,} | {'✅ Pass' if report.valid_bars > 0 else '❌ Fail'} |",
        f"| Invalid OHLC Violations | {report.invalid_ohlc_bars:,} | {'✅ Pass' if report.invalid_ohlc_bars == 0 else '❌ Fail'} |",
        f"| Negative Volume Violations | {report.invalid_volume_bars:,} | {'✅ Pass' if report.invalid_volume_bars == 0 else '❌ Fail'} |",
        f"| Duplicate Timestamps | {report.duplicate_timestamps:,} | {'✅ Pass' if report.duplicate_timestamps == 0 else '❌ Fail'} |",
        f"| Out-of-Session Bars | {report.out_of_session_bars:,} | {'✅ Pass' if report.out_of_session_bars == 0 else '❌ Fail'} |",
        f"| Missing Expected Bars | {report.missing_bars:,} | {'✅ Pass' if report.missing_bars == 0 else '⚠️ Incomplete'} |",
        "",
    ]

    if report.errors:
        lines.extend([
            "## Anomaly Details (First 10 Errors)",
            "",
            "| Timestamp | Error Type | Description |",
            "|---|---|---|",
        ])
        for err in report.errors[:10]:
            ts_str = err.timestamp.isoformat() if hasattr(err.timestamp, "isoformat") else str(err.timestamp)
            lines.append(f"| {ts_str} | `{err.error_type}` | {err.description} |")
        lines.append("")

    if report.missing_timestamps:
        lines.extend([
            "## Missing Timestamps Sample (First 5)",
            "",
        ])
        for mts in report.missing_timestamps[:5]:
            lines.append(f"- {mts.isoformat()}")
        lines.append("")

    return "\n".join(lines)


def validation_report_to_dict(report: ValidationReport) -> Dict[str, Any]:
    """Convert validation report into a JSON-serializable dictionary."""
    return {
        "symbol": report.symbol,
        "timeframe_seconds": report.timeframe_seconds,
        "is_valid": report.is_valid,
        "total_bars": report.total_bars,
        "valid_bars": report.valid_bars,
        "invalid_ohlc_bars": report.invalid_ohlc_bars,
        "invalid_volume_bars": report.invalid_volume_bars,
        "duplicate_timestamps": report.duplicate_timestamps,
        "out_of_session_bars": report.out_of_session_bars,
        "missing_bars": report.missing_bars,
        "expected_bars": report.expected_bars,
        "completeness_percentage": report.completeness_percentage,
        "error_count": len(report.errors),
    }
