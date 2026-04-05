"""
Liquidity zone detection using 1H candles.

Fetches the last 24 1H candles (~1 day) and identifies local support/resistance.
Returns whether the current price is near the low zone (buy side).

Using 1H instead of 4H gives more frequent, actionable zones that price
actually revisits. Proximity threshold is 5% to catch approaches early.
"""

from typing import Dict, Any

_LOOKBACK       = 24    # 24 × 1H = 1 day
_PROXIMITY_PCT  = 0.05  # price within 5% of zone boundary


async def get_liquidity_zones(symbol: str, exchange) -> Dict[str, Any]:
    """
    Returns:
        {
            "high": float,        # highest point in last 50 4H candles
            "low": float,         # lowest point in last 50 4H candles
            "current": float,     # current price
            "near_zone": bool,    # True if price is within 3% of high or low
            "side": str,          # "buy" | "sell" | None
        }
    """
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="1h", limit=_LOOKBACK)
        if not ohlcv or len(ohlcv) < 5:
            return _empty_result()

        highs = [c[2] for c in ohlcv]   # index 2 = high
        lows  = [c[3] for c in ohlcv]   # index 3 = low

        zone_high = max(highs)
        zone_low  = min(lows)

        # Current price from last closed candle close
        current = float(ohlcv[-1][4])   # index 4 = close
        if current <= 0:
            return _empty_result()

        near_low  = current <= zone_low  * (1 + _PROXIMITY_PCT)
        near_high = current >= zone_high * (1 - _PROXIMITY_PCT)

        if near_low:
            side = "buy"
        elif near_high:
            side = "sell"
        else:
            side = None

        return {
            "high":      zone_high,
            "low":       zone_low,
            "current":   current,
            "near_zone": near_low or near_high,
            "side":      side,
        }

    except Exception:
        return _empty_result()


def _empty_result() -> Dict[str, Any]:
    return {
        "high":      0.0,
        "low":       0.0,
        "current":   0.0,
        "near_zone": False,
        "side":      None,
    }
