import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from bot.database import db
from bot.keyboards import main_menu_kb, rebalance_confirm_kb, rebalance_dry_kb
from bot.mexc_client import MexcClient
from bot.rebalancer import calculate_trades
from datetime import datetime, timezone


async def rebalance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1] if ":" in query.data else "check"
    user_id = update.effective_user.id

    if action == "check":
        await query.edit_message_text("⏳ جاري تحليل المحفظة...")
        settings = await db.get_settings(user_id)
        if not settings or not settings.get("mexc_api_key"):
            await query.edit_message_text(
                "❌ يجب ربط مفاتيح MEXC API أولاً.", reply_markup=main_menu_kb()
            )
            return

        portfolio_id = await db.ensure_active_portfolio(user_id)
        portfolio_info = await db.get_portfolio(portfolio_id)
        allocations = await db.get_portfolio_allocations(portfolio_id)

        if not allocations:
            await query.edit_message_text(
                f"❌ لا يوجد توزيع في محفظة *{portfolio_info.get('name', '')}*.\n"
                "اذهب إلى 🛠 الإعدادات ← إضافة العملات.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
            return

        client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
        try:
            portfolio, total_usdt = await asyncio.wait_for(client.get_portfolio(), timeout=20)
        except asyncio.TimeoutError:
            await query.edit_message_text("❌ انتهت المهلة — MEXC لم يستجب. حاول مجدداً.", reply_markup=main_menu_kb())
            return
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}", reply_markup=main_menu_kb())
            return
        finally:
            await client.close()

        capital = portfolio_info.get("capital_usdt", 0.0)

        # Bug fix: never trade more than what's actually in the account.
        # If a capital budget is set but the real balance is lower, use the real balance.
        if capital > 0:
            effective_total = min(capital, total_usdt)
        else:
            effective_total = total_usdt

        # Block execution if the account is essentially empty (< $1)
        if effective_total < 1.0:
            await query.edit_message_text(
                "⚠️ *رصيد غير كافٍ*\n\n"
                f"إجمالي الحساب: `${total_usdt:.2f}`\n\n"
                "يجب أن يكون الرصيد أكبر من $1 لتنفيذ أي عملية توازن.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
            return

        # Validate allocations sum to ~100% before proceeding
        total_pct = sum(a["target_percentage"] for a in allocations)
        if abs(total_pct - 100) > 1.0:
            await query.edit_message_text(
                "⚠️ *التوزيع غير صحيح*\n\n"
                f"مجموع النسب الحالي: `{total_pct:.1f}%`\n"
                "يجب أن يكون المجموع 100% قبل تنفيذ التوازن.\n\n"
                "اذهب إلى 🛠 الإعدادات ← إضافة / تعديل عملة لتصحيح النسب.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
            return

        threshold = settings.get("threshold", 5.0)
        trades, drift_report = calculate_trades(portfolio, effective_total, allocations, threshold)

        context.user_data["_pending_trades"] = trades
        context.user_data["_pending_portfolio_id"] = portfolio_id
        context.user_data["_pending_total"] = effective_total

        portfolio_name = portfolio_info.get("name", "")
        text = (
            f"⚡ *تحليل إعادة التوازن*\n\n"
            f"🗂 المحفظة: *{portfolio_name}*\n"
            f"💰 رأس المال المخصص: `${effective_total:,.2f}`\n"
            f"🏦 إجمالي الحساب: `${total_usdt:,.2f}`\n"
            f"🎯 حد الانحراف: `{threshold}%`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *تقرير الانحراف*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
        )

        for d in drift_report:
            if d["needs_action"]:
                arrow = "🔴" if d["drift_pct"] > 0 else "🟢"
                text += (
                    f"{arrow} `{d['symbol']:6}` "
                    f"{d['current_pct']:.1f}% → {d['target_pct']:.1f}%  "
                    f"({d['drift_pct']:+.1f}%) ⚠️\n"
                )
            else:
                text += (
                    f"✅ `{d['symbol']:6}` "
                    f"{d['current_pct']:.1f}% → {d['target_pct']:.1f}%  "
                    f"({d['drift_pct']:+.1f}%)\n"
                )

        if not trades:
            text += "\n✅ *المحفظة متوازنة — لا حاجة لأي إجراء*"
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=rebalance_dry_kb())
            return

        text += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"💡 *الصفقات المطلوبة  ({len(trades)})*\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        total_trade = 0
        for t in trades:
            emoji = "🔴 بيع" if t["action"] == "sell" else "🟢 شراء"
            text += f"{emoji}  `{t['symbol']}`  ·  `${t['usdt_amount']:.2f}`\n"
            total_trade += t["usdt_amount"]
        text += f"\n💵 إجمالي التداول: `${total_trade:.2f}`"

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=rebalance_confirm_kb())

    elif action == "execute":
        trades = context.user_data.get("_pending_trades", [])
        if not trades:
            await query.edit_message_text("❌ انتهت الجلسة. أعد التحقق أولاً.", reply_markup=main_menu_kb())
            return

        await query.edit_message_text("⏳ جاري تنفيذ الصفقات...")
        settings = await db.get_settings(user_id)
        client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])

        try:
            results = await client.execute_rebalance(trades)
        except Exception as e:
            await query.edit_message_text(
                f"❌ خطأ أثناء التنفيذ: {str(e)[:100]}", reply_markup=main_menu_kb()
            )
            return
        finally:
            await client.close()

        ok   = [r for r in results if r.get("status") == "ok"]
        err  = [r for r in results if r.get("status") == "error"]
        skip = [r for r in results if r.get("status") == "skip"]
        total_traded = sum(
            t["usdt_amount"] for t in trades
            if any(r["symbol"] == t["symbol"] and r.get("status") == "ok" for r in results)
        )

        text = "✅ *اكتملت إعادة التوازن*\n\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        for r in ok:
            a = "🔴 بيع" if r["action"] == "sell" else "🟢 شراء"
            text += f"{a}  `{r['symbol']}`  ·  `${r.get('usdt', 0):.2f}`  ✅\n"
        for r in err:
            text += f"❌  `{r['symbol']}`: {r.get('reason', 'خطأ')[:50]}\n"
        for r in skip:
            text += f"⏭  `{r['symbol']}`: {r.get('reason', 'تم التخطي')}\n"

        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"📊 ناجح: *{len(ok)}*  |  خطأ: *{len(err)}*  |  تخطي: *{len(skip)}*\n"
        text += f"💵 الإجمالي: `${total_traded:.2f}`"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = f"يدوي: {len(ok)} ناجح، {len(err)} خطأ"
        portfolio_id = context.user_data.get("_pending_portfolio_id")
        await db.add_history(user_id, now, summary, total_traded, 1 if not err else 0,
                             portfolio_id=portfolio_id)

        context.user_data.pop("_pending_trades", None)
        context.user_data.pop("_pending_portfolio_id", None)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())



