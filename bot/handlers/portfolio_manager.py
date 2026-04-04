import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from bot.database import db
from bot.keyboards import (
    portfolios_list_kb, portfolio_actions_kb,
    portfolio_delete_confirm_kb, main_menu_kb,
)

# Conversation states
CREATE_NAME, CREATE_CAPITAL, EDIT_NAME, EDIT_CAPITAL = range(30, 34)


async def portfolios_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    active_id = await db.ensure_active_portfolio(user_id)
    portfolios = await db.get_portfolios(user_id)

    text = "📁 *محافظك*\n\n"
    if not portfolios:
        text += "لا يوجد محافظ بعد. أنشئ محفظتك الأولى!"
    else:
        for p in portfolios:
            mark = "✅ نشطة" if p["id"] == active_id else ""
            text += f"• *{p['name']}* — ${p['capital_usdt']:,.0f} USDT {mark}\n"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=portfolios_list_kb(portfolios, active_id)
    )


async def portfolio_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    portfolio_id = int(query.data.split(":")[1])

    p = await db.get_portfolio(portfolio_id)
    if not p or p["user_id"] != user_id:
        await query.answer("❌ محفظة غير موجودة", show_alert=True)
        return

    active_id = await db.get_active_portfolio_id(user_id)
    allocs = await db.get_portfolio_allocations(portfolio_id)
    total_pct = sum(a["target_percentage"] for a in allocs)

    text = (
        f"📁 *{p['name']}*\n\n"
        f"💰 رأس المال: *${p['capital_usdt']:,.2f} USDT*\n"
        f"🪙 عدد العملات: *{len(allocs)}*\n"
        f"📊 مجموع التوزيع: *{total_pct:.1f}%*\n"
        f"{'✅ المحفظة النشطة الآن' if p['id'] == active_id else '⭕ غير نشطة'}\n"
    )
    if allocs:
        text += "\n*التوزيع:*\n"
        for a in allocs[:8]:
            text += f"• `{a['symbol']:6}` {a['target_percentage']:.1f}%\n"
        if len(allocs) > 8:
            text += f"_... و {len(allocs)-8} عملات أخرى_\n"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=portfolio_actions_kb(portfolio_id, p["id"] == active_id)
    )


async def switch_portfolio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    portfolio_id = int(query.data.split(":")[1])

    p = await db.get_portfolio(portfolio_id)
    if not p or p["user_id"] != user_id:
        await query.answer("❌ محفظة غير موجودة", show_alert=True)
        return

    await db.set_active_portfolio(user_id, portfolio_id)

    portfolios = await db.get_portfolios(user_id)
    text = f"✅ *تم تفعيل المحفظة: {p['name']}*\n\nكل العمليات ستُطبَّق على هذه المحفظة الآن.\n\n"
    text += "📁 *محافظك:*\n"
    for port in portfolios:
        mark = "✅" if port["id"] == portfolio_id else "•"
        text += f"{mark} *{port['name']}* — ${port['capital_usdt']:,.0f}\n"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=portfolios_list_kb(portfolios, portfolio_id)
    )


async def delete_portfolio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    portfolio_id = int(query.data.split(":")[1])

    p = await db.get_portfolio(portfolio_id)
    if not p or p["user_id"] != user_id:
        await query.answer("❌ محفظة غير موجودة", show_alert=True)
        return

    portfolios = await db.get_portfolios(user_id)
    if len(portfolios) <= 1:
        await query.answer("❌ لا يمكن حذف المحفظة الوحيدة", show_alert=True)
        return

    await query.edit_message_text(
        f"⚠️ *تأكيد الحذف*\n\nهل أنت متأكد من حذف محفظة *{p['name']}*؟\n"
        f"💰 رأس المال: ${p['capital_usdt']:,.0f}\n\n"
        "سيتم حذف جميع التوزيعات المرتبطة بها بشكل نهائي.",
        parse_mode="Markdown",
        reply_markup=portfolio_delete_confirm_kb(portfolio_id)
    )


