"""
Architecture Boundary Tests.

Verifies strict dependency rules:
Domain layer must have ZERO imports from broker, persistence, execution, or external network adapters.
"""

import ast
from pathlib import Path
import pytest


def test_domain_layer_has_zero_infrastructure_dependencies() -> None:
    domain_dir = Path("trade_bot/domain")
    assert domain_dir.exists()

    forbidden_patterns = [
        "trade_bot.broker",
        "trade_bot.persistence",
        "trade_bot.execution",
        "trade_bot.orchestration",
        "requests",
        "httpx",
        "websockets",
        "upstox",
    ]

    for py_file in domain_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_patterns:
                        assert not alias.name.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports '{alias.name}', "
                            f"which violates domain isolation from '{forbidden}'."
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_patterns:
                        assert not node.module.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports from '{node.module}', "
                            f"which violates domain isolation from '{forbidden}'."
                        )


def test_strategy_layer_has_zero_infrastructure_dependencies() -> None:
    strategy_dir = Path("trade_bot/strategy")
    assert strategy_dir.exists()

    forbidden_patterns = [
        "trade_bot.broker",
        "trade_bot.persistence",
        "trade_bot.execution",
        "trade_bot.orchestration",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "upstox",
        "logging",
    ]

    for py_file in strategy_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_patterns:
                        assert not alias.name.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports '{alias.name}', "
                            f"which violates pure strategy domain isolation from '{forbidden}'."
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_patterns:
                        assert not node.module.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports from '{node.module}', "
                            f"which violates pure strategy domain isolation from '{forbidden}'."
                        )


def test_risk_layer_has_zero_infrastructure_dependencies() -> None:
    risk_dir = Path("trade_bot/risk")
    assert risk_dir.exists()

    forbidden_patterns = [
        "trade_bot.broker",
        "trade_bot.persistence",
        "trade_bot.execution",
        "trade_bot.orchestration",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "upstox",
        "sqlite3",
        "duckdb",
    ]

    for py_file in risk_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_patterns:
                        assert not alias.name.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports '{alias.name}', "
                            f"which violates pure risk domain isolation from '{forbidden}'."
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_patterns:
                        assert not node.module.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports from '{node.module}', "
                            f"which violates pure risk domain isolation from '{forbidden}'."
                        )


def test_portfolio_layer_has_zero_infrastructure_dependencies() -> None:
    portfolio_dir = Path("trade_bot/portfolio")
    assert portfolio_dir.exists()

    forbidden_patterns = [
        "trade_bot.broker",
        "trade_bot.persistence",
        "trade_bot.execution",
        "trade_bot.orchestration",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "upstox",
        "sqlite3",
        "duckdb",
    ]

    for py_file in portfolio_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_patterns:
                        assert not alias.name.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports '{alias.name}', "
                            f"which violates pure portfolio domain isolation from '{forbidden}'."
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_patterns:
                        assert not node.module.startswith(forbidden), (
                            f"Architectural boundary violation: {py_file} imports from '{node.module}', "
                            f"which violates pure portfolio domain isolation from '{forbidden}'."
                        )



