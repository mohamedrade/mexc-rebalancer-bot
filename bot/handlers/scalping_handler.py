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

_MIN_TRADE_SIZE = 5.0
_MAX_TRADE_SIZE = 10_000.0

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
        "  ◈ 4H — مناطق Liquidity (السياق)\n"
        "  ◈ CVD — ضغط الشراء الفوري\n"
        "  ◈ 15M — Liquidity Sweep\n"
        "  ◈ 5M — Engulfing (تأكيد الدخول)\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Handlers ───────────────────────────────────────────────────────────────────

async def scalping_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    sc = await _get_scalping_settings(user_id)
    open_count = len(trade_monitor.open_symbols_for(user_id))

    await query.edit_message_text(
        _status_text(sc, open_count),
        parse_mode="Markdown",
        reply_markup=scalping_menu_kb(sc["enabled"]),
    )


async def scalping_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id

    sc = await _get_scalping_settings(user_id)

    if not sc["mexc_api_key"]:
        await query.answer("❌ يجب ربط MEXC API أولاً من الإعدادات", show_alert=True)
        return

    new_state = 0 if sc["enabled"] else 1
    await db.update_settings(user_id, scalping_enabled=new_state)

    sc["enabled"] = bool(new_state)
    open_count = len(trade_monitor.open_symbols_for(user_id))

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


# ── /scalping_size command ────────────────────────────────────────────────────

