import asyncio
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.database import db
from bot.mexc_client import MexcClient
from bot.rebalancer import calculate_trades

logger = logging.getLogger(__name__)


async def auto_rebalance_job(app):
    """Run rebalance for users whose interval has elapsed since last rebalance."""
    users = await db.get_all_users_with_auto()
    now = datetime.now(timezone.utc)

    for row in users:
        user_id = row["user_id"]
        try:
            settings = await db.get_settings(user_id)
            if not settings:
                continue

            interval_hours = int(settings.get("auto_interval_hours") or 24)
            last_str = settings.get("last_rebalance_at")

            if last_str:
                try:
                    last_dt = datetime.fromisoformat(last_str.replace(" UTC", "+00:00"))
                    if now - last_dt < timedelta(hours=interval_hours):
                        continue  # not time yet
                except Exception:
                    pass  # if parse fails, run anyway

            await _do_rebalance(app, user_id, auto=True)

        except Exception as e:
            logger.error("Auto rebalance error for %s: %s", user_id, e)


async def _do_rebalance(app, user_id: int, auto: bool = False):
    settings = await db.get_settings(user_id)
    if not settings or not settings.get("mexc_api_key"):
        return

    portfolio_id = await db.get_active_portfolio_id(user_id)
    if not portfolio_id:
        portfolio_id = await db.ensure_active_portfolio(user_id)

    allocations = await db.get_portfolio_allocations(portfolio_id)
    if not allocations:
        return

    portfolio_info = await db.get_portfolio(portfolio_id)

    client = MexcClient(settings["mexc_api_key"], settings["mexc_secret_key"])
    try:
        try:
            portfolio, total_usdt = await asyncio.wait_for(client.get_portfolio(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Auto rebalance timeout for user %s — MEXC did not respond", user_id)
            return

        threshold = settings.get("threshold", 5.0)

        # Respect capital_usdt if set, otherwise use full account balance
        capital = portfolio_info.get("capital_usdt", 0.0) if portfolio_info else 0.0
        effective_total = capital if capital > 0 else total_usdt

        trades, _ = calculate_trades(portfolio, effective_total, allocations, threshold)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Update last_rebalance_at regardless of whether trades were needed
        await db.update_settings(user_id, last_rebalance_at=now_str)

        if not trades:
            return

        results = await client.execute_rebalance(trades)
        ok  = sum(1 for r in results if r.get("status") == "ok")
        err = sum(1 for r in results if r.get("status") == "error")
        traded = sum(
            t["usdt_amount"] for t in trades
            if any(r["symbol"] == t["symbol"] and r.get("status") == "ok" for r in results)
        )

        summary = f"{'تلقائي' if auto else 'يدوي'}: {ok} ناجح، {err} خطأ"
        await db.add_history(user_id, now_str, summary, traded,
                             1 if err == 0 else 0, portfolio_id=portfolio_id)

        msg = (
            f"{'🤖 توازن تلقائي' if auto else '⚖️ إعادة التوازن'}\n\n"
            f"✅ {ok} صفقة ناجحة\n"
            + (f"❌ {err} خطأ\n" if err else "")
            + f"💵 إجمالي: ${traded:.2f}\n"
            f"🕐 {now_str}"
        )
        await app.bot.send_message(user_id, msg)
    finally:
        await client.close()


async def start_scheduler(app) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    # Check every hour; each user's own interval is respected inside the job
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
