"""
Trade executor — places market entry + limit targets + stop loss on MEXC.

Since MEXC Spot doesn't support native OCO orders, we place:
  1. Market buy for full qty
  2. Limit sell at target1 for qty_half
  3. Limit sell at target2 for qty_half
  4. Stop-loss is managed by monitor.py (price polling) to avoid exchange limitations
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
            "status":       "ok" | "error",
            "symbol":       str,
            "entry_order":  dict,
            "target1_order": dict,
            "target2_order": dict,
            "reason":       str,   # only on error
        }
    """
    symbol          = setup["symbol"]
    trade_size_usdt = setup["qty"] * setup["entry_price"]   # recover USDT cost
    target1         = setup["target1"]
    target2         = setup["target2"]

    try:
        # ── 1. Market buy (MEXC Spot requires quoteOrderQty, not base qty) ─
        entry_order = await exchange.create_market_buy_order_with_cost(symbol, trade_size_usdt)
        logger.info(f"Executor: market buy {symbol} cost={trade_size_usdt} → order {entry_order.get('id')}")

        # Use the actual filled qty from the order so limit sells match exactly
        filled_qty = float(entry_order.get("filled") or entry_order.get("amount") or 0)
        if filled_qty <= 0:
            # Fallback: estimate from cost / average price
            avg_price = float(entry_order.get("average") or entry_order.get("price") or setup["entry_price"])
            filled_qty = trade_size_usdt / avg_price if avg_price > 0 else setup["qty"]

        qty_half = round(filled_qty / 2, 8)

        # ── 2. Limit sell at target1 (50%) ────────────────────────────────
        t1_order = await exchange.create_limit_sell_order(symbol, qty_half, target1)
        logger.info(f"Executor: limit sell {symbol} @{target1} qty={qty_half} → {t1_order.get('id')}")

        # ── 3. Limit sell at target2 (remaining 50%) ──────────────────────
        t2_order = await exchange.create_limit_sell_order(symbol, qty_half, target2)
        logger.info(f"Executor: limit sell {symbol} @{target2} qty={qty_half} → {t2_order.get('id')}")

        return {
            "status":        "ok",
            "symbol":        symbol,
            "entry_order":   entry_order,
            "target1_order": t1_order,
            "target2_order": t2_order,
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
