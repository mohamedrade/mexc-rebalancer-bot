"""
Liquidity Sweep detection on 30M candles.

A sweep occurs when a candle wicks below the 4H liquidity low and then
closes back above it — indicating smart money grabbed stop-losses and reversed.

A volume spike on the sweep candle (>= 1.5x the average of prior candles)
is required to confirm that the move was driven by real institutional activity,
not just a thin-market wick.
"""

from typing import Dict, Any

_VOLUME_SPIKE_MULTIPLIER = 1.5   # sweep candle volume must be >= 1.5x average


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

        # Average volume of all closed candles (used as baseline)
        volumes = [float(c[5]) for c in closed if float(c[5]) > 0]
        avg_vol = sum(volumes) / len(volumes) if volumes else 0

        # Check the last 8 closed candles for a sweep pattern
        for candle in reversed(closed[-8:]):
            _, open_, high, low, close, vol = candle
            low   = float(low)
            close = float(close)
            vol   = float(vol)

            # Wick went below the liquidity low but candle closed above it
            if low < liquidity_low and close > liquidity_low:
                # Require a volume spike to confirm institutional activity
                if avg_vol > 0 and vol < avg_vol * _VOLUME_SPIKE_MULTIPLIER:
                    continue   # weak sweep — likely a fake-out, skip it
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
