"""
Grid engine — calculates grid levels and places orders on MEXC.

Given a center price, upper %, lower %, and number of steps:
  - Divides the range into equal price levels
  - Places limit buy orders below center
  - Places limit sell orders above center
  - Each filled buy immediately gets a sell placed one step above it
  - Each filled sell immediately gets a buy placed one step below it

Trailing: when price breaks above upper boundary → shift grid up
          when price breaks below lower boundary → shift grid down
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def calculate_grid_levels(
    center_price: float,
    upper_pct: float,
    lower_pct: float,
    steps: int,
) -> Dict[str, Any]:
    """
    Calculate grid price levels.

    Args:
        center_price: current market price
        upper_pct:    % above center (e.g. 10 for 10%)
        lower_pct:    % below center (e.g. 10 for 10%)
        steps:        number of grid levels (split equally above and below)

    Returns:
        {
            "upper":  float,         # upper boundary
            "lower":  float,         # lower boundary
            "levels": [float, ...],  # all price levels sorted ascending
            "step_pct": float,       # % between each level
            "buy_levels":  [float],  # levels below center
            "sell_levels": [float],  # levels above center
        }
    """
    upper = round(center_price * (1 + upper_pct / 100), 8)
    lower = round(center_price * (1 - lower_pct / 100), 8)

    total_range = upper - lower
    step_size   = total_range / steps
    step_pct    = round((step_size / center_price) * 100, 4)

    levels = [round(lower + i * step_size, 8) for i in range(steps + 1)]

    buy_levels  = [l for l in levels if l < center_price]
    sell_levels = [l for l in levels if l > center_price]

    return {
        "upper":       upper,
        "lower":       lower,
        "levels":      levels,
        "step_pct":    step_pct,
        "buy_levels":  buy_levels,
        "sell_levels": sell_levels,
        "center":      center_price,
    }


async def place_grid_orders(
    exchange,
    symbol: str,
    grid: Dict[str, Any],
    order_size_usdt: float,
) -> Dict[str, Any]:
    """
    Place initial grid orders on the exchange.

    Places limit buys at each buy level and limit sells at each sell level.
    order_size_usdt is split equally across all levels.

    Returns:
        {
            "buy_orders":  [{"price", "qty", "order_id"}, ...],
            "sell_orders": [{"price", "qty", "order_id"}, ...],
            "errors":      [str, ...],
        }
    """
    buy_orders  = []
    sell_orders = []
    errors      = []

    total_levels = len(grid["buy_levels"]) + len(grid["sell_levels"])
    if total_levels == 0:
        return {"buy_orders": [], "sell_orders": [], "errors": ["no levels"]}

    size_per_level = order_size_usdt / total_levels

    # Place buy orders (ascending — lowest first)
    for price in grid["buy_levels"]:
        qty = round(size_per_level / price, 8)
        try:
            order = await exchange.create_limit_buy_order(symbol, qty, price)
            buy_orders.append({
                "price":    price,
                "qty":      qty,
                "order_id": order.get("id"),
                "status":   "open",
            })
            logger.info(f"Grid: buy order placed {symbol} @ {price:.6g} qty={qty}")
        except Exception as e:
            errors.append(f"buy@{price:.6g}: {str(e)[:60]}")
            logger.warning(f"Grid: failed buy order {symbol} @ {price}: {e}")

    # Place sell orders (ascending)
    for price in grid["sell_levels"]:
        qty = round(size_per_level / price, 8)
        try:
            order = await exchange.create_limit_sell_order(symbol, qty, price)
            sell_orders.append({
                "price":    price,
                "qty":      qty,
                "order_id": order.get("id"),
                "status":   "open",
            })
            logger.info(f"Grid: sell order placed {symbol} @ {price:.6g} qty={qty}")
        except Exception as e:
            errors.append(f"sell@{price:.6g}: {str(e)[:60]}")
            logger.warning(f"Grid: failed sell order {symbol} @ {price}: {e}")

    return {
        "buy_orders":  buy_orders,
        "sell_orders": sell_orders,
        "errors":      errors,
    }


async def cancel_all_grid_orders(exchange, symbol: str, orders: List[Dict]) -> None:
    """Cancel all open grid orders for a symbol."""
    for order in orders:
        order_id = order.get("order_id")
        if not order_id:
            continue
        try:
            await exchange.cancel_order(order_id, symbol)
        except Exception:
            pass  # already filled or cancelled
