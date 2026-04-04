import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from bot.database import db
from bot.keyboards import settings_kb, allocs_list_kb, back_to_settings_kb, main_menu_kb
from bot.mexc_client import MexcClient

# ── States ─────────────────────────────────────────────────────────────────────
(SET_API_KEY, SET_SECRET_KEY,
 SET_THRESHOLD, SET_INTERVAL,
 SET_ALLOC_COINS, SET_ALLOC_MODE, SET_ALLOC_CUSTOM) = range(7)

MAX_COINS = 20


def _alloc_mode_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚖️ توزيع متساوٍ بالكامل", callback_data="alloc_mode:equal")],
        [InlineKeyboardButton("📈 حسب حجم التداول السوقي", callback_data="alloc_mode:volume")],
        [InlineKeyboardButton("✏️ أدخل النسب يدوياً", callback_data="alloc_mode:custom")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")],
    ])


def _parse_symbols(text):
    tokens = re.split(r"[\s,،\n]+", text.upper())
    return [t.strip() for t in tokens if t.strip() and t.strip().isalnum() and len(t.strip()) <= 20]


def _parse_custom(text):
    parsed, errors = [], []
    for line in text.replace(",", "\n").splitlines():
        line = line.strip().replace(":", "=").replace(" ", "=")
        if not line:
            continue
        parts = line.split("=")
        if len(parts) != 2:
            errors.append(f"❌ `{line}` — صيغة خاطئة")
            continue
        sym = parts[0].strip().upper()
        if not sym.isalnum() or len(sym) > 20:
            errors.append(f"❌ `{sym}` — رمز غير صحيح")
            continue
        try:
            pct = float(parts[1].strip().replace("%", ""))
            if not 0.1 <= pct <= 100:
                raise ValueError
        except ValueError:
            errors.append(f"❌ `{sym}` — نسبة خاطئة")
            continue
        parsed.append((sym, pct))
    return parsed, errors


async def _save_and_reply(update, user_id, alloc_dict, label, errors=None):
    existing = await db.get_allocations(user_id)
    existing_syms = {a["symbol"] for a in existing}
    for sym, pct in alloc_dict.items():
        await db.set_allocation(user_id, sym, round(pct, 2))
    all_allocs = await db.get_allocations(user_id)
    total = sum(a["target_percentage"] for a in all_allocs)
    lines = []
    for a in all_allocs:
        tag = "🆕" if a["symbol"] not in existing_syms else "✏️" if a["symbol"] in alloc_dict else "•"
        bars = max(1, int(a["target_percentage"] / 5))
        bar = "█" * bars + "░" * max(0, 20 - bars)
        lines.append(f"{tag} `{a['symbol']:6}` {bar} *{a['target_percentage']:.1f}%*")
    status = "✅ التوزيع صحيح" if abs(total - 100) < 0.5 else f"⚠️ المجموع = {total:.1f}% (يجب 100%)"
    text = (
        f"✅ *تم الحفظ — {label}*\n\n"
        f"📊 *{len(all_allocs)} عملة:*\n" + "\n".join(lines)
        + f"\n\n📌 المجموع: *{total:.1f}%*\n{status}"
    )
    if errors:
        text += f"\n\n⚠️ تجاهل {len(errors)} سطر:\n" + "\n".join(errors[:3])
    kb = main_menu_kb()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ── View Allocs ────────────────────────────────────────────────────────────────
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    action = query.data.split(":", 1)[1]
    if action == "view_allocs":
        allocs = await db.get_allocations(user_id)
        if not allocs:
            await query.edit_message_text(
                "📊 *التوزيع*\n\nلا توجد عملات بعد.", parse_mode="Markdown",
                reply_markup=back_to_settings_kb()
            )
            return
        total = sum(a["target_percentage"] for a in allocs)
        text = f"📊 *التوزيع المستهدف ({len(allocs)} عملة)*\n\n"
        for a in allocs:
            bars = max(1, int(a["target_percentage"] / 5))
            bar = "█" * bars + "░" * max(0, 20 - bars)
            text += f"`{a['symbol']:6}` {bar} *{a['target_percentage']:.1f}%*\n"
        text += f"\n📌 المجموع: *{total:.1f}%*"
        text += "\n✅ صحيح" if abs(total - 100) < 0.5 else f"\n⚠️ يجب 100%"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=allocs_list_kb(allocs))


