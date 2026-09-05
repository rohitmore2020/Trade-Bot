"""
Upstox API v2 Domain Normalization Models and Transformers.

Provides pure mapping between Upstox API v2 / HFT request/response schemas
and internal domain models (OrderRequest, Order, Position, Trade, AccountBalance).
Includes credential redaction utilities to guarantee zero sensitive data exposure.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from trade_bot.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    TimeInForce,
)
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
    utc_now,
)


# =============================================================================
# Value Mappings
# =============================================================================

PRODUCT_TO_UPSTOX: Dict[ProductType, str] = {
    ProductType.MIS: "I",  # Intraday
    ProductType.CNC: "D",  # Delivery
    ProductType.NRML: "D",
}

UPSTOX_TO_PRODUCT: Dict[str, ProductType] = {
    "I": ProductType.MIS,
    "INTRADAY": ProductType.MIS,
    "MIS": ProductType.MIS,
    "D": ProductType.CNC,
    "DELIVERY": ProductType.CNC,
    "CNC": ProductType.CNC,
    "MTF": ProductType.CNC,
}

ORDER_TYPE_TO_UPSTOX: Dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL_MARKET: "SL-M",
    OrderType.SL_LIMIT: "SL",
}

UPSTOX_TO_ORDER_TYPE: Dict[str, OrderType] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "SL-M": OrderType.SL_MARKET,
    "SL": OrderType.SL_LIMIT,
}

SIDE_TO_UPSTOX: Dict[OrderSide, str] = {
    OrderSide.BUY: "BUY",
    OrderSide.SELL: "SELL",
}

UPSTOX_TO_SIDE: Dict[str, OrderSide] = {
    "BUY": OrderSide.BUY,
    "SELL": OrderSide.SELL,
}

UPSTOX_STATUS_MAP: Dict[str, OrderStatus] = {
    "complete": OrderStatus.FILLED,
    "completed": OrderStatus.FILLED,
    "filled": OrderStatus.FILLED,
    "open": OrderStatus.ACKNOWLEDGED,
    "trigger pending": OrderStatus.ACKNOWLEDGED,
    "after market order req received": OrderStatus.ACKNOWLEDGED,
    "put order req received": OrderStatus.ACKNOWLEDGED,
    "validation pending": OrderStatus.PENDING_SUBMIT,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "rejected": OrderStatus.REJECTED,
    "cancelled": OrderStatus.CANCELLED,
    "expired": OrderStatus.EXPIRED,
}


# =============================================================================
# Redaction & Security Utilities
# =============================================================================

_SENSITIVE_KEYS = re.compile(r"(token|secret|password|key|auth|credential|authorization)", re.IGNORECASE)


def redact_token(token: Optional[str]) -> str:
    """Mask token leaving only short prefix or complete redaction."""
    if not token:
        return "[EMPTY]"
    if len(token) <= 8:
        return "[REDACTED]"
    return f"{token[:4]}...[REDACTED]"


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return headers dictionary with Authorization/Tokens sanitized."""
    sanitized = dict(headers)
    for k in list(sanitized.keys()):
        if _SENSITIVE_KEYS.search(k):
            val = sanitized[k]
            if val.lower().startswith("bearer "):
                sanitized[k] = f"Bearer {redact_token(val[7:].strip())}"
            else:
                sanitized[k] = redact_token(val)
    return sanitized


def sanitize_log_data(data: Any) -> Any:
    """Recursively sanitize nested dictionaries or lists for secure logging."""
    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            if _SENSITIVE_KEYS.search(str(k)):
                sanitized[k] = redact_token(str(v))
            else:
                sanitized[k] = sanitize_log_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_log_data(item) for item in data]
    return data


# =============================================================================
# Request Builders
# =============================================================================

