"""
Whale Order Flow scanner — runs every 5 minutes.

Pipeline (3 conditions, all must pass):

  1. FVG (Fair Value Gap): price is inside or just above a recent
     bullish imbalance on 5M — this is where whales accumulate.

  2. CVD Shift: order flow flipped from sell-dominant to buy-dominant
     in the last 300 trades — whales started buying.

  3. Breakout candle: last closed 5M candle broke above the highest
     high of the previous 3 candles — momentum confirmed.

Targets: T1=+0.5%, T2=+1.0%, SL=-0.4%
Average hold: 5–15 minutes.
"""

import logging
from typing import List, Dict, Any

from bot.scalping.imbalance  import get_imbalance
from bot.scalping.orderflow  import get_order_flow
from bot.scalping.whale_risk import calculate_whale_risk

logger = logging.getLogger(__name__)

MIN_VOLUME_24H = 300_000   # $300K minimum — need liquidity for fast exits
MAX_SPREAD_PCT = 0.4       # 0.4% max spread
MAX_SETUPS     = 5         # max signals per scan


async def get_top_symbols(exchange, limit: int = 150) -> List[str]:
    """Return top symbols by 24h volume, filtered for tight spread."""
    try:
        tickers = await exchange.fetch_tickers()
        valid = []
        for sym, t in tickers.items():
            if not sym.endswith("/USDT"):
                continue
            volume = float(t.get("quoteVolume") or 0)
            if volume < MIN_VOLUME_24H:
                continue
            bid = float(t.get("bid") or 0)
            ask = float(t.get("ask") or 0)
            if bid <= 0 or ask <= 0:
                continue
            spread = ((ask - bid) / bid) * 100
            if spread > MAX_SPREAD_PCT:
                continue
            valid.append((sym, volume))

        valid.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in valid[:limit]]

    except Exception as e:
        logger.error(f"WhaleScanner: failed to fetch symbols: {e}")
        return []


async def whale_scan(
    exchange,
    open_symbols: set,
    trade_size_usdt: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Full whale order flow scan.

    Returns list of valid setups (capped at MAX_SETUPS).
    """
    symbols = await get_top_symbols(exchange)
    logger.info(f"WhaleScanner: checking {len(symbols)} symbols")

    passed_fvg = passed_flow = passed_break = 0
    setups = []

    for symbol in symbols:
        if len(setups) >= MAX_SETUPS:
            break
        if symbol in open_symbols:
            continue

        try:
            # ── Step 1: Fair Value Gap ─────────────────────────────────────
            imb = await get_imbalance(symbol, exchange)
            if not imb["found"]:
                logger.debug(f"WhaleScanner: {symbol} — no FVG")
                continue
            passed_fvg += 1

            # ── Step 2: CVD Shift (order flow flipped bullish) ─────────────
            flow = await get_order_flow(symbol, exchange)
            if not flow["shifted"]:
                logger.debug(f"WhaleScanner: {symbol} — no CVD shift")
                continue
            passed_flow += 1

            # ── Step 3: Breakout above last 3 candles high ─────────────────
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="5m", limit=6)
            if not ohlcv or len(ohlcv) < 5:
                continue

            closed       = ohlcv[:-1]
            last_candle  = closed[-1]
            prev_3       = closed[-4:-1]

            last_close   = float(last_candle[4])
            last_open    = float(last_candle[1])
            prev_3_high  = max(float(c[2]) for c in prev_3)

            # Must be bullish and close above previous 3 candles' high
            if last_close <= last_open or last_close <= prev_3_high:
                logger.debug(f"WhaleScanner: {symbol} — no breakout")
                continue
            passed_break += 1

            # ── Risk calculation ───────────────────────────────────────────
            entry_price = last_close
            risk = calculate_whale_risk(entry_price, trade_size_usdt)
            if not risk["valid"]:
                continue

            setups.append({
                "symbol":      symbol,
                "side":        "buy",
                "entry_price": entry_price,
                "stop_loss":   risk["stop_loss"],
                "target1":     risk["target1"],
                "target2":     risk["target2"],
                "qty":         risk["qty"],
                "qty_60pct":   risk["qty_60pct"],
                "qty_40pct":   risk["qty_40pct"],
                "risk_reward": risk["risk_reward"],
                "fvg_low":     imb["fvg_low"],
                "fvg_high":    imb["fvg_high"],
                "cvd_delta":   flow["delta"],
            })

            logger.info(f"WhaleScanner: setup → {symbol} entry={entry_price:.6g}")

        except Exception as e:
            logger.debug(f"WhaleScanner: error on {symbol}: {e}")
            continue

    logger.info(
        f"WhaleScanner: done — fvg={passed_fvg} flow={passed_flow} "
        f"break={passed_break} setups={len(setups)}"
    )
    return setups
