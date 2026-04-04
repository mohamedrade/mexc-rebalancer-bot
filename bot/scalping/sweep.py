"""
Liquidity Sweep detection on 30M candles.

A sweep occurs when a candle wicks below the 4H liquidity low and then
closes back above it — indicating smart money grabbed stop-losses and reversed.
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
            "swept":     bool,   # a sweep happened
            "sweep_low": float,  # the actual wick low of the sweep candle
            "recovered": bool,   # candle closed back above liquidity_low
        }
    """
    try:
        # Last 10 candles on 30M
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="30m", limit=10)
        if not ohlcv or len(ohlcv) < 3:
            return _empty_result()

        # Check the last 3 closed candles for a sweep pattern
        for candle in reversed(ohlcv[-4:-1]):   # skip the still-forming last candle
            _, open_, high, low, close, _ = candle
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