def build_order_payload(
    request: OrderRequest,
    instrument_token_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build Upstox v2 / HFT place order request payload.
    Conforms to https://api-hft.upstox.com/v2/order/place
    """
    token_map = instrument_token_map or {}
    # Use mapped instrument token (e.g. NSE_EQ|INE...) or fallback to symbol with exchange prefix
    instrument_token = token_map.get(request.symbol, f"NSE_EQ|{request.symbol}")

    product = PRODUCT_TO_UPSTOX.get(request.product_type, "I")
    order_type = ORDER_TYPE_TO_UPSTOX.get(request.order_type, "MARKET")
    transaction_type = SIDE_TO_UPSTOX.get(request.side, "BUY")
    validity = "IOC" if request.time_in_force == TimeInForce.IOC else "DAY"

    price = float(request.price) if request.price is not None and request.order_type in (OrderType.LIMIT, OrderType.SL_LIMIT) else 0.0
    trigger_price = float(request.trigger_price) if request.trigger_price is not None and request.order_type in (OrderType.SL_MARKET, OrderType.SL_LIMIT) else 0.0

    payload: Dict[str, Any] = {
        "quantity": int(request.quantity),
        "product": product,
        "validity": validity,
        "price": price,
        "tag": request.tag or request.client_order_id,
        "instrument_token": instrument_token,
        "order_type": order_type,
        "transaction_type": transaction_type,
        "disclosed_quantity": 0,
        "trigger_price": trigger_price,
        "is_amo": False,
    }
    return payload


def build_modify_payload(modification: OrderModification) -> Dict[str, Any]:
    """
    Build Upstox v2 / HFT modify order request payload.
    Conforms to https://api-hft.upstox.com/v2/order/modify
    """
    payload: Dict[str, Any] = {
        "order_id": str(modification.order_id),
        "validity": "DAY",
    }
    if modification.quantity is not None:
        payload["quantity"] = int(modification.quantity)
    if modification.price is not None:
        payload["price"] = float(modification.price)
    if modification.trigger_price is not None:
        payload["trigger_price"] = float(modification.trigger_price)
    if modification.order_type is not None:
        payload["order_type"] = ORDER_TYPE_TO_UPSTOX.get(modification.order_type, "MARKET")
    return payload


# =============================================================================
# Response Normalizers
# =============================================================================

def parse_upstox_timestamp(ts_str: Optional[str]) -> datetime:
    """Parse Upstox exchange timestamp string into timezone-aware datetime."""
    if not ts_str:
        return utc_now()
    try:
        # e.g., "2024-01-08 10:15:30" or ISO format
        clean = ts_str.strip()
        if "T" in clean:
            return datetime.fromisoformat(clean.replace("Z", "+00:00"))
        return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return utc_now()


def normalize_order(data: Dict[str, Any]) -> Order:
    """
    Normalize Upstox order book JSON record into domain Order.
    """
    order_id = str(data.get("order_id", ""))
    tag = data.get("tag")
    client_order_id = tag if tag else f"UPSTOX_{order_id}"

    # Symbol normalization (Upstox tradingsymbol, e.g. "RELIANCE-EQ" -> "RELIANCE")
    raw_symbol = str(data.get("tradingsymbol") or data.get("trading_symbol") or "")
    symbol = raw_symbol.replace("-EQ", "").strip().upper()

    side = UPSTOX_TO_SIDE.get(str(data.get("transaction_type", "")).upper(), OrderSide.BUY)
    order_type = UPSTOX_TO_ORDER_TYPE.get(str(data.get("order_type", "")).upper(), OrderType.MARKET)
    product_type = UPSTOX_TO_PRODUCT.get(str(data.get("product", "")).upper(), ProductType.MIS)

    quantity = int(data.get("quantity", 0))
    filled_qty = int(data.get("filled_quantity", 0))
    price = float(data.get("price", 0.0)) if data.get("price") is not None else None
    trigger_price = float(data.get("trigger_price", 0.0)) if data.get("trigger_price") is not None else None
    avg_price = float(data.get("average_price", 0.0)) if data.get("average_price") is not None else 0.0

    raw_status = str(data.get("status", "")).lower().strip()
    status = UPSTOX_STATUS_MAP.get(raw_status, OrderStatus.ACKNOWLEDGED)

    # In partial fill state, if partially filled
    if status == OrderStatus.ACKNOWLEDGED and 0 < filled_qty < quantity:
        status = OrderStatus.PARTIALLY_FILLED

    rejection_reason = data.get("status_message")

    order = Order(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        product_type=product_type,
        time_in_force=TimeInForce.DAY,
        price=price,
        trigger_price=trigger_price,
        broker_order_id=order_id,
        status=status,
        filled_quantity=filled_qty,
        average_fill_price=avg_price,
        rejection_reason=rejection_reason,
    )
    return order


def normalize_position(data: Dict[str, Any]) -> Position:
    """
    Normalize Upstox portfolio position JSON record into domain Position.
    """
    raw_symbol = str(data.get("tradingsymbol") or data.get("trading_symbol") or "")
    symbol = raw_symbol.replace("-EQ", "").strip().upper()

    product_type = UPSTOX_TO_PRODUCT.get(str(data.get("product", "")).upper(), ProductType.MIS)
    quantity = int(data.get("quantity", 0))
    avg_price = float(data.get("average_price", 0.0) or 0.0)
    last_price = float(data.get("last_price", 0.0) or avg_price)
    realized_pnl = float(data.get("realised", 0.0) or 0.0)
    unrealized_pnl = float(data.get("unrealised", 0.0) or 0.0)

    pos = Position(
        symbol=symbol,
        product_type=product_type,
        quantity=quantity,
        average_price=avg_price,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        last_price=last_price,
    )
    return pos


def normalize_trade(data: Dict[str, Any]) -> Trade:
    """
    Normalize Upstox trade history item into domain Trade fill.
    """
    trade_id = str(data.get("trade_id", ""))
    order_id = str(data.get("order_id", ""))
    raw_symbol = str(data.get("tradingsymbol") or data.get("trading_symbol") or "")
    symbol = raw_symbol.replace("-EQ", "").strip().upper()

    side = UPSTOX_TO_SIDE.get(str(data.get("transaction_type", "")).upper(), OrderSide.BUY)
    quantity = int(data.get("quantity", 0))
    price = float(data.get("average_price", 0.0) or 0.0)
    ts = parse_upstox_timestamp(data.get("exchange_timestamp") or data.get("order_timestamp"))

    trade = Trade(
        trade_id=trade_id,
        order_id=order_id,
        client_order_id=data.get("order_ref_id") or f"UPSTOX_{order_id}",
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        timestamp=ts,
        exchange=data.get("exchange", "NSE"),
    )
    return trade


def normalize_funds(data: Dict[str, Any]) -> AccountBalance:
    """
    Normalize Upstox /user/get-funds-and-margin JSON payload into domain AccountBalance.
    """
    equity_data = data.get("equity", {})
    available_margin = float(equity_data.get("available_margin", 0.0) or 0.0)
    used_margin = float(equity_data.get("used_margin", 0.0) or 0.0)
    payin = float(equity_data.get("payin_amount", 0.0) or 0.0)

    total_capital = available_margin + used_margin

    return AccountBalance(
        initial_capital=round(total_capital, 2),
        available_cash=round(available_margin, 2),
        used_margin=round(used_margin, 2),
        currency="INR",
        timestamp=utc_now(),
    )
