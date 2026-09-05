"""
Strategy Registry.

Provides registration and discovery mechanism for trading strategies.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional
from trade_bot.strategy.base import IStrategy


class StrategyRegistry:
    """Registry maintaining available strategy factories."""

    _registry: Dict[str, Callable[[], IStrategy]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Callable[[], IStrategy]], Callable[[], IStrategy]]:
        """Decorator to register a strategy factory."""
        def decorator(factory: Callable[[], IStrategy]) -> Callable[[], IStrategy]:
            cls._registry[name] = factory
            return factory
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[IStrategy]:
        """Create and return a new instance of the registered strategy."""
        factory = cls._registry.get(name)
        if factory is None:
            return None
        return factory()

    @classmethod
    def list_strategies(cls) -> List[str]:
        """Return list of registered strategy names."""
        return list(cls._registry.keys())
