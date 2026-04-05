"""
Liquidity zone detection using 4H candles.

Fetches the last 50 4H candles (~8 days) and identifies the highest high
and lowest low. Returns whether the current price is near either zone.

Using 50 candles instead of 20 gives a wider, more meaningful zone that
captures weekly swing highs/lows where liquidity actually pools.
The proximity threshold is 3% (was 2%) to account for crypto volatility
and avoid missing valid setups where price is approaching but not yet
at the exact zone boundary.
"""

from typing import Dict, Any

_LOOKBACK       = 50    # 50 × 4H = ~8 days
_PROXIMITY_PCT  = 0.03  # price within 3% of zone boundary


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
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="4h", limit=_LOOKBACK)
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
