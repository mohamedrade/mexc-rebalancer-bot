from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 عرض المحفظة", callback_data="portfolio:view")],
        [InlineKeyboardButton("⚖️ إعادة التوازن", callback_data="rebalance:check"),
         InlineKeyboardButton("📜 السجل", callback_data="history:view")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings:menu")],
    ])

def settings_kb(auto_on: bool = False) -> InlineKeyboardMarkup:
    auto_label = "🔴 إيقاف التلقائي" if auto_on else "🟢 تشغيل التلقائي"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 ربط MEXC API", callback_data="settings:set_api")],
        [InlineKeyboardButton("🪙 إضافة / تعديل العملات", callback_data="settings:set_alloc")],
        [InlineKeyboardButton("🎯 حد الانحراف العام", callback_data="settings:set_threshold")],
        [InlineKeyboardButton("⏰ فترة التوازن التلقائي", callback_data="settings:set_interval")],
        [InlineKeyboardButton(auto_label, callback_data="settings:toggle_auto")],
        [InlineKeyboardButton("📊 عرض التوزيع الحالي", callback_data="settings:view_allocs")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])

def allocs_list_kb(allocations: list) -> InlineKeyboardMarkup:
    rows = []
    for a in allocations:
        rows.append([InlineKeyboardButton(
            f"🗑 حذف {a['symbol']} ({a['target_percentage']:.1f}%)",
            callback_data=f"del_alloc:{a['symbol']}"
        )])
    rows.append([InlineKeyboardButton("🗑 مسح الكل", callback_data="clear_allocs")])
    rows.append([InlineKeyboardButton("🏠 رجوع", callback_data="settings:menu")])
    return InlineKeyboardMarkup(rows)

def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]])

def back_to_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings:menu")]])

def rebalance_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد التوازن", callback_data="rebalance:execute"),
         InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")],
    ])

def rebalance_dry_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تنفيذ فعلي", callback_data="rebalance:execute"),
         InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")],
    ])