async def scalping_size_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /scalping_size 20"""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        sc = await _get_scalping_settings(user_id)
        await update.message.reply_text(
            f"⚙️ حجم الصفقة الحالي: `${sc['trade_size']:.0f}`\n\n"
            f"لتغييره: `/scalping_size <المبلغ>`\n"
            f"مثال: `/scalping_size 20`\n\n"
            f"الحد الأدنى: ${_MIN_TRADE_SIZE:.0f}  ·  الحد الأقصى: ${_MAX_TRADE_SIZE:,.0f}",
            parse_mode="Markdown",
        )
        return

    try:
        size = float(args[0])
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً. مثال: `/scalping_size 20`", parse_mode="Markdown")
        return

    if size < _MIN_TRADE_SIZE or size > _MAX_TRADE_SIZE:
        await update.message.reply_text(
            f"❌ يجب أن يكون المبلغ بين ${_MIN_TRADE_SIZE:.0f} و ${_MAX_TRADE_SIZE:,.0f}",
        )
        return

    await db.update_settings(user_id, scalping_trade_size=size)
    await update.message.reply_text(
        f"✅ تم تغيير حجم الصفقة إلى `${size:.0f}` USDT",
        parse_mode="Markdown",
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

            # ── Pre-scan balance check ─────────────────────────────────────
            try:
                _, usdt_balance = await asyncio.wait_for(
                    client.get_portfolio(), timeout=15
                )
            except asyncio.TimeoutError:
                logger.warning(f"Scalping: balance check timed out for user {user_id}")
                continue
            except Exception as e:
                logger.warning(f"Scalping: balance check failed for user {user_id}: {e}")
                continue

            if usdt_balance < trade_size:
                logger.warning(
                    f"Scalping: low balance for user {user_id} — "
                    f"${usdt_balance:.2f} < ${trade_size:.0f}, scanning anyway"
                )

            # ── Scan start notification ────────────────────────────────────
            user_open_symbols = trade_monitor.open_symbols_for(user_id)
            open_count = len(user_open_symbols)
            await app.bot.send_message(
                user_id,
                f"🔍 *Scalping — جاري المسح*\n\n"
                f"💰 الرصيد: `${usdt_balance:.2f} USDT`\n"
                f"📦 حجم الصفقة: `${trade_size:.0f} USDT`\n"
                f"📊 صفقات مفتوحة: `{open_count}`\n\n"
                f"⏳ يمسح أفضل العملات بحثاً عن فرصة...",
                parse_mode="Markdown",
            )

            try:
                setups = await asyncio.wait_for(
                    scan(client.exchange, user_open_symbols, trade_size),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Scalping scan timed out for user {user_id}")
                await app.bot.send_message(
                    user_id,
                    "⚠️ *Scalping — انتهت مهلة المسح*\n\nسيحاول مجدداً في الدورة القادمة (15 دقيقة).",
                    parse_mode="Markdown",
                )
                continue

            # ── Scan result notification ───────────────────────────────────
            if not setups:
                await app.bot.send_message(
                    user_id,
                    "🔎 *Scalping — انتهى المسح*\n\n"
                    "لم تتوفر فرصة مناسبة الآن.\n"
                    "📅 المسح القادم بعد *15 دقيقة*.",
                    parse_mode="Markdown",
                )
            else:
                await app.bot.send_message(
                    user_id,
                    f"✨ *Scalping — وُجدت {len(setups)} فرصة!*\n\n"
                    f"جاري تنفيذ الصفقات...",
                    parse_mode="Markdown",
                )

            # Refresh balance before executing setups
            try:
                _, usdt_balance = await asyncio.wait_for(
                    client.get_portfolio(), timeout=15
                )
            except Exception:
                pass  # use last known balance

            for setup in setups:
                symbol = setup["symbol"]

                # Per-trade balance check — notify with symbol name
                if usdt_balance < trade_size:
                    await app.bot.send_message(
                        user_id,
                        f"⚠️ *Scalping — رصيد غير كافٍ*\n\n"
                        f"📌 العملة: `{symbol}`\n"
                        f"💰 رصيدك الحالي: `${usdt_balance:.2f} USDT`\n"
                        f"📦 حجم الصفقة المطلوب: `${trade_size:.0f} USDT`\n\n"
                        f"أضف رصيداً أو قلّل حجم الصفقة بـ `/scalping_size`",
                        parse_mode="Markdown",
                    )
                    logger.warning(
                        f"Scalping: skipping {symbol} for user {user_id} — "
                        f"balance ${usdt_balance:.2f} < trade_size ${trade_size:.0f}"
                    )
                    continue

                result = await execute_trade(setup, client.exchange)

                if result["status"] == "ok":
                    # Deduct from local balance to avoid over-trading in same scan
                    usdt_balance -= trade_size
                    await trade_monitor.add_trade(setup, result, user_id)
                    await _send_signal(app.bot, user_id, setup, executed=True)
                else:
                    reason = result.get("reason", "")
                    logger.warning(f"Scalping: execute failed {symbol}: {reason}")
                    await _send_signal(app.bot, user_id, setup, executed=False, fail_reason=reason)

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

def _translate_error(reason: str) -> str:
    """Convert common MEXC/ccxt English errors to readable Arabic."""
    r = reason.lower()
    if "insufficient" in r or "balance" in r or "not enough" in r:
        return "رصيد غير كافٍ في حسابك"
    if "minimum" in r or "min" in r or "too small" in r:
        return "المبلغ أقل من الحد الأدنى المسموح"
    if "invalid" in r and ("symbol" in r or "pair" in r):
        return "رمز العملة غير مدعوم"
    if "auth" in r or "api" in r or "key" in r or "signature" in r:
        return "خطأ في مفاتيح API — تحقق من الإعدادات"
    if "timeout" in r or "timed out" in r:
        return "انتهت المهلة — MEXC لم يستجب"
    if "rate limit" in r or "too many" in r:
        return "تجاوزت حد الطلبات — حاول لاحقاً"
    if "market" in r and "close" in r:
        return "السوق مغلق مؤقتاً"
    # Fallback: return first 60 chars as-is
    return reason[:60]


async def _send_signal(
    bot,
    user_id: int,
    setup: dict,
    executed: bool = False,
    fail_reason: str = "",
) -> None:
    sym   = setup["symbol"]
    rr    = setup["risk_reward"]
    entry = setup["entry_price"]
    t1    = setup["target1"]
    t2    = setup["target2"]
    sl    = setup["stop_loss"]

    # Calculate actual % distances from entry
    t1_pct = ((t1 / entry) - 1) * 100 if entry > 0 else 0
    t2_pct = ((t2 / entry) - 1) * 100 if entry > 0 else 0
    sl_pct = ((sl / entry) - 1) * 100 if entry > 0 else 0

    if executed:
        exec_line = "✅ *تم تنفيذ الصفقة تلقائياً*"
    elif fail_reason:
        exec_line = f"⚠️ *لم يُنفَّذ:* {_translate_error(fail_reason)}"
    else:
        exec_line = "📋 *إشعار فرصة — لم يُنفَّذ تلقائياً*"

    text = (
        f"🎯 *Smart Liquidity Flow*\n\n"
        f"📌 `{sym}`\n"
        f"⏱ التقاطع: 4H + CVD + 15M + 5M\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 دخول  : `${entry:.6g}`\n"
        f"🎯 هدف 1 : `${t1:.6g}`  (`+{t1_pct:.2f}%`)\n"
        f"🎯 هدف 2 : `${t2:.6g}`  (`+{t2_pct:.2f}%`)\n"
        f"🛑 وقف   : `${sl:.6g}`  (`{sl_pct:.2f}%`)\n"
        f"📊 R/R   : `1:{rr}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💧 Liquidity Sweep 15M ✅\n"
        f"📈 CVD صاعد ✅\n"
        f"🕯 Engulfing 5M ✅\n\n"
        f"{exec_line}"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Signal notify failed for {user_id}: {e}")
