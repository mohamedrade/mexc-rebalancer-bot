"""
Telegram handlers for the Smart Liquidity Flow scalping feature.

Provides:
  - /scalping menu with status, start/stop controls
  - Real-time signal notifications
  - Open trades overview
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.database import db
from bot.keyboards import main_menu_kb
from bot.mexc_client import MexcClient
from bot.scalping.scanner import scan
from bot.scalping.executor import execute_trade
from bot.scalping.monitor import trade_monitor

logger = logging.getLogger(__name__)

# ── Keyboards ──────────────────────────────────────────────────────────────────

def scalping_menu_kb(enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "🔴 إيقاف الـ Scalping" if enabled else "🟢 تشغيل الـ Scalping"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="scalping:toggle")],
        [InlineKeyboardButton("📊 الصفقات المفتوحة", callback_data="scalping:open_trades")],
        [InlineKeyboardButton("⚙️ إعدادات الـ Scalping", callback_data="scalping:settings")],
        [InlineKeyboardButton("◀️ القائمة الرئيسية", callback_data="menu:main")],
    ])


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_scalping_settings(user_id: int) -> dict:
    settings = await db.get_settings(user_id) or {}
    return {
        "enabled":        bool(settings.get("scalping_enabled", 0)),
        "trade_size":     float(settings.get("scalping_trade_size", 10.0)),
        "mexc_api_key":   settings.get("mexc_api_key", ""),
        "mexc_secret_key": settings.get("mexc_secret_key", ""),
    }


def _status_text(sc: dict, open_count: int) -> str:
    status = "🟢 يعمل" if sc["enabled"] else "🔴 متوقف"
    return (
        "⚡ *Smart Liquidity Flow*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"  الحالة: {status}\n"
        f"  حجم الصفقة: `${sc['trade_size']:.0f}`\n"
        f"  صفقات مفتوحة: *{open_count}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *الاستراتيجية:*\n"
        "  ◈ 4H — مناطق Liquidity\n"
        "  ◈ 1H — CVD (ضغط الشراء)\n"
        "  ◈ 30M — Liquidity Sweep\n"
        "  ◈ 15M — Engulfing (تأكيد الدخول)\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Handlers ───────────────────────────────────────────────────────────────────

async def scalping_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    sc = await _get_scalping_settings(user_id)
    open_count = len(trade_monitor.open_symbols)

    await query.edit_message_text(
        _status_text(sc, open_count),
        parse_mode="Markdown",
        reply_markup=scalping_menu_kb(sc["enabled"]),
    )


async def scalping_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    sc = await _get_scalping_settings(user_id)

    if not sc["mexc_api_key"]:
        await query.answer("❌ يجب ربط MEXC API أولاً من الإعدادات", show_alert=True)
        return

    new_state = 0 if sc["enabled"] else 1
    await db.update_settings(user_id, scalping_enabled=new_state)

    sc["enabled"] = bool(new_state)
    open_count = len(trade_monitor.open_symbols)

    action = "تشغيل" if new_state else "إيقاف"
    await query.answer(f"✅ تم {action} الـ Scalping")

    await query.edit_message_text(
        _status_text(sc, open_count),
        parse_mode="Markdown",
        reply_markup=scalping_menu_kb(sc["enabled"]),
    )


async def scalping_open_trades_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    trades = trade_monitor.open_trades
    if not trades:
        await query.edit_message_text(
            "📊 *الصفقات المفتوحة*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "لا توجد صفقات مفتوحة حالياً.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ رجوع", callback_data="scalping:menu")]
            ]),
        )
        return

    text = "📊 *الصفقات المفتوحة*\n\n━━━━━━━━━━━━━━━━━━━━━\n"
    for sym, t in trades.items():
        t1_status = "✅" if t["t1_hit"] else "⏳"
        be_status  = " 🔒 Breakeven" if t["breakeven"] else ""
        text += (
            f"◈ *{sym}*{be_status}\n"
            f"   دخول: `${t['entry_price']:.6g}`\n"
            f"   وقف:  `${t['stop_loss']:.6g}`\n"
            f"   T1: `${t['target1']:.6g}` {t1_status}  ·  T2: `${t['target2']:.6g}`\n\n"
        )
    text += "━━━━━━━━━━━━━━━━━━━━━"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ رجوع", callback_data="scalping:menu")]
        ]),
    )


async def scalping_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sc = await _get_scalping_settings(user_id)

    await query.edit_message_text(
        "⚙️ *إعدادات الـ Scalping*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"  حجم الصفقة الحالي: `${sc['trade_size']:.0f}`\n\n"
        "لتغيير حجم الصفقة أرسل:\n"
        "`/scalping_size 20`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ رجوع", callback_data="scalping:menu")]
        ]),
    )


# ── Scanner job (called by scheduler every 15 min) ─────────────────────────────

async def run_scalping_scan(app) -> None:
    """
    Fetches all users with scalping enabled, runs the scanner for each,
    and executes valid setups.
    """
    try:
        users = await db.get_all_users_with_scalping()
    except Exception as e:
        logger.error(f"Scalping scan: failed to fetch users: {e}")
        return

    for row in users:
        user_id = row["user_id"]
        client = None
        try:
            settings = await db.get_settings(user_id)
            if not settings or not settings.get("mexc_api_key"):
                continue

            trade_size = float(settings.get("scalping_trade_size", 10.0))
            client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])

            try:
                setups = await asyncio.wait_for(
                    scan(client.exchange, trade_monitor.open_symbols, trade_size),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Scalping scan timed out for user {user_id}")
                continue

            for setup in setups:
                result = await execute_trade(setup, client.exchange)

                if result["status"] == "ok":
                    await trade_monitor.add_trade(setup, result, user_id)
                    await _send_signal(app.bot, user_id, setup)
                else:
                    logger.warning(
                        f"Scalping: execute failed {setup['symbol']}: {result['reason']}"
                    )

        except Exception as e:
            logger.error(f"Scalping scan error for user {user_id}: {e}")
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass


# ── Monitor job (called by scheduler every 60 sec) ────────────────────────────

async def run_scalping_monitor(app) -> None:
    """Check all open trades against current prices."""
    if not trade_monitor.open_trades:
        return

    try:
        users = await db.get_all_users_with_scalping()
    except Exception:
        return

    for row in users:
        user_id = row["user_id"]
        try:
            settings = await db.get_settings(user_id)
            if not settings or not settings.get("mexc_api_key"):
                continue

            client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
            try:
                await trade_monitor.check_all(client.exchange, app.bot, user_id)
            finally:
                await client.close()

        except Exception as e:
            logger.error(f"Scalping monitor error for user {user_id}: {e}")


# ── Signal message ─────────────────────────────────────────────────────────────

async def _send_signal(bot, user_id: int, setup: dict) -> None:
    sym = setup["symbol"]
    rr  = setup["risk_reward"]
    text = (
        f"🎯 *Smart Liquidity Flow*\n\n"
        f"📌 `{sym}`\n"
        f"⏱ التقاطع: 4H + 1H + 30M + 15M\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 دخول  : `${setup['entry_price']:.6g}`\n"
        f"🎯 هدف 1 : `${setup['target1']:.6g}`  (+0.5%)\n"
        f"🎯 هدف 2 : `${setup['target2']:.6g}`\n"
        f"🛑 وقف   : `${setup['stop_loss']:.6g}`  (-0.3%)\n"
        f"📊 R/R   : `1:{rr}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💧 Liquidity Sweep ✅\n"
        f"📈 CVD صاعد ✅\n"
        f"🕯 Engulfing 15M ✅"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Signal notify failed for {user_id}: {e}")
