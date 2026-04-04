from telegram import Update
from telegram.ext import ContextTypes
from bot.database import db
from bot.keyboards import main_menu_kb

async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    history = await db.get_history(user_id, limit=10)

    if not history:
        await query.edit_message_text(
            "📜 *سجل إعادة التوازن*\n\nلا يوجد سجل بعد.",
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )
        return

    text = "📜 *آخر 10 عمليات توازن:*\n\n"
    for h in history:
        icon = "✅" if h["success"] else "⚠️"
        portfolio_line = f"   📁 {h['portfolio_name']}\n" if h.get("portfolio_name") else ""
        text += (
            f"{icon} `{h['timestamp']}`\n"
            f"{portfolio_line}"
            f"   {h['summary']}\n"
            f"   💵 ${h['total_traded_usdt']:.2f}\n\n"
        )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
