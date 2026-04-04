"""
Cumulative Volume Delta (CVD) calculation using recent trades on 1H window.

MEXC doesn't expose CVD directly, so we approximate it from recent trades:
  - trades where price >= previous price  → buy volume
  - trades where price <  previous price  → sell volume
CVD = cumulative sum of (buy_vol - sell_vol)
"""

from typing import Dict, Any


async def get_cvd(symbol: str, exchange) -> Dict[str, Any]:
    """
    Returns:
        {
            "cvd":   float,              # positive = buy pressure, negative = sell pressure
            "trend": "up"|"down"|"neutral"
        }
    """
    try:
        # Fetch last 200 recent trades
        trades = await exchange.fetch_trades(symbol, limit=200)
        if not trades or len(trades) < 10:
            return {"cvd": 0.0, "trend": "neutral"}

        cvd = 0.0
        prev_price = float(trades[0]["price"])

        for t in trades[1:]:
            price  = float(t["price"])
            amount = float(t["amount"])
            if price >= prev_price:
                cvd += amount    # buy pressure
            else:
                cvd -= amount    # sell pressure
            prev_price = price

        if cvd > 0:
            trend = "up"
        elif cvd < 0:
            trend = "down"
        else:
            trend = "neutral"

        return {"cvd": round(cvd, 6), "trend": trend}

    except Exception:
        return {"cvd": 0.0, "trend": "neutral"}