async def delete_portfolio_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    portfolio_id = int(query.data.split(":")[1])

    p = await db.get_portfolio(portfolio_id)
    if not p or p["user_id"] != user_id:
        await query.answer("❌ محفظة غير موجودة", show_alert=True)
        return

    portfolios = await db.get_portfolios(user_id)
    if len(portfolios) <= 1:
        await query.answer("❌ لا يمكن حذف المحفظة الوحيدة", show_alert=True)
        return

    active_id = await db.get_active_portfolio_id(user_id)
    await db.delete_portfolio(portfolio_id)

    if active_id == portfolio_id:
        remaining = await db.get_portfolios(user_id)
        if remaining:
            await db.set_active_portfolio(user_id, remaining[0]["id"])

    remaining = await db.get_portfolios(user_id)
    new_active = await db.get_active_portfolio_id(user_id)
    text = f"✅ *تم حذف المحفظة: {p['name']}*\n\n📁 *محافظك المتبقية:*\n"
    for port in remaining:
        mark = "✅" if port["id"] == new_active else "•"
        text += f"{mark} *{port['name']}* — ${port['capital_usdt']:,.0f}\n"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=portfolios_list_kb(remaining, new_active)
    )


# ── Create Portfolio Conversation ──────────────────────────────────────────────

async def create_portfolio_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    # Try to fetch real balance from MEXC
    settings = await db.get_settings(user_id)
    real_balance = None
    if settings and settings.get("mexc_api_key"):
        await query.edit_message_text("⏳ جاري جلب رصيدك من MEXC...")
        try:
            from bot.mexc_client import MexcClient
            client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
            try:
                _, total_usdt = await asyncio.wait_for(client.get_portfolio(), timeout=15)
                real_balance = total_usdt
            finally:
                await client.close()
        except Exception:
            real_balance = None

    context.user_data["_real_balance"] = real_balance

    if real_balance is not None:
        balance_text = f"💰 رصيدك الحالي في MEXC: *${real_balance:,.2f} USDT*\n\n"
        use_full_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدام كامل الرصيد (${real_balance:,.2f})", callback_data="portfolio_capital:full")],
            [InlineKeyboardButton("✏️ تحديد مبلغ مخصص", callback_data="portfolio_capital:custom")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")],
        ])
        await query.edit_message_text(
            f"📁 *إنشاء محفظة جديدة*\n\n{balance_text}"
            "اختر رأس المال لهذه المحفظة:",
            parse_mode="Markdown",
            reply_markup=use_full_btn,
        )
    else:
        await query.edit_message_text(
            "📁 *إنشاء محفظة جديدة*\n\n"
            "⚠️ لم يتم ربط MEXC API بعد أو تعذّر جلب الرصيد.\n\n"
            "أدخل *اسم المحفظة*:\n"
            "مثال: محفظة المضاربة / محفظة طويلة المدى\n\n/cancel للإلغاء",
            parse_mode="Markdown",
        )
    return CREATE_NAME


