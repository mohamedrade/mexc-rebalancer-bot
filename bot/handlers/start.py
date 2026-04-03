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
        f"👋 *مرحباً {user.first_name}!*\n\n"
        "🤖 *بوت إعادة توازن محفظة MEXC*\n\n"
        "📌 *الميزات:*\n"
        "• مراقبة المحفظة في الوقت الفعلي\n"
        "• إعادة التوازن التلقائي واليدوي\n"
        "• إضافة حتى 20 عملة\n"
        "• توزيع متساوٍ أو بحسب حجم السوق\n"
        "• حد انحراف عام يطبَّق على جميع العملات\n\n"
        "⚙️ ابدأ بربط مفاتيح MEXC API من الإعدادات.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *دليل الاستخدام*\n\n"
        "*إضافة العملات:*\n"
        "أرسل رموزاً مثل: `BTC ETH SOL USDT`\n"
        "ثم اختر طريقة التوزيع:\n"
        "  ⚖️ متساوٍ — 100% ÷ عدد العملات\n"
        "  📈 حسب السوق — بناءً على حجم التداول\n"
        "  ✏️ يدوي — تحدد النسبة بنفسك\n\n"
        "*أو أرسل مباشرة بالنسب:*\n"
        "`BTC=40`\n`ETH=30`\n`SOL=20`\n`USDT=10`\n\n"
        "*حد الانحراف العام:*\n"
        "نسبة واحدة تطبَّق على جميع العملات.\n"
        "عند تجاوزها يتم التوازن تلقائياً.\n\n"
        "/cancel — إلغاء أي عملية جارية",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏠 *القائمة الرئيسية*\n\nاختر ما تريد:",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )
