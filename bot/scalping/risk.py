"""
Risk management: calculates stop loss, targets, and position size.

Rules:
  stop_loss = sweep_low * 0.997       (0.3% below the sweep wick)
  target1   = entry_price * 1.005     (+0.5% — close 50% of position)
  target2   = liquidity_high          (4H zone high — close remaining 50%)
  qty       = trade_size_usdt / entry_price
"""

from typing import Dict, Any


def calculate_risk(
    entry_price: float,
    sweep_low: float,
    liquidity_high: float,
    trade_size_usdt: float = 10.0,
) -> Dict[str, Any]:
    """
    Returns:
        {
            "stop_loss":     float,
            "target1":       float,
            "target2":       float,
            "qty":           float,
            "qty_half":      float,   # 50% of qty for partial close at target1
            "risk_reward":   float,   # R/R ratio based on target2
            "valid":         bool,    # False if R/R < 1.5 (not worth taking)
        }
    """
    if entry_price <= 0 or sweep_low <= 0 or liquidity_high <= 0:
        return _invalid()

    stop_loss = sweep_low * 0.997
    target1   = entry_price * 1.005
    target2   = liquidity_high

    # target2 must be above entry
    if target2 <= entry_price:
        return _invalid()

    risk   = entry_price - stop_loss
    reward = target2 - entry_price

    if risk <= 0:
        return _invalid()

    rr = round(reward / risk, 2)

    qty      = round(trade_size_usdt / entry_price, 8)
    qty_half = round(qty / 2, 8)

    return {
        "stop_loss":   round(stop_loss, 8),
        "target1":     round(target1, 8),
        "target2":     round(target2, 8),
        "qty":         qty,
        "qty_half":    qty_half,
        "risk_reward": rr,
        "valid":       rr >= 1.5,
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
