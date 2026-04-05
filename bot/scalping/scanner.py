"""
Market scanner — runs every 15 minutes.

Scans top MEXC symbols filtered by volume, spread, and volatility,
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

MIN_VOLUME_24H  = 500_000   # $500K minimum 24h volume
MAX_SPREAD_PCT  = 0.2       # 0.2% maximum spread
MIN_VOLATILITY  = 0.5       # minimum 24h price range % — flat coins not worth scalping
MAX_SETUPS      = 3         # cap signals per scan to avoid overtrading


async def get_top_symbols(exchange, limit: int = 200) -> List[str]:
    """Return top symbols by 24h quote volume, filtered by spread and volatility."""
    try:
        tickers = await exchange.fetch_tickers()
        usdt_pairs = {
            sym: t for sym, t in tickers.items()
            if sym.endswith("/USDT") and t.get("quoteVolume")
        }

        valid = []
        for sym, t in usdt_pairs.items():
            volume = float(t.get("quoteVolume") or 0)
            if volume < MIN_VOLUME_24H:
                continue

            bid = float(t.get("bid") or 0)
            ask = float(t.get("ask") or 0)
            if bid <= 0 or ask <= 0:
                continue

            spread_pct = ((ask - bid) / bid) * 100
            if spread_pct > MAX_SPREAD_PCT:
                continue

            # Volatility filter: skip coins that barely moved in 24h
            high_24h = float(t.get("high") or 0)
            low_24h  = float(t.get("low") or 0)
            if high_24h > 0 and low_24h > 0:
                volatility = ((high_24h - low_24h) / low_24h) * 100
                if volatility < MIN_VOLATILITY:
                    continue

            valid.append((sym, volume))

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
        List of valid setups (capped at MAX_SETUPS per scan).
    """
    symbols = await get_top_symbols(exchange)
    logger.info(f"Scanner: checking {len(symbols)} symbols")

    passed_liq = passed_cvd = passed_sweep = passed_entry = 0
    setups = []

    for symbol in symbols:
        if len(setups) >= MAX_SETUPS:
            break

        if symbol in open_symbols:
            continue

        try:
            # ── Step 1: 4H Liquidity Zone ──────────────────────────────────
            liq = await get_liquidity_zones(symbol, exchange)
            if not liq["near_zone"] or liq["side"] != "buy":
                continue
            passed_liq += 1

            # ── Step 2: 1H CVD ─────────────────────────────────────────────
            cvd = await get_cvd(symbol, exchange)
            if cvd["trend"] != "up":
                continue
            passed_cvd += 1

            # ── Step 3: 30M Sweep ──────────────────────────────────────────
            sweep = await detect_sweep(symbol, exchange, liq["low"])
            if not sweep["swept"] or not sweep["recovered"]:
                continue
            passed_sweep += 1

            # ── Step 4: 15M Engulfing ──────────────────────────────────────
            entry = await confirm_entry(symbol, exchange)
            if not entry["confirmed"]:
                continue
            passed_entry += 1

            # ── Step 5: Risk / R/R validation ─────────────────────────────
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
            logger.info(f"Scanner: error on {symbol}: {e}")
            continue

    logger.info(
        f"Scanner: done — liq={passed_liq} cvd={passed_cvd} "
        f"sweep={passed_sweep} entry={passed_entry} setups={len(setups)}"
    )
    return setups