async def create_portfolio_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle capital choice buttons (full/custom) that arrive as callback queries
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":")[1]
        real_balance = context.user_data.get("_real_balance")

        if choice == "full" and real_balance is not None:
            context.user_data["_new_portfolio_capital"] = real_balance
        # For "custom", fall through to ask for name first

        await query.edit_message_text(
            "📁 أدخل *اسم المحفظة*:\n"
            "مثال: محفظة المضاربة / محفظة طويلة المدى\n\n/cancel للإلغاء",
            parse_mode="Markdown",
        )
        return CREATE_NAME

    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("❌ الاسم يجب بين 2 و 50 حرف. أعد المحاولة:")
        return CREATE_NAME

    context.user_data["_new_portfolio_name"] = name

    # If capital already chosen (full balance), skip capital input step
    if "_new_portfolio_capital" in context.user_data:
        capital = context.user_data.pop("_new_portfolio_capital")
        user_id = update.effective_user.id
        await db.create_portfolio(user_id, name, capital)
        portfolios = await db.get_portfolios(user_id)
        active_id = await db.get_active_portfolio_id(user_id)
        await update.message.reply_text(
            f"✅ *تم إنشاء المحفظة!*\n\n📁 *{name}*\n💰 رأس المال: *${capital:,.2f} USDT*",
            parse_mode="Markdown",
            reply_markup=portfolios_list_kb(portfolios, active_id),
        )
        return ConversationHandler.END

    real_balance = context.user_data.get("_real_balance")
    balance_hint = f"\n💡 رصيدك الحالي: ${real_balance:,.2f}" if real_balance else ""
    await update.message.reply_text(
        f"✅ الاسم: *{name}*\n\n💰 أدخل *رأس المال بالـ USDT*:{balance_hint}\n"
        "مثال: `1000` أو `5000.50`\n\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return CREATE_CAPITAL


async def create_portfolio_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        capital = float(update.message.text.strip().replace(",", ""))
        if capital < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً أكبر من أو يساوي 0:")
        return CREATE_CAPITAL

    name = context.user_data.pop("_new_portfolio_name", "محفظة جديدة")
    context.user_data.pop("_real_balance", None)
    user_id = update.effective_user.id

    await db.create_portfolio(user_id, name, capital)
    portfolios = await db.get_portfolios(user_id)
    active_id = await db.get_active_portfolio_id(user_id)

    await update.message.reply_text(
        f"✅ *تم إنشاء المحفظة!*\n\n📁 *{name}*\n💰 رأس المال: *${capital:,.2f} USDT*\n\n"
        "يمكنك تفعيلها من قائمة المحافظ وإضافة عملات لها من الإعدادات.",
        parse_mode="Markdown",
        reply_markup=portfolios_list_kb(portfolios, active_id),
    )
    return ConversationHandler.END


# ── Edit Portfolio Name Conversation ───────────────────────────────────────────

async def edit_portfolio_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    portfolio_id = int(query.data.split(":")[1])
    p = await db.get_portfolio(portfolio_id)
    context.user_data["_edit_portfolio_id"] = portfolio_id
    await query.edit_message_text(
        f"✏️ *تعديل اسم المحفظة*\n\nالاسم الحالي: *{p['name']}*\n\nأدخل الاسم الجديد:\n\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return EDIT_NAME


async def edit_portfolio_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("❌ الاسم يجب بين 2 و 50 حرف:")
        return EDIT_NAME

    portfolio_id = context.user_data.pop("_edit_portfolio_id", None)
    if not portfolio_id:
        await update.message.reply_text("❌ انتهت الجلسة.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    await db.update_portfolio(portfolio_id, name=name)
    user_id = update.effective_user.id
    portfolios = await db.get_portfolios(user_id)
    active_id = await db.get_active_portfolio_id(user_id)
    await update.message.reply_text(
        f"✅ *تم تعديل الاسم إلى: {name}*",
        parse_mode="Markdown",
        reply_markup=portfolios_list_kb(portfolios, active_id),
    )
    return ConversationHandler.END


# ── Edit Portfolio Capital Conversation ────────────────────────────────────────

async def edit_portfolio_capital_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    portfolio_id = int(query.data.split(":")[1])
    p = await db.get_portfolio(portfolio_id)
    context.user_data["_edit_portfolio_id"] = portfolio_id
    await query.edit_message_text(
        f"💰 *تعديل رأس المال*\n\nالمحفظة: *{p['name']}*\n"
        f"رأس المال الحالي: *${p['capital_usdt']:,.2f} USDT*\n\n"
        "أدخل رأس المال الجديد بالـ USDT:\n\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return EDIT_CAPITAL


async def edit_portfolio_capital_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        capital = float(update.message.text.strip().replace(",", ""))
        if capital < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً:")
        return EDIT_CAPITAL

    portfolio_id = context.user_data.pop("_edit_portfolio_id", None)
    if not portfolio_id:
        await update.message.reply_text("❌ انتهت الجلسة.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    await db.update_portfolio(portfolio_id, capital_usdt=capital)
    user_id = update.effective_user.id
    portfolios = await db.get_portfolios(user_id)
    active_id = await db.get_active_portfolio_id(user_id)
    await update.message.reply_text(
        f"✅ *تم تعديل رأس المال إلى: ${capital:,.2f} USDT*",
        parse_mode="Markdown",
        reply_markup=portfolios_list_kb(portfolios, active_id),
    )
    return ConversationHandler.END


async def cancel_portfolio_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ تم الإلغاء.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_kb())
    return ConversationHandler.END
