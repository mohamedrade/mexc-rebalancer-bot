import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from bot.database import db
from bot.keyboards import main_menu_kb
from bot.mexc_client import MexcClient, PORTFOLIO_FETCH_TIMEOUT
from bot.rebalancer import calculate_trades

async def portfolio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    await query.edit_message_text("⏳ جاري جلب بيانات المحفظة...")

    settings = await db.get_settings(user_id)
    if not settings or not settings.get("mexc_api_key"):
        await query.edit_message_text(
            "❌ يجب ربط مفاتيح MEXC API أولاً.\n\nاذهب إلى ⚙️ الإعدادات.",
            reply_markup=main_menu_kb()
        )
        return

    client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
    try:
        portfolio, total_usdt = await asyncio.wait_for(client.get_portfolio(), timeout=PORTFOLIO_FETCH_TIMEOUT)
    except asyncio.TimeoutError:
        await query.edit_message_text("❌ انتهت المهلة — MEXC لم يستجب. حاول مجدداً.", reply_markup=main_menu_kb())
        return
    except Exception as e:
        await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}", reply_markup=main_menu_kb())
        return
    finally:
        await client.close()

    if not portfolio:
        await query.edit_message_text("📊 المحفظة فارغة.", reply_markup=main_menu_kb())
        return

    # Use active portfolio's capital if set, otherwise full account
    portfolio_id = await db.ensure_active_portfolio(user_id)
    portfolio_info = await db.get_portfolio(portfolio_id)
    allocations = await db.get_portfolio_allocations(portfolio_id)
    threshold = settings.get("threshold", 5.0)

    capital = portfolio_info.get("capital_usdt", 0.0) if portfolio_info else 0.0
    effective_total = capital if capital > 0 else total_usdt

    portfolio_name = portfolio_info.get("name", "") if portfolio_info else ""
    capital_line = f"💼 رأس المال المخصص: ${effective_total:,.2f}" if capital > 0 else f"🏦 إجمالي الحساب: ${total_usdt:,.2f}"

    text = f"📊 *{portfolio_name}*\n{capital_line}\n\n"
    rows = sorted(portfolio.items(), key=lambda x: x[1]["value_usdt"], reverse=True)
    alloc_map = {a["symbol"]: a["target_percentage"] for a in allocations}

    for sym, data in rows:
        pct = (data["value_usdt"] / effective_total) * 100
        target = alloc_map.get(sym)
        bars = max(1, int(pct / 5))
        bar = "█" * bars + "░" * max(0, 20 - bars)

        if target is not None:
            drift = pct - target
            status = f" ⚠️{drift:+.1f}%" if abs(drift) >= threshold else f" ✅{drift:+.1f}%"
            text += f"`{sym:6}` {bar} *{pct:.1f}%*{status}\n"
            text += f"         ${data['value_usdt']:,.1f} | هدف:{target:.1f}%\n"
        else:
            text += f"`{sym:6}` {bar} *{pct:.1f}%*\n"
            text += f"         ${data['value_usdt']:,.1f}\n"

    if allocations:
        _, drift_report = calculate_trades(portfolio, effective_total, allocations, threshold)
        needs = [d for d in drift_report if d["needs_action"]]
        text += f"\n{'⚠️ ' + str(len(needs)) + ' عملة تحتاج توازناً' if needs else '✅ المحفظة متوازنة'}"

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
