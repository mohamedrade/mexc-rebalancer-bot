"""
Liquidity zone detection using 4H candles.

Fetches the last 20 4H candles and identifies the highest high and lowest low.
Returns whether the current price is near either zone (within 0.5%).
"""

from typing import Dict, Any


async def get_liquidity_zones(symbol: str, exchange) -> Dict[str, Any]:
    """
    Returns:
        {
            "high": float,        # highest point in last 20 4H candles
            "low": float,         # lowest point in last 20 4H candles
            "current": float,     # current price
            "near_zone": bool,    # True if price is within 0.5% of high or low
            "side": str,          # "buy" | "sell" | None
        }
    """
    try:
        # Fetch last 20 candles on 4H timeframe
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="4h", limit=20)
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

        near_low  = current <= zone_low  * 1.005   # within 0.5% above low
        near_high = current >= zone_high * 0.995   # within 0.5% below high

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
