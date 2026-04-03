from telegram import Update
from telegram.ext import ContextTypes
from bot.database import db
from bot.keyboards import main_menu_kb, settings_kb


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1] if ":" in query.data else "main"
    user_id = update.effective_user.id

    if action == "main":
        await query.edit_message_text(
            "🏠 *القائمة الرئيسية*\n\nاختر ما تريد:",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

    elif action == "settings":
        settings = await db.get_settings(user_id)
        auto_on = bool(settings.get("auto_enabled")) if settings else False
        has_api = bool(settings.get("mexc_api_key")) if settings else False
        threshold = settings.get("threshold", 5.0) if settings else 5.0
        interval = settings.get("auto_interval_hours", 24) if settings else 24
        allocs = await db.get_allocations(user_id)

        # Show active portfolio name
        portfolio_id = await db.get_active_portfolio_id(user_id)
        portfolio_name = ""
        if portfolio_id:
            p = await db.get_portfolio(portfolio_id)
            if p:
                portfolio_name = f"\n📁 المحفظة النشطة: *{p['name']}*"

        text = (
            f"⚙️ *الإعدادات*{portfolio_name}\n\n"
            f"{'✅ API مربوطة' if has_api else '❌ API غير مربوطة'}\n"
            f"{'📊 ' + str(len(allocs)) + ' عملة محددة' if allocs else '📊 لا يوجد توزيع'}\n"
            f"🎯 حد الانحراف: *{threshold}%*\n"
            f"{'🟢 تلقائي كل ' + str(interval) + ' ساعة' if auto_on else '🔴 التوازن التلقائي معطل'}\n"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=settings_kb(auto_on)
        )

    elif action == "info":
        await query.edit_message_text(
            "ℹ️ *كيف يعمل البوت*\n\n"
            "1️⃣ *ربط API:* اذهب إلى الإعدادات وأدخل مفاتيح MEXC API\n\n"
            "2️⃣ *إنشاء محفظة:* من 📁 محافظي أنشئ محفظة وحدد رأس مالها\n\n"
            "3️⃣ *إضافة عملات:* من الإعدادات أضف العملات بنسبها\n\n"
            "4️⃣ *إعادة التوازن:* البوت يقارن التوزيع الحالي بالمستهدف\n"
            "   وينفذ الصفقات اللازمة لإعادة التوازن\n\n"
            "5️⃣ *التلقائي:* فعّل التوازن التلقائي وحدد الفترة الزمنية\n\n"
            "📁 *نظام المحافظ:*\n"
            "يمكنك إنشاء محافظ متعددة بميزانيات منفصلة\n"
            "كل محفظة لها عملاتها ونسبها المستقلة",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
