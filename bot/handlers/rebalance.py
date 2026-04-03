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
    action = query.data.split(":", 1)[1]
    user_id = update.effective_user.id

    if action == "check":
        await query.edit_message_text("⏳ جاري تحليل المحفظة...")
        settings = await db.get_settings(user_id)
        if not settings or not settings.get("mexc_api_key"):
            await query.edit_message_text(
                "❌ يجب ربط مفاتيح MEXC API أولاً.", reply_markup=main_menu_kb()
            )
            return

        allocations = await db.get_allocations(user_id)
        if not allocations:
            await query.edit_message_text(
                "❌ لم تحدد أي عملات بعد.\nاذهب إلى ⚙️ الإعدادات ← إضافة العملات.",
                reply_markup=main_menu_kb()
            )
            return

        client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
        try:
            portfolio, total_usdt = await client.get_portfolio()
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}", reply_markup=main_menu_kb())
            return
        finally:
            await client.close()

        threshold = settings.get("threshold", 5.0)
        trades, drift_report = calculate_trades(portfolio, total_usdt, allocations, threshold)

        # Store in context for execution
        context.user_data["_pending_trades"] = trades
        context.user_data["_pending_portfolio"] = portfolio
        context.user_data["_pending_total"] = total_usdt

        text = f"⚖️ *تحليل إعادة التوازن*\n💰 إجمالي: ${total_usdt:,.2f}\n🎯 حد الانحراف: {threshold}%\n\n"
        text += "📊 *تقرير الانحراف:*\n"

        for d in drift_report:
            arrow = "🔴" if d["drift_pct"] > 0 else "🟢"
            action_flag = " ← تحتاج توازن" if d["needs_action"] else ""
            text += (
                f"{arrow} `{d['symbol']:6}` "
                f"الحالي:{d['current_pct']:.1f}% | الهدف:{d['target_pct']:.1f}% | "
                f"الفرق:{d['drift_pct']:+.1f}%{action_flag}\n"
            )

        if not trades:
            text += "\n✅ *المحفظة متوازنة — لا حاجة لأي إجراء*"
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
            return

        text += f"\n💡 *الصفقات المطلوبة ({len(trades)}):*\n"
        total_trade = 0
        for t in trades:
            emoji = "🔴 بيع" if t["action"] == "sell" else "🟢 شراء"
            text += f"{emoji} {t['symbol']}: ${t['usdt_amount']:.2f}\n"
            total_trade += t["usdt_amount"]
        text += f"\n💵 إجمالي التداول: ${total_trade:.2f}"

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
            await query.edit_message_text(f"❌ خطأ أثناء التنفيذ: {str(e)[:100]}", reply_markup=main_menu_kb())
            return
        finally:
            await client.close()

        ok = [r for r in results if r.get("status") == "ok"]
        err = [r for r in results if r.get("status") == "error"]
        skip = [r for r in results if r.get("status") == "skip"]
        total_traded = sum(t["usdt_amount"] for t in trades if any(r["symbol"] == t["symbol"] and r.get("status") == "ok" for r in results))

        text = "✅ *اكتملت إعادة التوازن*\n\n"
        for r in ok:
            a = "🔴 بيع" if r["action"] == "sell" else "🟢 شراء"
            text += f"{a} {r['symbol']}: ${r.get('usdt', 0):.2f} ✅\n"
        for r in err:
            text += f"❌ {r['symbol']}: {r.get('reason', 'خطأ')[:50]}\n"
        for r in skip:
            text += f"⏭ {r['symbol']}: {r.get('reason', 'تم التخطي')}\n"

        text += f"\n📊 ناجح: {len(ok)} | خطأ: {len(err)} | تخطي: {len(skip)}"
        text += f"\n💵 إجمالي: ${total_traded:.2f}"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = f"يدوي: {len(ok)} ناجح، {len(err)} خطأ"
        await db.add_history(user_id, now, summary, total_traded, 1 if not err else 0)

        context.user_data.pop("_pending_trades", None)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
