"""
Risk management: calculates stop loss, targets, and position size.

Rules:
  stop_loss = sweep_low * 0.997       (0.3% below the sweep wick)
  target1   = entry + risk * 1.5      (1.5R — close 50% of position)
  target2   = entry + risk * 3.0      (3R   — close remaining 50%)

  Targets are dynamic (based on actual risk distance) so R/R is always
  consistent regardless of how far the sweep wick is from entry.
  Fixed-% targets caused the R/R check to fail in almost all real
  market conditions because the stop distance varies per trade.
"""

from typing import Dict, Any

_STOP_PCT = 0.003   # 0.3% below sweep low
_T1_R     = 1.5     # target1 = entry + 1.5 × risk
_T2_R     = 3.0     # target2 = entry + 3.0 × risk
_MIN_RR   = 2.0     # reject trades below this R/R (always met with _T2_R=3)


def calculate_risk(
    entry_price: float,
    sweep_low: float,
    liquidity_high: float,   # kept for API compatibility
    trade_size_usdt: float = 10.0,
) -> Dict[str, Any]:
    """
    Returns:
        {
            "stop_loss":     float,
            "target1":       float,
            "target2":       float,
            "qty":           float,
            "qty_half":      float,
            "risk_reward":   float,
            "valid":         bool,
        }
    """
    if entry_price <= 0 or sweep_low <= 0:
        return _invalid()

    stop_loss = round(sweep_low * (1 - _STOP_PCT), 8)
    risk      = entry_price - stop_loss

    if risk <= 0:
        return _invalid()

    target1 = round(entry_price + risk * _T1_R, 8)
    target2 = round(entry_price + risk * _T2_R, 8)

    reward = target2 - entry_price
    rr     = round(reward / risk, 2)

    qty      = round(trade_size_usdt / entry_price, 8)
    qty_half = round(qty / 2, 8)

    return {
        "stop_loss":   stop_loss,
        "target1":     target1,
        "target2":     target2,
        "qty":         qty,
        "qty_half":    qty_half,
        "risk_reward": rr,
        "valid":       rr >= _MIN_RR,
    }


def _invalid() -> Dict[str, Any]:
    return {
        "stop_loss":   0.0,
        "target1":     0.0,
        "target2":     0.0,
        "qty":         0.0,
        "qty_half":    0.0,
        "risk_reward": 0.0,
        "valid":       False,
    }
