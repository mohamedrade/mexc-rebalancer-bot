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

# PostgreSQL takes priority; fall back to SQLite for local dev
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_db_path = os.environ.get("DATABASE_PATH", "bot.db").strip()
_db_dir = os.path.dirname(_db_path)
if _db_dir and not os.path.exists(_db_dir):
    try:
        os.makedirs(_db_dir, exist_ok=True)
        print(f"[INFO] Created directory: {_db_dir}", flush=True)
    except Exception as e:
        print(f"[WARN] Could not create {_db_dir}: {e} — using bot.db", flush=True)
        _db_path = "bot.db"

DATABASE_PATH = _db_path
QUOTE_CURRENCY = os.environ.get("QUOTE_CURRENCY", "USDT").strip()


class _Config:
    TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN
    allowed_user_ids = ALLOWED_USER_IDS
    database_path = DATABASE_PATH
    database_url = DATABASE_URL
    quote_currency = QUOTE_CURRENCY


config = _Config()

if DATABASE_URL:
    print(f"[INFO] Config loaded. DB: PostgreSQL | Users: {ALLOWED_USER_IDS}", flush=True)
else:
    print(f"[INFO] Config loaded. DB: {DATABASE_PATH} (SQLite) | Users: {ALLOWED_USER_IDS}", flush=True)
