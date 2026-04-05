"""
Liquidity Sweep detection on 30M candles.

A sweep occurs when a candle wicks below the 4H liquidity low and then
closes back above it — indicating stop-losses were grabbed and price reversed.

The volume spike requirement has been removed: it was filtering out too many
valid setups. A wick below the zone that closes back above it is sufficient
confirmation when combined with the other confluence filters (CVD + engulfing).
"""

from typing import Dict, Any


async def detect_sweep(symbol: str, exchange, liquidity_low: float) -> Dict[str, Any]:
    """
    Args:
        symbol:        trading pair e.g. "BTC/USDT"
        exchange:      ccxt async exchange instance
        liquidity_low: the 4H zone low to watch for a sweep

    Returns:
        {
            "swept":     bool,
            "sweep_low": float,
            "recovered": bool,
        }
    """
    try:
        # Last 20 candles on 30M
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="30m", limit=20)
        if not ohlcv or len(ohlcv) < 5:
            return _empty_result()

        closed = ohlcv[:-1]   # exclude the still-forming candle

        # Check the last 8 closed candles for a sweep pattern
        for candle in reversed(closed[-8:]):
            _, open_, high, low, close, vol = candle
            low   = float(low)
            close = float(close)

            # Wick went below the liquidity low but candle closed above it
            if low < liquidity_low and close > liquidity_low:
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
