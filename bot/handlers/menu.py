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

        portfolio_id = await db.get_active_portfolio_id(user_id)
        portfolio_name = ""
        if portfolio_id:
            p = await db.get_portfolio(portfolio_id)
            if p:
                portfolio_name = f"\n🗂 المحفظة النشطة: *{p['name']}*"

        api_status = "✅ API مربوطة" if has_api else "❌ API غير مربوطة"
        alloc_status = f"📊 {len(allocs)} عملة محددة" if allocs else "📊 لا يوجد توزيع بعد"
        auto_status = f"🟢 تلقائي كل {interval} ساعة" if auto_on else "🔴 التوازن التلقائي معطل"

        text = (
            f"🛠 *الإعدادات*{portfolio_name}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"  {api_status}\n"
            f"  {alloc_status}\n"
            f"  🎯 حد الانحراف: *{threshold}%*\n"
            f"  {auto_status}\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=settings_kb(auto_on)
        )

    elif action == "info":
        await query.edit_message_text(
            "💡 *كيف يعمل البوت*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣  *ربط API*\n"
            "     اذهب إلى الإعدادات وأدخل مفاتيح MEXC API\n\n"
            "2️⃣  *إنشاء محفظة*\n"
            "     من 🗂 محافظي أنشئ محفظة وحدد رأس مالها\n\n"
            "3️⃣  *إضافة عملات*\n"
            "     من الإعدادات أضف العملات بنسبها المستهدفة\n\n"
            "4️⃣  *إعادة التوازن*\n"
            "     البوت يقارن التوزيع الحالي بالمستهدف\n"
            "     وينفذ الصفقات اللازمة تلقائياً\n\n"
            "5️⃣  *التوازن التلقائي*\n"
            "     فعّله وحدد الفترة الزمنية المناسبة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🗂 *نظام المحافظ المتعددة*\n\n"
            "يمكنك إنشاء محافظ متعددة بميزانيات منفصلة\n"
            "لكل محفظة عملاتها ونسبها المستقلة تماماً",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
