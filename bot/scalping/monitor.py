"""
Open trade monitor — runs every 60 seconds.

Tracks all open scalping trades and handles:
  - Stop loss enforcement (price polling since MEXC Spot has no native SL)
  - Breakeven move: once target1 is hit, move SL to entry price
  - Trade closure notification via Telegram
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List

from bot.database import db

logger = logging.getLogger(__name__)


class TradeMonitor:
    def __init__(self):
        # open_trades: {symbol: trade_dict}
        self.open_trades: Dict[str, Dict[str, Any]] = {}

    async def add_trade(self, setup: Dict[str, Any], result: Dict[str, Any], user_id: int) -> None:
        """Register a newly executed trade and persist it to the database."""
        symbol = setup["symbol"]
        trade = {
            "symbol":        symbol,
            "entry_price":   setup["entry_price"],
            "stop_loss":     setup["stop_loss"],
            "target1":       setup["target1"],
            "target2":       setup["target2"],
            "qty":           setup["qty"],
            "qty_half":      setup["qty_half"],
            "risk_reward":   setup["risk_reward"],
            "t1_hit":        False,
            "t1_order_id":   result.get("target1_order", {}).get("id"),
            "t2_order_id":   result.get("target2_order", {}).get("id"),
            "opened_at":     datetime.now(timezone.utc).isoformat(),
            "breakeven":     False,
        }
        self.open_trades[symbol] = trade
        try:
            await db.save_scalping_trade(user_id, trade)
        except Exception as e:
            logger.error(f"Monitor: failed to persist trade {symbol}: {e}")
        logger.info(f"Monitor: tracking {symbol}")

    async def remove_trade(self, symbol: str) -> None:
        self.open_trades.pop(symbol, None)
        try:
            await db.delete_scalping_trade(symbol)
        except Exception as e:
            logger.error(f"Monitor: failed to delete trade {symbol} from DB: {e}")

    async def load_from_db(self) -> None:
        """Restore open trades from DB after a restart."""
        try:
            rows = await db.load_scalping_trades()
            for row in rows:
                self.open_trades[row["symbol"]] = {
                    "symbol":      row["symbol"],
                    "entry_price": row["entry_price"],
                    "stop_loss":   row["stop_loss"],
                    "target1":     row["target1"],
                    "target2":     row["target2"],
                    "qty":         row["qty"],
                    "qty_half":    row["qty_half"],
                    "risk_reward": row["risk_reward"],
                    "t1_hit":      bool(row["t1_hit"]),
                    "t1_order_id": row["t1_order_id"],
                    "t2_order_id": row["t2_order_id"],
                    "opened_at":   row["opened_at"],
                    "breakeven":   bool(row["breakeven"]),
                }
            if self.open_trades:
                logger.info(f"Monitor: restored {len(self.open_trades)} open trade(s) from DB")
        except Exception as e:
            logger.error(f"Monitor: failed to load trades from DB: {e}")

    @property
    def open_symbols(self) -> set:
        return set(self.open_trades.keys())

    async def check_all(self, exchange, bot, user_id: int) -> None:
        """
        Check every open trade against current price.
        Called every 60 seconds by the scheduler.
        """
        if not self.open_trades:
            return

        symbols = list(self.open_trades.keys())
        try:
            tickers = await exchange.fetch_tickers(symbols)
        except Exception as e:
            logger.error(f"Monitor: fetch_tickers failed: {e}")
            return

        for symbol, trade in list(self.open_trades.items()):
            ticker = tickers.get(symbol, {})
            price  = float(ticker.get("last") or 0)
            if price <= 0:
                continue

            await self._check_trade(trade, price, exchange, bot, user_id)

    async def _check_trade(
        self,
        trade: Dict[str, Any],
        price: float,
        exchange,
        bot,
        user_id: int,
    ) -> None:
        symbol    = trade["symbol"]
        stop_loss = trade["stop_loss"]
        target1   = trade["target1"]
        target2   = trade["target2"]

        # ── Stop loss hit ──────────────────────────────────────────────────
        if price <= stop_loss:
            await self._close_trade(trade, price, "stop_loss", exchange, bot, user_id)
            return

        # ── Target 1 hit → move SL to lock-in profit (trailing) ──────────
        if not trade["t1_hit"] and price >= target1:
            trade["t1_hit"]    = True
            # Move SL to 0.3% above entry instead of exact entry —
            # guarantees a small profit even if price reverses after T1.
            trailing_sl        = round(trade["entry_price"] * 1.003, 8)
            trade["stop_loss"] = trailing_sl
            trade["breakeven"] = True
            logger.info(f"Monitor: {symbol} hit T1 — SL trailed to {trailing_sl}")
            # Persist updated state so it survives a restart
            try:
                await db.save_scalping_trade(user_id, trade)
            except Exception as e:
                logger.error(f"Monitor: failed to update trade {symbol} in DB: {e}")
            await self._notify(
                bot, user_id,
                f"🎯 *{symbol}* — هدف 1 اتحقق!\n"
                f"✅ ربح جزئي عند `${target1:.6g}`\n"
                f"🔒 وقف الخسارة انتقل لـ `${trailing_sl:.6g}` (+0.3% ربح مضمون)\n"
                f"🎯 الهدف 2: `${target2:.6g}`"
            )
            return

        # ── Target 2 hit → full close ──────────────────────────────────────
        if trade["t1_hit"] and price >= target2:
            await self._close_trade(trade, price, "target2", exchange, bot, user_id)

    async def _close_trade(
        self,
        trade: Dict[str, Any],
        price: float,
        reason: str,
        exchange,
        bot,
        user_id: int,
    ) -> None:
        symbol = trade["symbol"]

        # Cancel any remaining open limit orders
        for order_id in [trade.get("t1_order_id"), trade.get("t2_order_id")]:
            if order_id:
                try:
                    await exchange.cancel_order(order_id, symbol)
                except Exception:
                    pass

        # Market sell remaining position if stop loss hit.
        # If T1 was already hit, half the position was sold at target1,
        # so only qty_half remains. Otherwise sell the full qty.
        if reason == "stop_loss":
            remaining_qty = trade["qty_half"] if trade["t1_hit"] else trade["qty"]
            try:
                await exchange.create_market_sell_order(symbol, remaining_qty)
            except Exception as e:
                logger.error(f"Monitor: emergency sell failed for {symbol}: {e}")

        await self.remove_trade(symbol)

        entry  = trade["entry_price"]
        pnl    = ((price - entry) / entry) * 100

        if reason == "stop_loss":
            msg = (
                f"🛑 *{symbol}* — وقف الخسارة\n\n"
                f"دخول: `${entry:.6g}`\n"
                f"خروج: `${price:.6g}`\n"
                f"📉 خسارة: `{pnl:.2f}%`"
            )
        else:
            msg = (
                f"✅ *{symbol}* — هدف 2 اتحقق!\n\n"
                f"دخول: `${entry:.6g}`\n"
                f"خروج: `${price:.6g}`\n"
                f"📈 ربح: `+{pnl:.2f}%`\n"
                f"📊 R/R: `{trade['risk_reward']}`"
            )

        logger.info(f"Monitor: {symbol} closed ({reason}) @ {price}")
        await self._notify(bot, user_id, msg)

    async def _notify(self, bot, user_id: int, text: str) -> None:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Monitor: notify failed: {e}")


# Singleton used across the app
trade_monitor = TradeMonitor()
