"""
Risk management: calculates stop loss, T1 target, and position size.

Rules:
  stop_loss = sweep_low * 0.997       (0.3% below the sweep wick)
  target1   = entry + risk * 1.5      (1.5R — sell 50% here, lock partial profit)

  No T2 hard target — the trailing stop in monitor.py handles the full exit,
  allowing the trade to ride the trend as far as it goes.

  Minimum R/R check removed: with a trailing stop there is no fixed reward,
  so R/R is open-ended. Any valid sweep entry is accepted.
"""

from typing import Dict, Any

_STOP_PCT = 0.003   # 0.3% below sweep low
_T1_R     = 1.5     # target1 = entry + 1.5 × risk (partial exit)


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
            "target2":       float,   # same as target1 — trailing handles full exit
            "qty":           float,
            "qty_half":      float,
            "risk_reward":   float,   # initial R (open-ended with trailing)
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

    qty      = round(trade_size_usdt / entry_price, 8)
    qty_half = round(qty / 2, 8)

    # R/R shown in notifications — open-ended since trailing stop rides the trend
    rr = round(_T1_R, 2)

    return {
        "stop_loss":   stop_loss,
        "target1":     target1,
        "target2":     target1,   # monitor uses trailing, not a hard T2
        "qty":         qty,
        "qty_half":    qty_half,
        "risk_reward": rr,
        "valid":       True,      # any valid sweep entry is accepted
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
