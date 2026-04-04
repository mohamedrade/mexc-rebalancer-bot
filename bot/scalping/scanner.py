"""
Market scanner — runs every 15 minutes.

Scans Top 100 MEXC symbols filtered by volume and spread,
applies the full Smart Liquidity Flow confluence check,
and returns a list of valid trade setups.
"""

import logging
from typing import List, Dict, Any

from bot.scalping.liquidity import get_liquidity_zones
from bot.scalping.cvd      import get_cvd
from bot.scalping.sweep    import detect_sweep
from bot.scalping.entry    import confirm_entry
from bot.scalping.risk     import calculate_risk

logger = logging.getLogger(__name__)

MIN_VOLUME_24H = 1_000_000   # $1M minimum
MAX_SPREAD_PCT = 0.1          # 0.1% maximum


async def get_top_symbols(exchange, limit: int = 100) -> List[str]:
    """Return top symbols by 24h quote volume, filtered by spread."""
    try:
        tickers = await exchange.fetch_tickers()
        usdt_pairs = {
            sym: t for sym, t in tickers.items()
            if sym.endswith("/USDT") and t.get("quoteVolume")
        }

        # Filter by minimum volume
        filtered = {
            sym: t for sym, t in usdt_pairs.items()
            if float(t.get("quoteVolume") or 0) >= MIN_VOLUME_24H
        }

        # Filter by spread
        valid = []
        for sym, t in filtered.items():
            bid = float(t.get("bid") or 0)
            ask = float(t.get("ask") or 0)
            if bid > 0 and ask > 0:
                spread_pct = ((ask - bid) / bid) * 100
                if spread_pct <= MAX_SPREAD_PCT:
                    valid.append((sym, float(t["quoteVolume"])))

        # Sort by volume descending, take top N
        valid.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in valid[:limit]]

    except Exception as e:
        logger.error(f"Scanner: failed to fetch symbols: {e}")
        return []


async def scan(
    exchange,
    open_symbols: set,
    trade_size_usdt: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Full confluence scan across top symbols.

    Args:
        exchange:        ccxt async exchange instance (already authenticated)
        open_symbols:    set of symbols that already have an open trade
        trade_size_usdt: USDT amount per trade

    Returns:
        List of valid setups, each dict contains all info needed by executor.
    """
    symbols = await get_top_symbols(exchange)
    setups  = []

    for symbol in symbols:
        # Skip if already in a trade
        if symbol in open_symbols:
            continue

        try:
            # ── Step 1: 4H Liquidity Zone ──────────────────────────────────
            liq = await get_liquidity_zones(symbol, exchange)
            if not liq["near_zone"] or liq["side"] != "buy":
                continue

            # ── Step 2: 1H CVD ─────────────────────────────────────────────
            cvd = await get_cvd(symbol, exchange)
            if cvd["trend"] != "up":
                continue

            # ── Step 3: 30M Sweep ──────────────────────────────────────────
            sweep = await detect_sweep(symbol, exchange, liq["low"])
            if not sweep["swept"] or not sweep["recovered"]:
                continue

            # ── Step 4: 15M Engulfing ──────────────────────────────────────
            entry = await confirm_entry(symbol, exchange)
            if not entry["confirmed"]:
                continue

            # ── Step 5: Risk calculation ───────────────────────────────────
            risk = calculate_risk(
                entry_price     = entry["entry_price"],
                sweep_low       = sweep["sweep_low"],
                liquidity_high  = liq["high"],
                trade_size_usdt = trade_size_usdt,
            )
            if not risk["valid"]:
                continue

            setups.append({
                "symbol":      symbol,
                "side":        "buy",
                "entry_price": entry["entry_price"],
                "stop_loss":   risk["stop_loss"],
                "target1":     risk["target1"],
                "target2":     risk["target2"],
                "qty":         risk["qty"],
                "qty_half":    risk["qty_half"],
                "risk_reward": risk["risk_reward"],
                "cvd":         cvd["cvd"],
                "sweep_low":   sweep["sweep_low"],
                "liq_high":    liq["high"],
                "liq_low":     liq["low"],
            })

            logger.info(f"Scanner: setup found → {symbol} R/R={risk['risk_reward']}")

        except Exception as e:
            logger.debug(f"Scanner: error on {symbol}: {e}")
            continue

    return setups
