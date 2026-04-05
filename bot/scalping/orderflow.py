"""
Order Flow analysis — detects CVD shift from negative to positive.

Whales accumulate quietly then trigger a burst of buy orders.
We detect this by splitting recent trades into two halves and
checking if buy pressure increased significantly in the second half.

A "CVD shift" means:
  - First half:  sell pressure dominant (CVD negative or flat)
  - Second half: buy pressure dominant (CVD positive)
  - Delta between halves >= SHIFT_THRESHOLD

This pattern indicates smart money flipped from distribution to accumulation.
"""

from typing import Dict, Any

_SHIFT_THRESHOLD = 0.3   # second half CVD must be >= 30% more bullish than first


async def get_order_flow(symbol: str, exchange) -> Dict[str, Any]:
    """
    Returns:
        {
            "shifted":    bool,    # True if CVD flipped bullish recently
            "cvd_first":  float,   # CVD of first half of trades
            "cvd_second": float,   # CVD of second half of trades
            "delta":      float,   # cvd_second - cvd_first
        }
    """
    try:
        trades = await exchange.fetch_trades(symbol, limit=300)
        if not trades or len(trades) < 30:
            return _empty()

        mid = len(trades) // 2
        first_half  = trades[:mid]
        second_half = trades[mid:]

        cvd_first  = _calc_cvd(first_half)
        cvd_second = _calc_cvd(second_half)
        delta      = cvd_second - cvd_first

        # Shifted = second half is meaningfully more bullish than first
        # AND second half itself is net positive (actual buying)
        shifted = (cvd_second > 0) and (delta > 0)

        return {
            "shifted":    shifted,
            "cvd_first":  round(cvd_first, 4),
            "cvd_second": round(cvd_second, 4),
            "delta":      round(delta, 4),
        }

    except Exception:
        return _empty()


def _calc_cvd(trades: list) -> float:
    cvd = 0.0
    prev_price = float(trades[0]["price"]) if trades else 0.0

    for t in trades:
        price  = float(t["price"])
        amount = float(t["amount"])
        side   = t.get("side")

        if side == "buy":
            cvd += amount
        elif side == "sell":
            cvd -= amount
        else:
            if price >= prev_price:
                cvd += amount
            else:
                cvd -= amount
        prev_price = price

    return cvd


def _empty() -> Dict[str, Any]:
    return {
        "shifted":    False,
        "cvd_first":  0.0,
        "cvd_second": 0.0,
        "delta":      0.0,
    }
