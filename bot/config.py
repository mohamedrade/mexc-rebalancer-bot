import os
import sys

def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"[FATAL] Missing environment variable: {key}", flush=True)
        sys.exit(1)
    return val

TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [
    int(i.strip()) for i in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if i.strip().isdigit()
]
DATABASE_PATH = os.environ.get("DATABASE_PATH", "bot.db").strip()
QUOTE_CURRENCY = os.environ.get("QUOTE_CURRENCY", "USDT").strip()

# Simple namespace object for compatibility
class _Config:
    telegram_token = TELEGRAM_BOT_TOKEN
    allowed_user_ids = ALLOWED_USER_IDS
    database_path = DATABASE_PATH
    quote_currency = QUOTE_CURRENCY

config = _Config()
