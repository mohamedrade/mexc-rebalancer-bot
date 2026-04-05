"""
Risk management: calculates stop loss, targets, and position size.

Rules:
  stop_loss = sweep_low * 0.997       (0.3% below the sweep wick)
  target1   = entry_price * 1.005     (+0.5%  — close 50% of position)
  target2   = entry_price * 1.015     (+1.5%  — close remaining 50%)

  Fixed % targets are used instead of the 4H zone high because the zone
  high is often 10-20% away — unreachable for scalping. Fixed targets
  give a realistic, consistent R/R on every trade.

  Effective R/R:
    risk   = ~0.3%
    reward = 1.5%
    R/R    = 1:5
"""

from typing import Dict, Any

_TARGET1_PCT = 0.005   # +0.5%
_TARGET2_PCT = 0.015   # +1.5%
_STOP_PCT    = 0.003   # 0.3% below sweep low
_MIN_RR      = 2.0     # reject trades below this R/R


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

    stop_loss = sweep_low * (1 - _STOP_PCT)
    target1   = entry_price * (1 + _TARGET1_PCT)
    target2   = entry_price * (1 + _TARGET2_PCT)

    risk = entry_price - stop_loss
    if risk <= 0:
        return _invalid()

    reward = target2 - entry_price
    rr     = round(reward / risk, 2)

    qty      = round(trade_size_usdt / entry_price, 8)
    qty_half = round(qty / 2, 8)

    return {
        "stop_loss":   round(stop_loss, 8),
        "target1":     round(target1, 8),
        "target2":     round(target2, 8),
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
