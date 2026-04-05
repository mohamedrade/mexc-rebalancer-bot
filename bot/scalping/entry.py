"""
Entry confirmation on 5M candles.

Checks for bullish momentum using two patterns (either is sufficient):

1. Bullish Engulfing: previous candle bearish, current candle bullish and
   body overlaps at least 50% of the previous candle's body.

2. Bullish close: last closed candle is bullish with a lower wick >= body
   (hammer-like), indicating buying pressure at the zone.

Relaxed from strict full-engulf to 50% overlap to catch more valid entries
without sacrificing directional bias.
"""

from typing import Dict, Any


async def confirm_entry(symbol: str, exchange) -> Dict[str, Any]:
    """
    Returns:
        {
            "confirmed":   bool,
            "entry_price": float,  # close of the confirming candle
        }
    """
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe="5m", limit=5)
        if not ohlcv or len(ohlcv) < 3:
            return {"confirmed": False, "entry_price": 0.0}

        # Use the two most recently *closed* candles
        prev = ohlcv[-3]
        curr = ohlcv[-2]

        prev_open  = float(prev[1])
        prev_close = float(prev[4])
        curr_open  = float(curr[1])
        curr_close = float(curr[4])

        # ── Pattern 1: Relaxed Bullish Engulfing (50% body overlap) ──────
        prev_bearish = prev_close < prev_open
        curr_bullish = curr_close > curr_open
        prev_body    = abs(prev_open - prev_close)
        overlap      = min(curr_close, prev_open) - max(curr_open, prev_close)
        partial_engulf = prev_body > 0 and overlap >= prev_body * 0.5

        if prev_bearish and curr_bullish and partial_engulf:
            return {"confirmed": True, "entry_price": curr_close}

        # ── Pattern 2: Hammer / bullish rejection candle ──────────────────
        curr_body       = abs(curr_close - curr_open)
        curr_lower_wick = min(curr_open, curr_close) - float(curr[3])
        is_hammer = (
            curr_bullish
            and curr_body > 0
            and curr_lower_wick >= curr_body * 1.5
        )

        if is_hammer:
            return {"confirmed": True, "entry_price": curr_close}

        return {"confirmed": False, "entry_price": 0.0}

    except Exception:
        return {"confirmed": False, "entry_price": 0.0}
