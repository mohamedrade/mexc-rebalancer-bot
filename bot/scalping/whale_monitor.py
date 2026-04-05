"""
Whale trade monitor — runs every 30 seconds.

Handles fixed-target exits (no trailing stop):
  - T1 (+0.5%): sell 60%, keep 40%
  - T2 (+1.0%): sell remaining 40%
  - SL (-0.4%): sell everything immediately

Fast exits — average hold 5–15 minutes.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from bot.database import db

logger = logging.getLogger(__name__)


class WhaleTradeMonitor:
    def __init__(self):
        self.open_trades: Dict[str, Dict[str, Any]] = {}

    async def add_trade(self, setup: Dict, result: Dict, user_id: int) -> None:
        symbol     = setup["symbol"]
        filled_qty = float(result.get("filled_qty") or setup["qty"])
        qty_60     = round(filled_qty * 0.6, 8)
        qty_40     = round(filled_qty * 0.4, 8)

        trade = {
            "symbol":      symbol,
            "user_id":     user_id,
            "entry_price": setup["entry_price"],
            "stop_loss":   setup["stop_loss"],
            "target1":     setup["target1"],
            "target2":     setup["target2"],
            "qty":         filled_qty,
            "qty_60pct":   qty_60,
            "qty_40pct":   qty_40,
            "risk_reward": setup["risk_reward"],
            "t1_hit":      False,
            "t2_hit":      False,
            "opened_at":   datetime.now(timezone.utc).isoformat(),
            "strategy":    "whale",
        }
        self.open_trades[symbol] = trade
        try:
            await db.save_scalping_trade(user_id, trade)
        except Exception as e:
            logger.error(f"WhaleMonitor: failed to persist {symbol}: {e}")
        logger.info(f"WhaleMonitor: tracking {symbol}")

    async def remove_trade(self, symbol: str) -> None:
        self.open_trades.pop(symbol, None)
        try:
            await db.delete_scalping_trade(symbol)
        except Exception as e:
            logger.error(f"WhaleMonitor: failed to delete {symbol}: {e}")

    async def load_from_db(self) -> None:
        """Restore open whale trades from DB after a restart."""
        try:
            rows = await db.load_scalping_trades()
            for row in rows:
                # Only restore trades that belong to the whale strategy
                if row.get("strategy") != "whale":
                    continue
                filled_qty = float(row.get("qty") or 0)
                self.open_trades[row["symbol"]] = {
                    "symbol":      row["symbol"],
                    "user_id":     row.get("user_id"),
                    "entry_price": row["entry_price"],
                    "stop_loss":   row["stop_loss"],
                    "target1":     row["target1"],
                    "target2":     row["target2"],
                    "qty":         filled_qty,
                    "qty_60pct":   round(filled_qty * 0.6, 8),
                    "qty_40pct":   round(filled_qty * 0.4, 8),
                    "risk_reward": row["risk_reward"],
                    "t1_hit":      bool(row["t1_hit"]),
                    "t2_hit":      bool(row.get("t2_hit", 0)),
                    "opened_at":   row["opened_at"],
                    "strategy":    "whale",
                }
            if self.open_trades:
                logger.info(f"WhaleMonitor: restored {len(self.open_trades)} open trade(s) from DB")
        except Exception as e:
            logger.error(f"WhaleMonitor: failed to load trades from DB: {e}")

    @property
    def open_symbols(self) -> set:
        return set(self.open_trades.keys())

    def open_symbols_for(self, user_id: int) -> set:
        """Return only the symbols with open trades belonging to user_id."""
        return {sym for sym, t in self.open_trades.items() if t.get("user_id") == user_id}

    async def check_all(self, exchange, bot, user_id: int) -> None:
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
            logger.error(f"WhaleMonitor: fetch_tickers failed: {e}")
            return

        for symbol, trade in list(user_trades.items()):
            ticker = tickers.get(symbol, {})
            price  = float(ticker.get("last") or 0)
            if price <= 0:
                continue
            await self._check_trade(trade, price, exchange, bot, user_id)

    async def _check_trade(self, trade, price, exchange, bot, user_id) -> None:
        symbol  = trade["symbol"]
        target1 = trade["target1"]
        target2 = trade["target2"]
        sl      = trade["stop_loss"]

        # ── Stop loss hit ──────────────────────────────────────────────────
        if price <= sl:
            await self._close_trade(trade, price, "stop_loss", exchange, bot, user_id)
            return

        # ── T2 hit → sell remaining 40% ────────────────────────────────────
        if not trade["t2_hit"] and price >= target2:
            trade["t2_hit"] = True
            try:
                await exchange.create_market_sell_order(symbol, trade["qty_40pct"])
                logger.info(f"WhaleMonitor: {symbol} T2 hit — sold {trade['qty_40pct']} @ {price:.6g}")
            except Exception as e:
                logger.error(f"WhaleMonitor: T2 sell failed {symbol}: {e}")

            await self.remove_trade(symbol)
            entry  = trade["entry_price"]
            pnl    = ((price - entry) / entry) * 100
            await self._notify(
                bot, user_id,
                f"✅ *{symbol}* — هدف 2 اتحقق!\n\n"
                f"🎯 بيع 40% عند `${price:.6g}`  (`+{pnl:.2f}%`)\n"
                f"📊 الصفقة اتغلقت كاملاً"
            )
            return

        # ── T1 hit → sell 60% ──────────────────────────────────────────────
        if not trade["t1_hit"] and price >= target1:
            trade["t1_hit"] = True
            try:
                await exchange.create_market_sell_order(symbol, trade["qty_60pct"])
                logger.info(f"WhaleMonitor: {symbol} T1 hit — sold {trade['qty_60pct']} @ {price:.6g}")
            except Exception as e:
                logger.error(f"WhaleMonitor: T1 sell failed {symbol}: {e}")

            try:
                await db.save_scalping_trade(user_id, trade)
            except Exception:
                pass

            entry  = trade["entry_price"]
            pnl    = ((price - entry) / entry) * 100
            await self._notify(
                bot, user_id,
                f"🎯 *{symbol}* — هدف 1 اتحقق!\n\n"
                f"✅ بيع 60% عند `${price:.6g}`  (`+{pnl:.2f}%`)\n"
                f"⏳ الباقي (40%) شايل لهدف 2: `${target2:.6g}`\n"
                f"🛑 الوقف لسه: `${sl:.6g}`"
            )

    async def _close_trade(self, trade, price, reason, exchange, bot, user_id) -> None:
        symbol = trade["symbol"]

        # Sell whatever remains
        remaining = trade["qty_40pct"] if trade["t1_hit"] else trade["qty"]
        try:
            await exchange.create_market_sell_order(symbol, remaining)
        except Exception as e:
            logger.error(f"WhaleMonitor: close sell failed {symbol}: {e}")

        await self.remove_trade(symbol)

        entry = trade["entry_price"]
        pnl   = ((price - entry) / entry) * 100
        icon  = "✅" if pnl >= 0 else "🛑"
        sign  = "+" if pnl >= 0 else ""

        await self._notify(
            bot, user_id,
            f"{icon} *{symbol}* — إغلاق\n\n"
            f"دخول: `${entry:.6g}`\n"
            f"خروج: `${price:.6g}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{'📈 ربح' if pnl >= 0 else '📉 خسارة'}: `{sign}{pnl:.2f}%`\n"
            f"{'✅ هدف 1 تحقق' if trade['t1_hit'] else '⏳ هدف 1 لم يتحقق'}"
        )

    async def _notify(self, bot, user_id: int, text: str) -> None:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"WhaleMonitor: notify failed: {e}")


whale_monitor = WhaleTradeMonitor()
