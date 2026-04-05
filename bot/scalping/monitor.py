"""
Open trade monitor — runs every 60 seconds.

Tracks all open scalping trades and handles:
  - Trailing stop: SL follows price upward at TRAIL_PCT below the highest
    price seen since entry. SL never moves down.
  - T1 partial exit: when price hits T1 (1.5R), sell 50% via market order
    and tighten the trail to TRAIL_PCT_AFTER_T1 (tighter after locking profit)
  - Trade closure: when price drops to trailing SL, market sell remainder
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from bot.database import db

logger = logging.getLogger(__name__)

TRAIL_PCT           = 0.015   # 1.5% trail distance before T1
TRAIL_PCT_AFTER_T1  = 0.010   # 1.0% trail distance after T1 (tighter — protect profit)


class TradeMonitor:
    def __init__(self):
        # open_trades: {symbol: trade_dict}
        self.open_trades: Dict[str, Dict[str, Any]] = {}

    async def add_trade(self, setup: Dict[str, Any], result: Dict[str, Any], user_id: int) -> None:
        """Register a newly executed trade and persist it to the database."""
        symbol = setup["symbol"]
        # Use actual filled qty from executor (may differ from estimated qty due to
        # MEXC Spot using quoteOrderQty for market buys)
        actual_qty      = float(result.get("filled_qty") or setup["qty"])
        actual_qty_half = float(result.get("qty_half")   or setup["qty_half"])
        entry_price     = setup["entry_price"]
        initial_sl      = setup["stop_loss"]
        trade = {
            "symbol":        symbol,
            "user_id":       user_id,
            "entry_price":   entry_price,
            "stop_loss":     initial_sl,
            "highest_price": entry_price,   # tracks peak price for trailing
            "target1":       setup["target1"],
            "target2":       setup["target1"],  # T2 removed — trailing handles exit
            "qty":           actual_qty,
            "qty_half":      actual_qty_half,
            "risk_reward":   setup["risk_reward"],
            "t1_hit":        False,
            "t1_order_id":   result.get("target1_order", {}).get("id"),
            "t2_order_id":   None,   # no T2 limit order
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
                # Skip whale trades — whale_monitor handles those
                if row.get("strategy") == "whale":
                    continue
                self.open_trades[row["symbol"]] = {
                    "symbol":        row["symbol"],
                    "user_id":       row.get("user_id"),
                    "entry_price":   row["entry_price"],
                    "stop_loss":     row["stop_loss"],
                    "highest_price": row.get("highest_price") or row["entry_price"],
                    "target1":       row["target1"],
                    "target2":       row["target2"],
                    "qty":           row["qty"],
                    "qty_half":      row["qty_half"],
                    "risk_reward":   row["risk_reward"],
                    "t1_hit":        bool(row["t1_hit"]),
                    "t1_order_id":   row["t1_order_id"],
                    "t2_order_id":   row["t2_order_id"],
                    "opened_at":     row["opened_at"],
                    "breakeven":     bool(row["breakeven"]),
                }
            if self.open_trades:
                logger.info(f"Monitor: restored {len(self.open_trades)} open trade(s) from DB")
        except Exception as e:
            logger.error(f"Monitor: failed to load trades from DB: {e}")

    @property
    def open_symbols(self) -> set:
        return set(self.open_trades.keys())

    def open_symbols_for(self, user_id: int) -> set:
        """Return only the symbols with open trades belonging to user_id."""
        return {sym for sym, t in self.open_trades.items() if t.get("user_id") == user_id}

    async def check_all(self, exchange, bot, user_id: int) -> None:
        """
        Check open trades belonging to user_id against current price.
        Called every 60 seconds by the scheduler.
        Filters by user_id so multiple users share the same singleton safely.
        """
        # Only process trades that belong to this user
        user_trades = {
            sym: t for sym, t in self.open_trades.items()
            if t.get("user_id") == user_id
        }
        if not user_trades:
            return

        symbols = list(user_trades.keys())
        try:
            tickers = await exchange.fetch_tickers(symbols)
        except Exception as e:
            logger.error(f"Monitor: fetch_tickers failed: {e}")
            return

        for symbol, trade in list(user_trades.items()):
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
        symbol  = trade["symbol"]
        target1 = trade["target1"]

        # ── Update trailing stop ───────────────────────────────────────────
        # Use tighter trail after T1 is hit (profit already locked)
        trail_pct = TRAIL_PCT_AFTER_T1 if trade["t1_hit"] else TRAIL_PCT

        if price > trade["highest_price"]:
            trade["highest_price"] = price
            new_sl = round(price * (1 - trail_pct), 8)
            if new_sl > trade["stop_loss"]:
                old_sl = trade["stop_loss"]
                trade["stop_loss"] = new_sl
                logger.info(
                    f"Monitor: {symbol} new high {price:.6g} — "
                    f"SL trailed {old_sl:.6g} → {new_sl:.6g}"
                )
                try:
                    await db.save_scalping_trade(user_id, trade)
                except Exception as e:
                    logger.error(f"Monitor: failed to update trailing SL for {symbol}: {e}")

        # ── Trailing stop hit → close ──────────────────────────────────────
        if price <= trade["stop_loss"]:
            await self._close_trade(trade, price, "trailing_stop", exchange, bot, user_id)
            return

        # ── T1 hit → sell 50%, tighten trail ──────────────────────────────
        if not trade["t1_hit"] and price >= target1:
            trade["t1_hit"]    = True
            trade["breakeven"] = True

            # Sell half position via market order.
            # No limit order to cancel — executor no longer places one,
            # so there is no risk of a double-sell race.
            try:
                await exchange.create_market_sell_order(symbol, trade["qty_half"])
                logger.info(f"Monitor: {symbol} T1 hit — sold {trade['qty_half']} @ {price:.6g}")
            except Exception as e:
                logger.error(f"Monitor: T1 partial sell failed for {symbol}: {e}")

            # Tighten trail immediately
            new_sl = round(price * (1 - TRAIL_PCT_AFTER_T1), 8)
            if new_sl > trade["stop_loss"]:
                trade["stop_loss"] = new_sl

            try:
                await db.save_scalping_trade(user_id, trade)
            except Exception as e:
                logger.error(f"Monitor: failed to update trade {symbol} after T1: {e}")

            entry  = trade["entry_price"]
            t1_pct = ((price - entry) / entry) * 100
            await self._notify(
                bot, user_id,
                f"🎯 *{symbol}* — هدف 1 اتحقق!\n\n"
                f"✅ بيع 50% عند `${price:.6g}`  (`+{t1_pct:.2f}%`)\n"
                f"🔒 الـ trailing stop انضغط لـ `{TRAIL_PCT_AFTER_T1*100:.0f}%`\n"
                f"📈 الباقي شغال مع الـ trailing — يلاحق السعر لأعلى"
            )

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

        # executor no longer places limit orders — nothing to cancel here.
        # t1_order_id and t2_order_id are kept in the schema for legacy rows
        # restored from DB but will always be None for new trades.

        # Sell remaining position:
        # If T1 was already hit, 50% was already sold — only qty_half remains.
        # Otherwise sell the full qty.
        remaining_qty = trade["qty_half"] if trade["t1_hit"] else trade["qty"]
        try:
            await exchange.create_market_sell_order(symbol, remaining_qty)
        except Exception as e:
            logger.error(f"Monitor: market sell failed for {symbol}: {e}")

        await self.remove_trade(symbol)

        entry       = trade["entry_price"]
        highest     = trade.get("highest_price", entry)
        pnl         = ((price - entry) / entry) * 100
        peak_pnl    = ((highest - entry) / entry) * 100

        if pnl < 0:
            result_icon = "🛑"
            result_line = f"📉 خسارة: `{pnl:.2f}%`"
        else:
            result_icon = "✅"
            result_line = f"📈 ربح: `+{pnl:.2f}%`"

        t1_line = "✅ هدف 1 تحقق (50% بيع)" if trade["t1_hit"] else "⏳ هدف 1 لم يُحقق"

        msg = (
            f"{result_icon} *{symbol}* — Trailing Stop\n\n"
            f"دخول:  `${entry:.6g}`\n"
            f"أعلى:  `${highest:.6g}`  (`+{peak_pnl:.2f}%`)\n"
            f"خروج:  `${price:.6g}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{result_line}\n"
            f"{t1_line}\n"
            f"📊 R/R: `{trade['risk_reward']}`"
        )

        logger.info(f"Monitor: {symbol} closed ({reason}) @ {price} pnl={pnl:.2f}%")
        await self._notify(bot, user_id, msg)

    async def _notify(self, bot, user_id: int, text: str) -> None:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Monitor: notify failed: {e}")


# Singleton used across the app
trade_monitor = TradeMonitor()
