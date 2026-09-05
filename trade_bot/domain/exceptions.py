"""
Domain Exception Hierarchy for Trade-Bot.

Structured exceptions with rich context to guarantee robust, fail-fast financial computing.
"""

from typing import Any, Dict, Optional


class TradingPlatformError(Exception):
    """Base exception for all Trade-Bot platform errors."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            return f"{self.message} | Context: {self.context}"
        return self.message


class ConfigurationError(TradingPlatformError):
    """Raised when configuration validation or loading fails."""
    pass


class DomainValidationError(TradingPlatformError):
    """Raised when a domain model invariant is violated."""
    pass


class InvalidOrderStateTransitionError(TradingPlatformError):
    """Raised when an illegal order state machine transition is attempted."""
    pass


class RiskViolationError(TradingPlatformError):
    """Base class for risk rule rejections and breaches."""
    pass


class DailyLossLimitExceededError(RiskViolationError):
    """Raised when cumulative daily loss limit is breached."""
    pass


class MaxDrawdownExceededError(RiskViolationError):
    """Raised when maximum drawdown limit is breached."""
    pass


class PositionLimitExceededError(RiskViolationError):
    """Raised when maximum concurrent open positions or max trade size is exceeded."""
    pass


class TradeRiskLimitExceededError(RiskViolationError):
    """Raised when the calculated financial risk for a single trade exceeds configured limit."""
    pass


class CircuitBreakerTriggeredError(RiskViolationError):
    """Raised when the system circuit breaker halts trading."""
    pass


class MarketClosedError(RiskViolationError):
    """Raised when an order or trade action is attempted outside allowed market trading hours."""
    pass


class OrderExecutionError(TradingPlatformError):
    """Base class for order submission, routing, and execution failures."""
    pass


class DuplicateOrderError(OrderExecutionError):
    """Raised when an idempotent duplicate order request is detected."""
    pass


class OrderNotFoundError(OrderExecutionError):
    """Raised when an order ID is not found in the tracking registry."""
    pass


class OrderRejectedError(OrderExecutionError):
    """Raised when an order is rejected by broker or pre-trade validation."""
    pass


class BrokerAdapterError(TradingPlatformError):
    """Base class for broker communication and protocol errors."""
    pass


class BrokerConnectionError(BrokerAdapterError):
    """Raised when network connection to broker fails."""
    pass


class BrokerAuthenticationError(BrokerAdapterError):
    """Raised when broker credentials, API tokens, or TOTP authentication fails."""
    pass


AuthenticationError = BrokerAuthenticationError


class BrokerRateLimitError(BrokerAdapterError):
    """Raised when broker API rate limits are exceeded."""
    pass


class MarketDataError(TradingPlatformError):
    """Base class for market data stream or historical feed errors."""
    pass


class DataFeedDisconnectedError(MarketDataError):
    """Raised when real-time market data feed disconnects unexpectedly."""
    pass


class MissingMarketDataError(MarketDataError):
    """Raised when required ticks, candles, or quotes are missing."""
    pass


class StateInconsistencyError(TradingPlatformError):
    """CRITICAL: Raised when an irreconcilable state discrepancy is detected (e.g. broker vs local position)."""
    pass


class InvalidStrategyStateTransitionError(TradingPlatformError):
    """Raised when an illegal strategy state transition is attempted."""
    pass


class DuplicateSignalError(TradingPlatformError):
    """Raised when an illegal duplicate strategy signal is emitted."""
    pass


class ProtectiveStopLossError(OrderExecutionError):
    """CRITICAL: Raised when placement or creation of a protective stop loss order fails."""
    pass


class InvalidStopLossModificationError(OrderExecutionError):
    """Raised when an order modification attempts to loosen risk on an existing stop loss."""
    pass


class EmergencyExitTriggeredError(TradingPlatformError):
    """CRITICAL: Raised when an emergency exit procedure is initiated."""
    pass


class ReconciliationError(TradingPlatformError):
    """Base exception for broker and internal state reconciliation failures."""
    pass


class CriticalStateDiscrepancyError(ReconciliationError):
    """CRITICAL: Raised when an unresolvable state discrepancy between broker and bot halts trading."""
    pass

