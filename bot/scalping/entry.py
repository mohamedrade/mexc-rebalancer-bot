"""
Entry confirmation on 15M candles using Bullish Engulfing pattern.

A Bullish Engulfing forms when:
  - The previous candle is bearish (close < open)
  - The current candle is bullish (close > open)
  - The current candle's body fully engulfs the previous candle's body
"""

from typing import Dict, Any


async def confirm_entry(symbol: str, exchange) -> Dict[str, Any]:
    """
    Returns:
        {
            "confirmed":   bool,
            "entry_price": float,  # close of the engulfing candle
        }
    """
    try:
        # Need at least 3 candles; last one may still be forming
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="15m", limit=4)
        if not ohlcv or len(ohlcv) < 3:
            return {"confirmed": False, "entry_price": 0.0}

        # Use the two most recently *closed* candles
        prev = ohlcv[-3]
        curr = ohlcv[-2]

        prev_open  = float(prev[1])
        prev_close = float(prev[4])
        curr_open  = float(curr[1])
        curr_close = float(curr[4])

        prev_bearish  = prev_close < prev_open
        curr_bullish  = curr_close > curr_open
        engulfs_body  = curr_open <= prev_close and curr_close >= prev_open

        confirmed = prev_bearish and curr_bullish and engulfs_body

        return {
            "confirmed":   confirmed,
            "entry_price": curr_close if confirmed else 0.0,
        }

    except Exception:
        return {"confirmed": False, "entry_price": 0.0}
