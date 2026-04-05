"""
Fair Value Gap (FVG) / Imbalance detector on 5M candles.

An imbalance (bullish FVG) forms when:
  candle[i-1] high < candle[i+1] low

This means candle[i] moved so fast upward that it left a price gap —
no orders were filled in that range. Price tends to return to fill
these gaps, making them high-probability entry zones.

We look for price currently sitting inside or just above a recent
bullish FVG — that's where whales accumulate before the next push.
"""

from typing import Dict, Any, List


async def get_imbalance(symbol: str, exchange) -> Dict[str, Any]:
    """
    Scans last 50 5M candles for bullish Fair Value Gaps.

    Returns:
        {
            "found":       bool,
            "fvg_low":     float,   # bottom of the gap
            "fvg_high":    float,   # top of the gap
            "price_in_fvg": bool,   # current price is inside the gap
            "price_above_fvg": bool # price just above gap (already filled, momentum up)
        }
    """
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="5m", limit=52)
        if not ohlcv or len(ohlcv) < 5:
            return _empty()

        current_price = float(ohlcv[-1][4])

        # Scan for bullish FVGs in last 50 closed candles
        fvgs: List[Dict] = []
        candles = ohlcv[:-1]  # exclude forming candle

        for i in range(1, len(candles) - 1):
            prev_high  = float(candles[i - 1][2])
            next_low   = float(candles[i + 1][3])

            # Bullish FVG: gap between prev candle high and next candle low
            if next_low > prev_high:
                fvgs.append({
                    "low":  prev_high,
                    "high": next_low,
                    "age":  len(candles) - i,  # candles ago
                })

        if not fvgs:
            return _empty()

        # Use the most recent FVG
        fvg = fvgs[-1]
        fvg_low  = fvg["low"]
        fvg_high = fvg["high"]

        price_in_fvg    = fvg_low <= current_price <= fvg_high
        # Price just above FVG (within 0.5%) — gap filled, momentum continuing
        price_above_fvg = fvg_high < current_price <= fvg_high * 1.005

        found = price_in_fvg or price_above_fvg

        return {
            "found":           found,
            "fvg_low":         fvg_low,
            "fvg_high":        fvg_high,
            "price_in_fvg":    price_in_fvg,
            "price_above_fvg": price_above_fvg,
        }

    except Exception:
        return _empty()


def _empty() -> Dict[str, Any]:
    return {
        "found":           False,
        "fvg_low":         0.0,
        "fvg_high":        0.0,
        "price_in_fvg":    False,
        "price_above_fvg": False,
    }
