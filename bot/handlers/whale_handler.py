"""
Telegram handler for the Whale Order Flow scalping strategy.

Scan runs every 5 minutes. Monitor runs every 30 seconds.
Targets: T1=+0.5% (sell 60%), T2=+1.0% (sell 40%), SL=-0.4%
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.database import db
from bot.mexc_client import MexcClient
from bot.scalping.whale_scanner import whale_scan
from bot.scalping.whale_monitor import whale_monitor
from bot.scalping.executor import execute_trade

logger = logging.getLogger(__name__)

_MIN_TRADE_SIZE = 5.0
_MAX_TRADE_SIZE = 10_000.0


# ── Keyboards ──────────────────────────────────────────────────────────────────

def whale_menu_kb(enabled: bool) -> InlineKeyboardMarkup:
    toggle = "🔴 إيقاف Whale Strategy" if enabled else "🟢 تشغيل Whale Strategy"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle, callback_data="whale:toggle")],
        [InlineKeyboardButton("📊 الصفقات المفتوحة", callback_data="whale:open_trades")],
        [InlineKeyboardButton("◀️ القائمة الرئيسية", callback_data="menu:main")],
    ])


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_settings(user_id: int) -> dict:
    s = await db.get_settings(user_id) or {}
    return {
        "enabled":         bool(s.get("whale_enabled", 0)),
        "trade_size":      float(s.get("whale_trade_size", 10.0)),
        "mexc_api_key":    s.get("mexc_api_key", ""),
        "mexc_secret_key": s.get("mexc_secret_key", ""),
    }


def _status_text(s: dict, open_count: int) -> str:
    status = "🟢 يعمل" if s["enabled"] else "🔴 متوقف"
    return (
        "🐋 *Whale Order Flow*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"  الحالة: {status}\n"
        f"  حجم الصفقة: `${s['trade_size']:.0f}`\n"
        f"  صفقات مفتوحة: *{open_count}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *الاستراتيجية:*\n"
        "  ◈ FVG — فجوة السعر (تجميع الحيتان)\n"
        "  ◈ CVD Shift — تحول ضغط الشراء\n"
        "  ◈ 5M Breakout — كسر أعلى 3 شمعات\n"
        "  ◈ T1: +0.5% · T2: +1.0% · SL: -0.4%\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Handlers ───────────────────────────────────────────────────────────────────

async def whale_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    s = await _get_settings(user_id)
    await query.edit_message_text(
        _status_text(s, len(whale_monitor.open_symbols_for(user_id))),
        parse_mode="Markdown",
        reply_markup=whale_menu_kb(s["enabled"]),
    )


async def whale_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    s = await _get_settings(user_id)

    if not s["mexc_api_key"]:
        await query.answer("❌ يجب ربط MEXC API أولاً من الإعدادات", show_alert=True)
        return

    new_state = 0 if s["enabled"] else 1
    await db.update_settings(user_id, whale_enabled=new_state)
    s["enabled"] = bool(new_state)

    action = "تشغيل" if new_state else "إيقاف"
    await query.answer(f"✅ تم {action} Whale Strategy")
    await query.edit_message_text(
        _status_text(s, len(whale_monitor.open_symbols_for(user_id))),
        parse_mode="Markdown",
        reply_markup=whale_menu_kb(s["enabled"]),
    )


async def whale_open_trades_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    trades = {
        sym: t for sym, t in whale_monitor.open_trades.items()
        if t.get("user_id") == user_id
    }
    if not trades:
        await query.edit_message_text(
            "📊 *Whale — الصفقات المفتوحة*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "لا توجد صفقات مفتوحة حالياً.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ رجوع", callback_data="whale:menu")]
            ]),
        )
        return

    text = "📊 *Whale — الصفقات المفتوحة*\n\n━━━━━━━━━━━━━━━━━━━━━\n"
    for sym, t in trades.items():
        t1 = "✅" if t["t1_hit"] else "⏳"
        text += (
            f"◈ *{sym}*\n"
            f"   دخول: `${t['entry_price']:.6g}`\n"
            f"   T1: `${t['target1']:.6g}` {t1}  ·  T2: `${t['target2']:.6g}`\n"
            f"   وقف: `${t['stop_loss']:.6g}`\n\n"
        )
    text += "━━━━━━━━━━━━━━━━━━━━━"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ رجوع", callback_data="whale:menu")]
        ]),
    )


# ── Scanner job (every 5 min) ──────────────────────────────────────────────────

async def run_whale_scan(app) -> None:
    try:
        users = await db.get_all_users_with_whale()
    except Exception as e:
        logger.error(f"WhaleScan: failed to fetch users: {e}")
        return

    for row in users:
        user_id = row["user_id"]
        client  = None
        try:
            settings = await db.get_settings(user_id)
            if not settings or not settings.get("mexc_api_key"):
                continue

            trade_size = float(settings.get("whale_trade_size", 10.0))
            client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])

            # Balance check
            try:
                _, usdt_balance = await asyncio.wait_for(
                    client.get_portfolio(), timeout=15
                )
            except Exception as e:
                logger.warning(f"WhaleScan: balance check failed user {user_id}: {e}")
                continue

            if usdt_balance < trade_size:
                logger.warning(
                    f"WhaleScan: low balance for user {user_id} — "
                    f"${usdt_balance:.2f} < ${trade_size:.0f}, scanning anyway"
                )

            # Run scan — only pass this user's open symbols to avoid blocking
            # symbols that belong to other users
            all_open = whale_monitor.open_symbols_for(user_id)
            try:
                setups = await asyncio.wait_for(
                    whale_scan(client.exchange, all_open, trade_size),
                    timeout=90,
                )
            except asyncio.TimeoutError:
                logger.warning(f"WhaleScan: timed out for user {user_id}")
                continue

            if not setups:
                logger.info(f"WhaleScan: no setups for user {user_id}")
                continue

            # Refresh balance before executing
            try:
                _, usdt_balance = await asyncio.wait_for(
                    client.get_portfolio(), timeout=15
                )
            except Exception:
                pass  # use last known balance

            for setup in setups:
                symbol = setup["symbol"]

                if usdt_balance < trade_size:
                    await app.bot.send_message(
                        user_id,
                        f"⚠️ *Whale — رصيد غير كافٍ*\n\n"
                        f"📌 العملة: `{symbol}`\n"
                        f"💰 رصيدك: `${usdt_balance:.2f} USDT`\n"
                        f"📦 المطلوب: `${trade_size:.0f} USDT`",
                        parse_mode="Markdown",
                    )
                    continue

                result = await execute_trade(setup, client.exchange)

                if result["status"] == "ok":
                    usdt_balance -= trade_size
                    await whale_monitor.add_trade(setup, result, user_id)
                    await _send_signal(app.bot, user_id, setup, executed=True)
                else:
                    reason = result.get("reason", "")
                    logger.warning(f"WhaleScan: execute failed {symbol}: {reason}")
                    await _send_signal(app.bot, user_id, setup, executed=False, fail_reason=reason)

        except Exception as e:
            logger.error(f"WhaleScan: error user {user_id}: {e}")
        finally:
            if client:
                try:
                    await client.close()
                except Exception:
                    pass


# ── Monitor job (every 30 sec) ─────────────────────────────────────────────────

async def run_whale_monitor(app) -> None:
    """Check all open whale trades against current prices.

    Derives the user list from open_trades directly — not from whale_enabled —
    so trades are monitored even if the user toggled whale off after entry.
    """
    if not whale_monitor.open_trades:
        return

    user_ids = {
        t.get("user_id")
        for t in whale_monitor.open_trades.values()
        if t.get("user_id") is not None
    }
    if not user_ids:
        return

    for user_id in user_ids:
        try:
            settings = await db.get_settings(user_id)
            if not settings or not settings.get("mexc_api_key"):
                continue
            client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
            try:
                await whale_monitor.check_all(client.exchange, app.bot, user_id)
            finally:
                await client.close()
        except Exception as e:
            logger.error(f"WhaleMonitor: error user {user_id}: {e}")


# ── Signal message ─────────────────────────────────────────────────────────────

async def _send_signal(bot, user_id: int, setup: dict,
                       executed: bool = False, fail_reason: str = "") -> None:
    sym   = setup["symbol"]
    entry = setup["entry_price"]
    t1    = setup["target1"]
    t2    = setup["target2"]
    sl    = setup["stop_loss"]
    rr    = setup["risk_reward"]

    t1_pct = ((t1 / entry) - 1) * 100
    t2_pct = ((t2 / entry) - 1) * 100
    sl_pct = ((sl / entry) - 1) * 100

    exec_line = (
        "✅ *تم تنفيذ الصفقة تلقائياً*" if executed
        else f"⚠️ *لم يُنفَّذ:* {fail_reason[:60]}" if fail_reason
        else "📋 *إشعار فرصة*"
    )

    text = (
        f"🐋 *Whale Order Flow*\n\n"
        f"📌 `{sym}`\n"
        f"⏱ FVG + CVD Shift + 5M Breakout\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 دخول  : `${entry:.6g}`\n"
        f"🎯 هدف 1 : `${t1:.6g}`  (`+{t1_pct:.2f}%`) — بيع 60%\n"
        f"🎯 هدف 2 : `${t2:.6g}`  (`+{t2_pct:.2f}%`) — بيع 40%\n"
        f"🛑 وقف   : `${sl:.6g}`  (`{sl_pct:.2f}%`)\n"
        f"📊 R/R   : `1:{rr}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💧 FVG تجميع ✅\n"
        f"📈 CVD Shift ✅\n"
        f"🕯 5M Breakout ✅\n\n"
        f"{exec_line}"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"WhaleSignal: notify failed {user_id}: {e}")