# ── API Key ────────────────────────────────────────────────────────────────────
async def set_api_key_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *مفتاح MEXC API*\n\nأرسل *Access Key*:\n\n"
        "mexc.com ← الحساب ← API Management ← Create API\n"
        "فعّل *Spot Trade* فقط\n\n"
        "⚠️ سيتم حذف رسالتك تلقائياً\n\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return SET_API_KEY


async def set_api_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["_api_key"] = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    await update.message.reply_text(
        "🔐 *المفتاح السري*\n\nأرسل *Secret Key*:\n\n⚠️ سيتم حذف رسالتك\n\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return SET_SECRET_KEY


async def set_secret_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secret = update.message.text.strip()
    api_key = context.user_data.pop("_api_key", None)
    try:
        await update.message.delete()
    except Exception:
        pass
    if not api_key:
        await update.message.reply_text("❌ انتهت الجلسة.", reply_markup=main_menu_kb())
        return ConversationHandler.END
    msg = await update.message.reply_text("⏳ جاري التحقق...")
    client = MexcClient(api_key, secret)
    try:
        valid, reason = await client.validate_credentials()
    except Exception as e:
        valid, reason = False, str(e)[:100]
    finally:
        await client.close()
    if not valid:
        await msg.edit_text(f"❌ *فشل التحقق*\n\n{reason}", parse_mode="Markdown", reply_markup=main_menu_kb())
        return ConversationHandler.END
    await db.update_settings(update.effective_user.id, mexc_api_key=api_key, mexc_secret_key=secret)
    await msg.edit_text("✅ *تم ربط MEXC API بنجاح!*", parse_mode="Markdown", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── Threshold ──────────────────────────────────────────────────────────────────
async def set_threshold_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    settings = await db.get_settings(update.effective_user.id)
    current = settings.get("threshold", 5.0) if settings else 5.0
    await query.edit_message_text(
        f"🎯 *حد الانحراف العام*\n\nالحالي: *{current}%*\n\n"
        "هذه النسبة تطبَّق على *جميع العملات* تلقائياً.\n"
        "عند تجاوزها تبدأ إعادة التوازن.\n\n"
        "• 3% حساس | 5% موصى به ✅ | 10% متسامح\n\n"
        "أدخل رقماً بين 1 و 20:\n\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return SET_THRESHOLD


async def set_threshold_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if not 1 <= val <= 20:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً بين 1 و 20:")
        return SET_THRESHOLD
    await db.update_settings(update.effective_user.id, threshold=val)
    await update.message.reply_text(
        f"✅ *حد الانحراف العام: {val}%*\n\nيُطبَّق على جميع العملات.",
        parse_mode="Markdown", reply_markup=main_menu_kb()
    )
    return ConversationHandler.END


# ── Interval ───────────────────────────────────────────────────────────────────
async def set_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    settings = await db.get_settings(update.effective_user.id)
    current = settings.get("auto_interval_hours", 24) if settings else 24
    await query.edit_message_text(
        f"⏰ *فترة التوازن التلقائي*\n\nالحالية: *كل {current} ساعة*\n\n"
        "أدخل عدد الساعات (1-720):\n/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return SET_INTERVAL


async def set_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if not 1 <= val <= 720:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً بين 1 و 720:")
        return SET_INTERVAL
    await db.update_settings(update.effective_user.id, auto_interval_hours=val)
    await update.message.reply_text(
        f"✅ تم تعيين الفترة: *كل {val} ساعة*", parse_mode="Markdown", reply_markup=main_menu_kb()
    )
    return ConversationHandler.END


# ── Allocation Entry ────────────────────────────────────────────────────────────
async def set_alloc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    allocs = await db.get_allocations(update.effective_user.id)
    existing = ", ".join(a["symbol"] for a in allocs) if allocs else "لا يوجد"
    await query.edit_message_text(
        f"🪙 *إضافة / تعديل العملات (حتى {MAX_COINS} عملة)*\n\n"
        f"📌 الحالية: {existing}\n\n"
        "أرسل رموز العملات مفصولة بمسافة:\n"
        "`BTC ETH SOL BNB USDT`\n\n"
        "أو بالنسب مباشرة:\n"
        "`BTC=40`\n`ETH=30`\n`SOL=20`\n`USDT=10`\n\n"
        "/cancel للإلغاء",
        parse_mode="Markdown",
    )
    return SET_ALLOC_COINS


# ── Coins Input ────────────────────────────────────────────────────────────────
async def set_alloc_coins_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if "=" in text:
        parsed, errors = _parse_custom(text)
        if not parsed:
            await update.message.reply_text(
                "❌ تنسيق خاطئ.\nمثال:\n`BTC=40`\n`ETH=30`", parse_mode="Markdown")
            return SET_ALLOC_COINS
        existing = await db.get_allocations(user_id)
        existing_syms = {a["symbol"] for a in existing}
        new_syms = {s for s, _ in parsed if s not in existing_syms}
        if len(existing_syms) + len(new_syms) > MAX_COINS:
            await update.message.reply_text(f"❌ تجاوزت الحد ({MAX_COINS} عملة).")
            return SET_ALLOC_COINS
        await _save_and_reply(update, user_id, {s: p for s, p in parsed}, "يدوي", errors)
        return ConversationHandler.END

    symbols = _parse_symbols(text)
    if not symbols:
        await update.message.reply_text("❌ أرسل رموزاً مثل:\n`BTC ETH SOL USDT`", parse_mode="Markdown")
        return SET_ALLOC_COINS
    if len(symbols) > MAX_COINS:
        await update.message.reply_text(f"❌ الحد الأقصى {MAX_COINS} عملة.")
        return SET_ALLOC_COINS

    context.user_data["_coins"] = symbols
    coins_txt = " | ".join(f"`{s}`" for s in symbols)
    await update.message.reply_text(
        f"✅ *{len(symbols)} عملة:*\n{coins_txt}\n\n🔀 *اختر طريقة التوزيع:*",
        parse_mode="Markdown", reply_markup=_alloc_mode_kb()
    )
    return SET_ALLOC_MODE


# ── Mode Selection ─────────────────────────────────────────────────────────────
async def alloc_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":", 1)[1]
    symbols = context.user_data.get("_coins", [])
    user_id = update.effective_user.id

    if not symbols:
        await query.edit_message_text("❌ انتهت الجلسة.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    if mode == "equal":
        # Distribute evenly using integer arithmetic to avoid floating-point drift.
        # Each coin gets base_pct, and the remainder is added to the last coin.
        total = 10000  # work in hundredths of a percent
        base = total // len(symbols)
        remainder = total - base * len(symbols)
        alloc_dict = {}
        for i, s in enumerate(symbols):
            cents = base + (remainder if i == len(symbols) - 1 else 0)
            alloc_dict[s] = round(cents / 100, 2)
        pct = alloc_dict[symbols[0]]
        context.user_data.pop("_coins", None)
        await _save_and_reply(update, user_id, alloc_dict, f"توزيع متساوٍ ({pct}% لكل عملة)")
        return ConversationHandler.END

    elif mode == "volume":
        await query.edit_message_text("⏳ جاري جلب بيانات السوق من MEXC...")
        settings = await db.get_settings(user_id)
        if not settings or not settings.get("mexc_api_key"):
            await query.edit_message_text("❌ يجب ربط MEXC API أولاً.", reply_markup=main_menu_kb())
            return ConversationHandler.END

        client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
        try:
            quote = settings.get("quote_currency", "USDT")
            pairs = [f"{s}/{quote}" for s in symbols if s != quote]
            volumes = {s: 0.0 for s in symbols}
            if pairs:
                try:
                    tickers = await client.exchange.fetch_tickers(pairs)
                    for s in symbols:
                        if s == quote:
                            continue
                        pair = f"{s}/{quote}"
                        if pair in tickers:
                            volumes[s] = float(tickers[pair].get("quoteVolume") or 0)
                except Exception:
                    pass
            total_vol = sum(volumes.values())
            if total_vol == 0:
                pct = round(100 / len(symbols), 2)
                alloc_dict = {s: pct for s in symbols}
                alloc_dict[symbols[-1]] = round(100 - pct * (len(symbols) - 1), 2)
                label = "حجم السوق (تعذّر — تم التوزيع المتساوٍ)"
            else:
                alloc_dict = {s: round((v / total_vol) * 100, 1) for s, v in volumes.items()}
                diff = round(100 - sum(alloc_dict.values()), 1)
                alloc_dict[symbols[-1]] = round(alloc_dict[symbols[-1]] + diff, 1)
                label = "حجم التداول السوقي 24ساعة"
        finally:
            await client.close()

        context.user_data.pop("_coins", None)
        await _save_and_reply(update, user_id, alloc_dict, label)
        return ConversationHandler.END

    elif mode == "custom":
        hint = "\n".join(f"`{s}=XX`" for s in symbols)
        await query.edit_message_text(
            f"✏️ *أدخل النسبة لكل عملة*\n\n{hint}\n\n"
            "📌 المجموع يجب 100%\n\n/cancel للإلغاء",
            parse_mode="Markdown",
        )
        return SET_ALLOC_CUSTOM

    return ConversationHandler.END


# ── Custom Input ───────────────────────────────────────────────────────────────
async def set_alloc_custom_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed, errors = _parse_custom(update.message.text.strip())
    if not parsed:
        await update.message.reply_text("❌ تنسيق خاطئ.\nمثال:\n`BTC=40`\n`ETH=30`", parse_mode="Markdown")
        return SET_ALLOC_CUSTOM
    context.user_data.pop("_coins", None)
    await _save_and_reply(update, update.effective_user.id, {s: p for s, p in parsed}, "يدوي", errors)
    return ConversationHandler.END


# ── Delete/Clear ───────────────────────────────────────────────────────────────
async def del_alloc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    symbol = query.data.split(":", 1)[1]
    await db.delete_allocation(user_id, symbol)
    allocs = await db.get_allocations(user_id)
    if not allocs:
        await query.edit_message_text(f"🗑 تم حذف *{symbol}*\n\nلا توجد عملات.", parse_mode="Markdown", reply_markup=back_to_settings_kb())
    else:
        total = sum(a["target_percentage"] for a in allocs)
        lines = "\n".join(f"• *{a['symbol']}*: {a['target_percentage']:.1f}%" for a in allocs)
        await query.edit_message_text(
            f"🗑 تم حذف *{symbol}*\n\n{lines}\n\n📌 المجموع: *{total:.1f}%*",
            parse_mode="Markdown", reply_markup=allocs_list_kb(allocs)
        )


async def clear_allocs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await db.clear_allocations(update.effective_user.id)
    await query.edit_message_text("🗑 تم مسح جميع التوزيعات.", reply_markup=back_to_settings_kb())


# ── Toggle Auto ────────────────────────────────────────────────────────────────
async def toggle_auto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db.get_settings(user_id)
    new_state = 0 if settings and settings.get("auto_enabled") else 1
    await db.update_settings(user_id, auto_enabled=new_state)
    settings = await db.get_settings(user_id)
    auto_on = bool(settings.get("auto_enabled"))
    has_api = bool(settings.get("mexc_api_key"))
    threshold = settings.get("threshold", 5.0)
    interval = settings.get("auto_interval_hours", 24)
    allocs = await db.get_allocations(user_id)
    text = (
        "⚙️ *الإعدادات*\n\n"
        f"{'✅ API مربوطة' if has_api else '❌ API غير مربوطة'}\n"
        f"{'📊 ' + str(len(allocs)) + ' عملة محددة' if allocs else '📊 لا يوجد توزيع'}\n"
        f"🎯 حد الانحراف: *{threshold}%* (جميع العملات)\n"
        f"{'🟢 تلقائي كل ' + str(interval) + ' ساعة' if auto_on else '🔴 التوازن التلقائي معطل'}\n"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=settings_kb(auto_on))


# ── Cancel ─────────────────────────────────────────────────────────────────────
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "❌ تم الإلغاء."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_kb())
    return ConversationHandler.END
