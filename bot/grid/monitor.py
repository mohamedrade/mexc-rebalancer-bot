"""
Grid monitor — runs every 30 seconds.

For each active grid:
  1. Fetch current price
  2. Check if any limit orders got filled
  3. For each filled buy  → place a sell one step above
  4. For each filled sell → place a buy one step below
  5. Check trailing: if price > upper boundary → shift grid up
                     if price < lower boundary → shift grid down
  6. Check take profit / stop loss if configured
"""

import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

from bot.grid.engine import (
    calculate_grid_levels,
    place_grid_orders,
    cancel_all_grid_orders,
)
from bot.database import db

logger = logging.getLogger(__name__)


class GridMonitor:
    def __init__(self):
        # active_grids: {grid_id: grid_dict}
        self.active_grids: Dict[int, Dict[str, Any]] = {}

    async def load_from_db(self) -> None:
        try:
            rows = await db.load_grids()
            for row in rows:
                self.active_grids[row["id"]] = dict(row)
            if self.active_grids:
                logger.info(f"GridMonitor: restored {len(self.active_grids)} grid(s)")
        except Exception as e:
            logger.error(f"GridMonitor: failed to load grids: {e}")

    async def add_grid(self, grid: Dict[str, Any]) -> None:
        self.active_grids[grid["id"]] = grid

    async def remove_grid(self, grid_id: int) -> None:
        self.active_grids.pop(grid_id, None)
        try:
            await db.delete_grid(grid_id)
        except Exception as e:
            logger.error(f"GridMonitor: failed to delete grid {grid_id}: {e}")

    async def check_all(self, exchange_factory, bot) -> None:
        """Called every 30 seconds by the scheduler."""
        for grid_id, grid in list(self.active_grids.items()):
            try:
                client_args = (grid["mexc_api_key"], grid["mexc_secret_key"])
                exchange = exchange_factory(*client_args)
                try:
                    await self._check_grid(grid, exchange, bot)
                finally:
                    await exchange.close()
            except Exception as e:
                logger.error(f"GridMonitor: error on grid {grid_id}: {e}")

    async def _check_grid(self, grid: Dict, exchange, bot) -> None:
        grid_id = grid["id"]
        symbol  = grid["symbol"]
        user_id = grid["user_id"]

        # ── Get current price ──────────────────────────────────────────────
        try:
            ticker = await exchange.fetch_ticker(symbol)
            price  = float(ticker.get("last") or 0)
        except Exception as e:
            logger.warning(f"GridMonitor: failed to fetch price {symbol}: {e}")
            return

        if price <= 0:
            return

        # ── Stop Loss check ────────────────────────────────────────────────
        if grid.get("stop_loss") and price <= grid["stop_loss"]:
            await self._close_grid(grid, exchange, bot, price, reason="stop_loss")
            return

        # ── Take Profit check ──────────────────────────────────────────────
        if grid.get("take_profit") and price >= grid["take_profit"]:
            await self._close_grid(grid, exchange, bot, price, reason="take_profit")
            return

        # ── Check filled orders and place counter-orders ───────────────────
        buy_orders  = grid.get("buy_orders", [])
        sell_orders = grid.get("sell_orders", [])
        step_size   = (grid["upper"] - grid["lower"]) / grid["steps"]
        size_per_level = grid["order_size_usdt"] / grid["steps"]

        changed = False

        for order in buy_orders:
            if order["status"] != "open":
                continue
            try:
                o = await exchange.fetch_order(order["order_id"], symbol)
                if o["status"] == "closed":
                    order["status"] = "filled"
                    changed = True
                    # Place sell one step above
                    sell_price = round(order["price"] + step_size, 8)
                    qty = round(size_per_level / sell_price, 8)
                    try:
                        new_order = await exchange.create_limit_sell_order(symbol, qty, sell_price)
                        sell_orders.append({
                            "price":    sell_price,
                            "qty":      qty,
                            "order_id": new_order.get("id"),
                            "status":   "open",
                        })
                        grid["total_trades"] = grid.get("total_trades", 0) + 1
                        logger.info(f"GridMonitor: {symbol} buy filled @ {order['price']:.6g} → sell placed @ {sell_price:.6g}")
                    except Exception as e:
                        logger.warning(f"GridMonitor: counter-sell failed {symbol}: {e}")
            except Exception:
                pass

        for order in sell_orders:
            if order["status"] != "open":
                continue
            try:
                o = await exchange.fetch_order(order["order_id"], symbol)
                if o["status"] == "closed":
                    order["status"] = "filled"
                    changed = True
                    # Place buy one step below
                    buy_price = round(order["price"] - step_size, 8)
                    qty = round(size_per_level / buy_price, 8)
                    try:
                        new_order = await exchange.create_limit_buy_order(symbol, buy_price, qty)
                        buy_orders.append({
                            "price":    buy_price,
                            "qty":      qty,
                            "order_id": new_order.get("id"),
                            "status":   "open",
                        })
                        grid["total_trades"] = grid.get("total_trades", 0) + 1
                        logger.info(f"GridMonitor: {symbol} sell filled @ {order['price']:.6g} → buy placed @ {buy_price:.6g}")
                    except Exception as e:
                        logger.warning(f"GridMonitor: counter-buy failed {symbol}: {e}")
            except Exception:
                pass

        # ── Trailing: shift grid if price breaks boundary ──────────────────
        shifted = False
        if price > grid["upper"]:
            logger.info(f"GridMonitor: {symbol} price {price:.6g} > upper {grid['upper']:.6g} — shifting grid up")
            await self._shift_grid(grid, exchange, bot, price, direction="up")
            shifted = True
        elif price < grid["lower"]:
            logger.info(f"GridMonitor: {symbol} price {price:.6g} < lower {grid['lower']:.6g} — shifting grid down")
            await self._shift_grid(grid, exchange, bot, price, direction="down")
            shifted = True

        if (changed or shifted) and not shifted:
            try:
                await db.update_grid(grid)
            except Exception as e:
                logger.error(f"GridMonitor: failed to update grid {grid_id}: {e}")

    async def _shift_grid(self, grid: Dict, exchange, bot, new_center: float, direction: str) -> None:
        symbol  = grid["symbol"]
        user_id = grid["user_id"]

        # Cancel all open orders
        all_orders = grid.get("buy_orders", []) + grid.get("sell_orders", [])
        await cancel_all_grid_orders(exchange, symbol, [o for o in all_orders if o["status"] == "open"])

        # Recalculate grid around new center
        new_grid = calculate_grid_levels(
            center_price = new_center,
            upper_pct    = grid["upper_pct"],
            lower_pct    = grid["lower_pct"],
            steps        = grid["steps"],
        )

        grid["upper"]  = new_grid["upper"]
        grid["lower"]  = new_grid["lower"]
        grid["center"] = new_center

        # Place new orders
        result = await place_grid_orders(
            exchange        = exchange,
            symbol          = symbol,
            grid            = new_grid,
            order_size_usdt = grid["order_size_usdt"],
        )

        grid["buy_orders"]  = result["buy_orders"]
        grid["sell_orders"] = result["sell_orders"]
        grid["shifts"]      = grid.get("shifts", 0) + 1

        try:
            await db.update_grid(grid)
        except Exception as e:
            logger.error(f"GridMonitor: failed to save shifted grid: {e}")

        arrow = "⬆️" if direction == "up" else "⬇️"
        await self._notify(
            bot, user_id,
            f"{arrow} *{symbol}* — الشبكة انتقلت {direction}\n\n"
            f"السعر الحالي: `${new_center:.6g}`\n"
            f"الحد الجديد العلوي: `${new_grid['upper']:.6g}`\n"
            f"الحد الجديد السفلي: `${new_grid['lower']:.6g}`\n"
            f"عدد الانتقالات: `{grid['shifts']}`"
        )

    async def _close_grid(self, grid: Dict, exchange, bot, price: float, reason: str) -> None:
        symbol  = grid["symbol"]
        user_id = grid["user_id"]

        all_orders = grid.get("buy_orders", []) + grid.get("sell_orders", [])
        await cancel_all_grid_orders(exchange, symbol, [o for o in all_orders if o["status"] == "open"])

        await self.remove_grid(grid["id"])

        if reason == "take_profit":
            icon = "✅"
            reason_ar = "Take Profit"
        else:
            icon = "🛑"
            reason_ar = "Stop Loss"

        trades = grid.get("total_trades", 0)
        shifts = grid.get("shifts", 0)

        await self._notify(
            bot, user_id,
            f"{icon} *{symbol}* — الشبكة أُغلقت ({reason_ar})\n\n"
            f"السعر: `${price:.6g}`\n"
            f"إجمالي الصفقات المنفذة: `{trades}`\n"
            f"عدد انتقالات الشبكة: `{shifts}`"
        )

    async def _notify(self, bot, user_id: int, text: str) -> None:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"GridMonitor: notify failed: {e}")


grid_monitor = GridMonitor()
