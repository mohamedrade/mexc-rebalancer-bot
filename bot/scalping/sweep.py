"""
Liquidity Sweep detection on 15M candles.

A sweep occurs when a candle wicks below the 1H liquidity low and then
closes back above it — indicating stop-losses were grabbed and price reversed.

Fallback: if no classic sweep is found, accepts a strong bullish rejection
candle near the zone low (wick-to-body ratio >= 2x) as a valid sweep signal.
"""

from typing import Dict, Any


async def detect_sweep(symbol: str, exchange, liquidity_low: float) -> Dict[str, Any]:
    """
    Args:
        symbol:        trading pair e.g. "BTC/USDT"
        exchange:      ccxt async exchange instance
        liquidity_low: the 1H zone low to watch for a sweep

    Returns:
        {
            "swept":     bool,
            "sweep_low": float,
            "recovered": bool,
        }
    """
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="15m", limit=30)
        if not ohlcv or len(ohlcv) < 5:
            return _empty_result()

        closed = ohlcv[:-1]   # exclude the still-forming candle

        # ── Classic sweep: wick below zone low, close above it ────────────
        # Allow a 1% buffer below zone_low to catch near-misses
        sweep_threshold = liquidity_low * 1.01
        for candle in reversed(closed[-12:]):
            _, open_, high, low, close, vol = candle
            low   = float(low)
            close = float(close)

            if low < sweep_threshold and close > liquidity_low:
                return {
                    "swept":     True,
                    "sweep_low": low,
                    "recovered": True,
                }

        # ── Fallback: bullish rejection candle near zone low ──────────────
        # Price within 3% of zone low + long lower wick (wick >= 2x body)
        for candle in reversed(closed[-6:]):
            _, open_, high, low, close, vol = candle
            open_  = float(open_)
            low    = float(low)
            close  = float(close)

            near_zone = low <= liquidity_low * 1.03
            if not near_zone:
                continue

            body       = abs(close - open_)
            lower_wick = min(open_, close) - low
            if body > 0 and lower_wick >= body * 2 and close > open_:
                return {
                    "swept":     True,
                    "sweep_low": low,
                    "recovered": True,
                }

        return _empty_result()

    except Exception:
        return _empty_result()


def _empty_result() -> Dict[str, Any]:
    return {"swept": False, "sweep_low": 0.0, "recovered": False}
