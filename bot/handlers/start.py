from telegram import Update
from telegram.ext import ContextTypes
from bot.config import config
from bot.keyboards import main_menu_kb, settings_kb
from bot.database import db


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if config.allowed_user_ids and user.id not in config.allowed_user_ids:
        await update.message.reply_text("⛔ غير مصرح لك باستخدام هذا البوت.")
        return

    await update.message.reply_text(
        f"✨ *أهلاً {user.first_name}!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *بوت إعادة توازن محفظة MEXC*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 *ما يقدر يعمله البوت:*\n"
        "  ◈ مراقبة محفظتك في الوقت الفعلي\n"
        "  ◈ إعادة توازن تلقائية ويدوية\n"
        "  ◈ إدارة محافظ متعددة برأس مال مستقل\n"
        "  ◈ دعم حتى 20 عملة لكل محفظة\n"
        "  ◈ حد انحراف مخصص لكل محفظة\n\n"
        "⚙️ *للبدء:* اربط مفاتيح MEXC API من الإعدادات.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *دليل الاستخدام*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "➕ *إضافة العملات*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل الرموز هكذا: `BTC ETH SOL USDT`\n"
        "ثم اختر طريقة التوزيع:\n"
        "  ⚖️ *متساوٍ* — 100% ÷ عدد العملات\n"
        "  📈 *حسب السوق* — بناءً على حجم التداول\n"
        "  ✏️ *يدوي* — تحدد النسبة بنفسك\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *أو أرسل مباشرة بالنسب:*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "`BTC=40`\n`ETH=30`\n`SOL=20`\n`USDT=10`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🗂 *المحافظ المتعددة*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "من زر 🗂 محافظي أنشئ محافظ منفصلة\n"
        "لكل محفظة رأس مال وتوزيع مستقل\n\n"
        "✖️ `/cancel` — إلغاء أي عملية جارية",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 *القائمة الرئيسية*\n\nاختر ما تريد:",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏠 *القائمة الرئيسية*\n\nاختر ما تريد:",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )
