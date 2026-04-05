"""
Trade executor — places market entry only on MEXC.

Since MEXC Spot doesn't support native OCO orders:
  1. Market buy for full qty (using quoteOrderQty / cost)
  2. No T1 limit order — monitor.py handles T1 via price polling to avoid
     double-sell (limit fill + market sell racing each other)
  3. No T2 limit order — trailing stop in monitor.py handles the full exit
  4. Stop-loss is managed by monitor.py (price polling)
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def execute_trade(setup: Dict[str, Any], exchange) -> Dict[str, Any]:
    """
    Args:
        setup:    dict from scanner.scan() containing all trade parameters
        exchange: ccxt async exchange instance

    Returns:
        {
            "status":        "ok" | "error",
            "symbol":        str,
            "entry_order":   dict,
            "target1_order": dict,   # always empty — monitor handles T1
            "target2_order": dict,
            "filled_qty":    float,
            "qty_half":      float,
            "reason":        str,    # only on error
        }
    """
    symbol          = setup["symbol"]
    trade_size_usdt = setup["qty"] * setup["entry_price"]   # recover USDT cost

    try:
        # ── Market buy (MEXC Spot requires quoteOrderQty, not base qty) ───
        entry_order = await exchange.create_market_buy_order_with_cost(symbol, trade_size_usdt)
        logger.info(f"Executor: market buy {symbol} cost={trade_size_usdt} → order {entry_order.get('id')}")

        # Use the actual filled qty from the order
        filled_qty = float(entry_order.get("filled") or entry_order.get("amount") or 0)
        if filled_qty <= 0:
            avg_price = float(entry_order.get("average") or entry_order.get("price") or setup["entry_price"])
            filled_qty = trade_size_usdt / avg_price if avg_price > 0 else setup["qty"]

        qty_half = round(filled_qty / 2, 8)

        # T1 and trailing stop are handled entirely by monitor.py via price
        # polling — no limit orders placed here to prevent double-sell races.

        return {
            "status":        "ok",
            "symbol":        symbol,
            "entry_order":   entry_order,
            "target1_order": {},   # intentionally empty
            "target2_order": {},
            "filled_qty":    filled_qty,
            "qty_half":      qty_half,
            "reason":        "",
        }

    except Exception as e:
        logger.error(f"Executor: failed on {symbol}: {e}")
        return {
            "status":        "error",
            "symbol":        symbol,
            "entry_order":   {},
            "target1_order": {},
            "target2_order": {},
            "reason":        str(e)[:120],
        }
