"""
Database layer supporting both PostgreSQL (persistent, for production) and
SQLite (local fallback). Set DATABASE_URL env var to use PostgreSQL.
"""

import asyncio
import logging
import re
from bot.config import config

logger = logging.getLogger(__name__)

# ── Backend detection ──────────────────────────────────────────────────────────

_USE_PG = bool(config.database_url)

if _USE_PG:
    import asyncpg
else:
    import aiosqlite


# ── PostgreSQL pool wrapper ────────────────────────────────────────────────────

def _pg(sql: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL $1, $2, … style."""
    counter = 0

    def _replace(_):
        nonlocal counter
        counter += 1
        return f"${counter}"

    return re.sub(r"\?", _replace, sql)


class _PGConn:
    """Thin context-manager that borrows a connection from the pool."""

    def __init__(self, pool):
        self._pool = pool
        self._conn = None

    async def __aenter__(self):
        self._conn = await self._pool.acquire()
        return self

    async def __aexit__(self, *_):
        await self._pool.release(self._conn)

    async def execute(self, sql: str, *args):
        return await self._conn.execute(sql, *args)

    async def fetchall(self, sql: str, *args) -> list:
        rows = await self._conn.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def fetchone(self, sql: str, *args) -> dict | None:
        row = await self._conn.fetchrow(sql, *args)
        return dict(row) if row else None

    async def fetchval(self, sql: str, *args):
        return await self._conn.fetchval(sql, *args)

    async def commit(self):
        pass  # asyncpg auto-commits outside explicit transactions


# ── SQLite connection wrapper ──────────────────────────────────────────────────

class _SQLiteConn:
    def __init__(self, path: str):
        self._path = path
        self._conn = None

    async def __aenter__(self):
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        return self

    async def __aexit__(self, *_):
        await self._conn.close()

    async def execute(self, sql: str, *args):
        params = args[0] if args and isinstance(args[0], (list, tuple)) else args
        return await self._conn.execute(sql, params)

    async def fetchall(self, sql: str, *args) -> list:
        params = args[0] if args and isinstance(args[0], (list, tuple)) else args
        async with self._conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def fetchone(self, sql: str, *args) -> dict | None:
        params = args[0] if args and isinstance(args[0], (list, tuple)) else args
        async with self._conn.execute(sql, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetchval(self, sql: str, *args):
        row = await self.fetchone(sql, *args)
        if row:
            return next(iter(row.values()))
        return None

    async def commit(self):
        await self._conn.commit()


# ── Database class ─────────────────────────────────────────────────────────────

class Database:
    def __init__(self):
        self._path = config.database_path
        self._lock = asyncio.Lock()
        self._pool = None  # PostgreSQL only

    def _conn(self):
        if _USE_PG:
            return _PGConn(self._pool)
        return _SQLiteConn(self._path)

    # ── Init / migrations ──────────────────────────────────────────────────────

    async def init(self):
        if _USE_PG:
            dsn = config.database_url
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql://", 1)
            self._pool = await asyncpg.create_pool(
                dsn, min_size=1, max_size=5,
                statement_cache_size=0,  # required for pgbouncer/Supabase pooler
            )
            logger.info("Connected to PostgreSQL")
            await self._init_pg()
        else:
            logger.info("Using SQLite at %s", self._path)
            await self._init_sqlite()

    async def _init_pg(self):
        async with self._conn() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT PRIMARY KEY,
                    mexc_api_key TEXT,
                    mexc_secret_key TEXT,
                    threshold REAL DEFAULT 5.0,
                    auto_enabled INTEGER DEFAULT 0,
                    auto_interval_hours INTEGER DEFAULT 24,
                    quote_currency TEXT DEFAULT 'USDT',
                    last_rebalance_at TEXT,
                    active_portfolio_id INTEGER
                )""")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolios (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    capital_usdt REAL DEFAULT 0.0,
                    created_at TEXT DEFAULT (NOW()::TEXT)
                )""")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS allocations (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    portfolio_id INTEGER,
                    symbol TEXT,
                    target_percentage REAL,
                    UNIQUE(portfolio_id, symbol)
                )""")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rebalance_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    portfolio_id INTEGER,
                    timestamp TEXT,
                    summary TEXT,
                    total_traded_usdt REAL,
                    success INTEGER DEFAULT 1
                )""")
            # Safe migrations
            for sql in [
                "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS active_portfolio_id INTEGER",
                "ALTER TABLE allocations ADD COLUMN IF NOT EXISTS portfolio_id INTEGER",
                "ALTER TABLE rebalance_history ADD COLUMN IF NOT EXISTS portfolio_id INTEGER",
            ]:
                try:
                    await conn.execute(sql)
                except Exception:
                    pass

    async def _init_sqlite(self):
        async with self._conn() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    mexc_api_key TEXT,
                    mexc_secret_key TEXT,
                    threshold REAL DEFAULT 5.0,
                    auto_enabled INTEGER DEFAULT 0,
                    auto_interval_hours INTEGER DEFAULT 24,
                    quote_currency TEXT DEFAULT 'USDT',
                    last_rebalance_at TEXT,
                    active_portfolio_id INTEGER
                )""")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    capital_usdt REAL DEFAULT 0.0,
                    created_at TEXT DEFAULT (datetime('now'))
                )""")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    portfolio_id INTEGER,
                    symbol TEXT,
                    target_percentage REAL,
                    UNIQUE(portfolio_id, symbol)
                )""")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rebalance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    portfolio_id INTEGER,
                    timestamp TEXT,
                    summary TEXT,
                    total_traded_usdt REAL,
                    success INTEGER DEFAULT 1
                )""")
            await conn.commit()
            for sql in [
                "ALTER TABLE user_settings ADD COLUMN active_portfolio_id INTEGER",
                "ALTER TABLE allocations ADD COLUMN portfolio_id INTEGER",
                "ALTER TABLE rebalance_history ADD COLUMN portfolio_id INTEGER",
            ]:
                try:
                    await conn.execute(sql)
                    await conn.commit()
                except Exception:
                    pass

    # ── Portfolio CRUD ─────────────────────────────────────────────────────────

    async def create_portfolio(self, user_id: int, name: str, capital_usdt: float = 0.0) -> int:
        async with self._conn() as conn:
            if _USE_PG:
                return await conn.fetchval(
                    "INSERT INTO portfolios(user_id, name, capital_usdt) VALUES($1,$2,$3) RETURNING id",
                    user_id, name, capital_usdt,
                )
            else:
                cur = await conn.execute(
                    "INSERT INTO portfolios(user_id, name, capital_usdt) VALUES(?,?,?)",
                    (user_id, name, capital_usdt),
                )
                await conn.commit()
                return cur.lastrowid

    async def get_portfolios(self, user_id: int) -> list:
        async with self._conn() as conn:
            if _USE_PG:
                return await conn.fetchall(
                    "SELECT * FROM portfolios WHERE user_id=$1 ORDER BY id", user_id)
            return await conn.fetchall(
                "SELECT * FROM portfolios WHERE user_id=? ORDER BY id", (user_id,))

    async def get_portfolio(self, portfolio_id: int) -> dict:
        async with self._conn() as conn:
            if _USE_PG:
                row = await conn.fetchone("SELECT * FROM portfolios WHERE id=$1", portfolio_id)
            else:
                row = await conn.fetchone("SELECT * FROM portfolios WHERE id=?", (portfolio_id,))
            return row or {}

    async def update_portfolio(self, portfolio_id: int, **kwargs):
        # Allowlist of columns that can be updated to prevent SQL injection
        _ALLOWED_PORTFOLIO_COLS = {"name", "capital_usdt"}
        for k in kwargs:
            if k not in _ALLOWED_PORTFOLIO_COLS:
                raise ValueError(f"Column not allowed: {k}")

        async with self._conn() as conn:
            for k, v in kwargs.items():
                if _USE_PG:
                    await conn.execute(f"UPDATE portfolios SET {k}=$1 WHERE id=$2", v, portfolio_id)
                else:
                    await conn.execute(f"UPDATE portfolios SET {k}=? WHERE id=?", (v, portfolio_id))
            await conn.commit()

    async def delete_portfolio(self, portfolio_id: int):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute("DELETE FROM allocations WHERE portfolio_id=$1", portfolio_id)
                await conn.execute("DELETE FROM portfolios WHERE id=$1", portfolio_id)
            else:
                await conn.execute("DELETE FROM allocations WHERE portfolio_id=?", (portfolio_id,))
                await conn.execute("DELETE FROM portfolios WHERE id=?", (portfolio_id,))
                await conn.commit()

    async def get_active_portfolio_id(self, user_id: int):
        async with self._conn() as conn:
            if _USE_PG:
                row = await conn.fetchone(
                    "SELECT active_portfolio_id FROM user_settings WHERE user_id=$1", user_id)
            else:
                row = await conn.fetchone(
                    "SELECT active_portfolio_id FROM user_settings WHERE user_id=?", (user_id,))
            if row and row.get("active_portfolio_id"):
                return row["active_portfolio_id"]
            return None

    async def set_active_portfolio(self, user_id: int, portfolio_id: int):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute(
                    """INSERT INTO user_settings(user_id, active_portfolio_id) VALUES($1,$2)
                       ON CONFLICT (user_id) DO UPDATE SET active_portfolio_id=$2""",
                    user_id, portfolio_id,
                )
            else:
                await conn.execute(
                    """INSERT INTO user_settings(user_id, active_portfolio_id) VALUES(?,?)
                       ON CONFLICT(user_id) DO UPDATE SET active_portfolio_id=?""",
                    (user_id, portfolio_id, portfolio_id),
                )
                await conn.commit()

    async def ensure_active_portfolio(self, user_id: int) -> int:
        """Returns active portfolio_id, creating a default one if needed."""
        portfolio_id = await self.get_active_portfolio_id(user_id)
        if portfolio_id:
            p = await self.get_portfolio(portfolio_id)
            if p:
                return portfolio_id

        portfolios = await self.get_portfolios(user_id)
        if portfolios:
            portfolio_id = portfolios[0]["id"]
        else:
            portfolio_id = await self.create_portfolio(user_id, "المحفظة الرئيسية", 0.0)
            await self._migrate_old_allocations(user_id, portfolio_id)

        await self.set_active_portfolio(user_id, portfolio_id)
        return portfolio_id

    async def _migrate_old_allocations(self, user_id: int, portfolio_id: int):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute(
                    "UPDATE allocations SET portfolio_id=$1 WHERE user_id=$2 AND portfolio_id IS NULL",
                    portfolio_id, user_id,
                )
            else:
                await conn.execute(
                    "UPDATE allocations SET portfolio_id=? WHERE user_id=? AND portfolio_id IS NULL",
                    (portfolio_id, user_id),
                )
                await conn.commit()

    # ── Portfolio Allocations ──────────────────────────────────────────────────

    async def get_portfolio_allocations(self, portfolio_id: int) -> list:
        async with self._conn() as conn:
            if _USE_PG:
                return await conn.fetchall(
                    "SELECT * FROM allocations WHERE portfolio_id=$1 ORDER BY target_percentage DESC",
                    portfolio_id)
            return await conn.fetchall(
                "SELECT * FROM allocations WHERE portfolio_id=? ORDER BY target_percentage DESC",
                (portfolio_id,))

    async def set_portfolio_allocation(self, portfolio_id: int, user_id: int, symbol: str, pct: float):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute(
                    """INSERT INTO allocations(portfolio_id, user_id, symbol, target_percentage)
                       VALUES($1,$2,$3,$4)
                       ON CONFLICT (portfolio_id, symbol)
                       DO UPDATE SET target_percentage = EXCLUDED.target_percentage""",
                    portfolio_id, user_id, symbol.upper(), pct,
                )
            else:
                await conn.execute(
                    """INSERT INTO allocations(portfolio_id, user_id, symbol, target_percentage)
                       VALUES(?,?,?,?)
                       ON CONFLICT(portfolio_id, symbol)
                       DO UPDATE SET target_percentage=excluded.target_percentage""",
                    (portfolio_id, user_id, symbol.upper(), pct),
                )
                await conn.commit()

    async def delete_portfolio_allocation(self, portfolio_id: int, symbol: str):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute(
                    "DELETE FROM allocations WHERE portfolio_id=$1 AND symbol=$2",
                    portfolio_id, symbol)
            else:
                await conn.execute(
                    "DELETE FROM allocations WHERE portfolio_id=? AND symbol=?",
                    (portfolio_id, symbol))
                await conn.commit()

    async def clear_portfolio_allocations(self, portfolio_id: int):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute("DELETE FROM allocations WHERE portfolio_id=$1", portfolio_id)
            else:
                await conn.execute("DELETE FROM allocations WHERE portfolio_id=?", (portfolio_id,))
                await conn.commit()

    # ── Backward-compatible wrappers ───────────────────────────────────────────

    async def get_allocations(self, user_id: int) -> list:
        portfolio_id = await self.ensure_active_portfolio(user_id)
        return await self.get_portfolio_allocations(portfolio_id)

    async def set_allocation(self, user_id: int, symbol: str, pct: float):
        portfolio_id = await self.ensure_active_portfolio(user_id)
        await self.set_portfolio_allocation(portfolio_id, user_id, symbol, pct)

    async def delete_allocation(self, user_id: int, symbol: str):
        portfolio_id = await self.get_active_portfolio_id(user_id)
        if portfolio_id:
            await self.delete_portfolio_allocation(portfolio_id, symbol)

    async def clear_allocations(self, user_id: int):
        portfolio_id = await self.get_active_portfolio_id(user_id)
        if portfolio_id:
            await self.clear_portfolio_allocations(portfolio_id)

    # ── User Settings ──────────────────────────────────────────────────────────

    async def get_settings(self, user_id: int) -> dict:
        async with self._conn() as conn:
            if _USE_PG:
                row = await conn.fetchone(
                    "SELECT * FROM user_settings WHERE user_id=$1", user_id)
            else:
                row = await conn.fetchone(
                    "SELECT * FROM user_settings WHERE user_id=?", (user_id,))
            return row or {}

    async def update_settings(self, user_id: int, **kwargs):
        # Allowlist of columns that can be updated to prevent SQL injection
        _ALLOWED_SETTINGS_COLS = {
            "mexc_api_key", "mexc_secret_key", "threshold", "auto_enabled",
            "auto_interval_hours", "quote_currency", "last_rebalance_at",
            "active_portfolio_id",
        }
        for k in kwargs:
            if k not in _ALLOWED_SETTINGS_COLS:
                raise ValueError(f"Column not allowed: {k}")

        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute(
                    "INSERT INTO user_settings(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING",
                    user_id,
                )
                for k, v in kwargs.items():
                    await conn.execute(
                        f"UPDATE user_settings SET {k}=$1 WHERE user_id=$2", v, user_id)
            else:
                await conn.execute(
                    "INSERT INTO user_settings(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING",
                    (user_id,),
                )
                for k, v in kwargs.items():
                    await conn.execute(
                        f"UPDATE user_settings SET {k}=? WHERE user_id=?", (v, user_id))
                await conn.commit()

    # ── History ────────────────────────────────────────────────────────────────

    async def add_history(self, user_id: int, timestamp: str, summary: str,
                          traded: float, success: int = 1, portfolio_id: int = None):
        async with self._conn() as conn:
            if _USE_PG:
                await conn.execute(
                    """INSERT INTO rebalance_history
                       (user_id, portfolio_id, timestamp, summary, total_traded_usdt, success)
                       VALUES($1,$2,$3,$4,$5,$6)""",
                    user_id, portfolio_id, timestamp, summary, traded, success,
                )
            else:
                await conn.execute(
                    """INSERT INTO rebalance_history
                       (user_id, portfolio_id, timestamp, summary, total_traded_usdt, success)
                       VALUES(?,?,?,?,?,?)""",
                    (user_id, portfolio_id, timestamp, summary, traded, success),
                )
                await conn.commit()

    async def get_history(self, user_id: int, limit: int = 10) -> list:
        async with self._conn() as conn:
            if _USE_PG:
                return await conn.fetchall(
                    """SELECT rh.*, p.name as portfolio_name
                       FROM rebalance_history rh
                       LEFT JOIN portfolios p ON rh.portfolio_id = p.id
                       WHERE rh.user_id=$1 ORDER BY rh.id DESC LIMIT $2""",
                    user_id, limit,
                )
            return await conn.fetchall(
                """SELECT rh.*, p.name as portfolio_name
                   FROM rebalance_history rh
                   LEFT JOIN portfolios p ON rh.portfolio_id = p.id
                   WHERE rh.user_id=? ORDER BY rh.id DESC LIMIT ?""",
                (user_id, limit),
            )

    async def get_all_users_with_auto(self) -> list:
        async with self._conn() as conn:
            return await conn.fetchall(
                "SELECT user_id FROM user_settings WHERE auto_enabled=1"
            )


db = Database()
