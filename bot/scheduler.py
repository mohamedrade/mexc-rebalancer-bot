import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.mexc_client import MexcClient
from bot.rebalancer import calculate_trades

logger = logging.getLogger(__name__)

async def auto_rebalance_job(app):
    """Run for all users with auto_enabled=1"""
    async with app.bot:
        pass  # ensure bot is accessible

    # Get all auto-enabled users
    import aiosqlite
    from bot.config import config
    async with aiosqlite.connect(config.database_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT user_id FROM user_settings WHERE auto_enabled=1 AND mexc_api_key IS NOT NULL"
        ) as cur:
            users = [r["user_id"] for r in await cur.fetchall()]

    for user_id in users:
        try:
            await _do_rebalance(app, user_id, auto=True)
        except Exception as e:
            logger.error(f"Auto rebalance error for {user_id}: {e}")


async def _do_rebalance(app, user_id: int, auto: bool = False):
    settings = await db.get_settings(user_id)
    if not settings:
        return
    allocations = await db.get_allocations(user_id)
    if not allocations:
        return

    client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
    try:
        portfolio, total_usdt = await client.get_portfolio()
        threshold = settings.get("threshold", 5.0)
        trades, drift = calculate_trades(portfolio, total_usdt, allocations, threshold)

        if not trades:
            if auto:
                return  # No drift, nothing to do
            return

        results = await client.execute_rebalance(trades)
        traded = sum(t["usdt_amount"] for t in trades if t.get("status") != "skip")
        ok = sum(1 for r in results if r.get("status") == "ok")
        err = sum(1 for r in results if r.get("status") == "error")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = f"{'تلقائي' if auto else 'يدوي'}: {ok} ناجح، {err} خطأ"
        await db.add_history(user_id, now, summary, traded, 1 if err == 0 else 0)

        msg = (
            f"{'🤖 توازن تلقائي' if auto else '⚖️ إعادة التوازن'}\n\n"
            f"✅ {ok} صفقة ناجحة\n"
            + (f"❌ {err} خطأ\n" if err else "")
            + f"💵 إجمالي: ${traded:.2f}\n"
            f"🕐 {now}"
        )
        await app.bot.send_message(user_id, msg)
    finally:
        await client.close()


async def start_scheduler(app) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        auto_rebalance_job,
        trigger="interval",
        hours=1,
        args=[app],
        id="auto_rebalance",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")
    return scheduler
