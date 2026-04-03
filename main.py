import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)
from bot.config import config
from bot.database import db
from bot.handlers.start import start_handler, help_handler, menu_command
from bot.handlers.portfolio import portfolio_callback
from bot.handlers.rebalance import rebalance_callback
from bot.handlers.history import history_callback
from bot.handlers.menu import handle_menu_callback
from bot.handlers.settings import (
    settings_callback, toggle_auto_callback,
    set_api_key_start, set_api_key_input, set_secret_key_input,
    set_threshold_start, set_threshold_input,
    set_interval_start, set_interval_input,
    set_alloc_start, set_alloc_coins_input,
    alloc_mode_callback, set_alloc_custom_input,
    del_alloc_callback, clear_allocs_callback,
    cancel_conv,
    SET_API_KEY, SET_SECRET_KEY,
    SET_THRESHOLD, SET_INTERVAL,
    SET_ALLOC_COINS, SET_ALLOC_MODE, SET_ALLOC_CUSTOM,
)
from bot.handlers.portfolio_manager import (
    portfolios_callback, portfolio_detail_callback,
    switch_portfolio_callback, delete_portfolio_callback,
    delete_portfolio_confirm_callback,
    create_portfolio_start, create_portfolio_name, create_portfolio_capital,
    edit_portfolio_name_start, edit_portfolio_name_input,
    edit_portfolio_capital_start, edit_portfolio_capital_input,
    cancel_portfolio_conv,
    CREATE_NAME, CREATE_CAPITAL, EDIT_NAME, EDIT_CAPITAL,
)
from bot.scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    TEXT = filters.TEXT & ~filters.COMMAND

    # ── Conversations (must be registered before simple CallbackQueryHandlers) ─
    api_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_api_key_start, pattern="^settings:set_api")],
        states={
            SET_API_KEY:    [MessageHandler(TEXT, set_api_key_input)],
            SET_SECRET_KEY: [MessageHandler(TEXT, set_secret_key_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv),
                   CallbackQueryHandler(cancel_conv, pattern="^cancel$")],
        conversation_timeout=300,
    )

    threshold_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_threshold_start, pattern="^settings:set_threshold")],
        states={SET_THRESHOLD: [MessageHandler(TEXT, set_threshold_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv),
                   CallbackQueryHandler(cancel_conv, pattern="^cancel$")],
        conversation_timeout=300,
    )

    interval_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_interval_start, pattern="^settings:set_interval")],
        states={SET_INTERVAL: [MessageHandler(TEXT, set_interval_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv),
                   CallbackQueryHandler(cancel_conv, pattern="^cancel$")],
        conversation_timeout=300,
    )

    alloc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_alloc_start, pattern="^settings:add_alloc")],
        states={
            SET_ALLOC_COINS:  [MessageHandler(TEXT, set_alloc_coins_input)],
            SET_ALLOC_MODE:   [CallbackQueryHandler(alloc_mode_callback, pattern="^alloc_mode:")],
            SET_ALLOC_CUSTOM: [MessageHandler(TEXT, set_alloc_custom_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv),
                   CallbackQueryHandler(cancel_conv, pattern="^cancel$")],
        conversation_timeout=600,
    )

    create_portfolio_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_portfolio_start, pattern="^portfolio_new$")],
        states={
            CREATE_NAME:    [MessageHandler(TEXT, create_portfolio_name)],
            CREATE_CAPITAL: [MessageHandler(TEXT, create_portfolio_capital)],
        },
        fallbacks=[CommandHandler("cancel", cancel_portfolio_conv),
                   CallbackQueryHandler(cancel_portfolio_conv, pattern="^cancel$")],
        conversation_timeout=300,
    )

    edit_name_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_portfolio_name_start, pattern="^portfolio_edit_name:")],
        states={EDIT_NAME: [MessageHandler(TEXT, edit_portfolio_name_input)]},
        fallbacks=[CommandHandler("cancel", cancel_portfolio_conv),
                   CallbackQueryHandler(cancel_portfolio_conv, pattern="^cancel$")],
        conversation_timeout=300,
    )

    edit_capital_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_portfolio_capital_start, pattern="^portfolio_edit_capital:")],
        states={EDIT_CAPITAL: [MessageHandler(TEXT, edit_portfolio_capital_input)]},
        fallbacks=[CommandHandler("cancel", cancel_portfolio_conv),
                   CallbackQueryHandler(cancel_portfolio_conv, pattern="^cancel$")],
        conversation_timeout=300,
    )

    app.add_handler(api_conv)
    app.add_handler(threshold_conv)
    app.add_handler(interval_conv)
    app.add_handler(alloc_conv)
    app.add_handler(create_portfolio_conv)
    app.add_handler(edit_name_conv)
    app.add_handler(edit_capital_conv)

    # ── Commands ───────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("menu", menu_command))

    # ── Navigation ─────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_menu_callback, pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(portfolio_callback,   pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(history_callback,     pattern="^history$"))

    # ── Rebalance ──────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(rebalance_callback, pattern="^rebalance:"))

    # ── Settings ───────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(settings_callback,     pattern="^settings:view"))
    app.add_handler(CallbackQueryHandler(toggle_auto_callback,  pattern="^toggle_auto$"))
    app.add_handler(CallbackQueryHandler(del_alloc_callback,    pattern="^del_alloc:"))
    app.add_handler(CallbackQueryHandler(clear_allocs_callback, pattern="^clear_allocs"))

    # ── Portfolio Management ───────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(portfolios_callback,               pattern="^portfolios$"))
    app.add_handler(CallbackQueryHandler(portfolio_detail_callback,         pattern="^portfolio:\\d+$"))
    app.add_handler(CallbackQueryHandler(switch_portfolio_callback,         pattern="^portfolio_switch:"))
    app.add_handler(CallbackQueryHandler(delete_portfolio_callback,         pattern="^portfolio_delete:\\d+$"))
    app.add_handler(CallbackQueryHandler(delete_portfolio_confirm_callback, pattern="^portfolio_delete_confirm:"))

    return app


async def main():
    await db.init()
    app = build_app()
    scheduler = await start_scheduler(app)
    logger.info("🤖 Bot started polling...")
    async with app:
        await app.start()
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
