from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import pandas as pd

if TYPE_CHECKING:
    from .historical_service import OHLCBar


@dataclass
class Trade:
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    trades: List[Trade]
    summary: Dict[str, float]
    signals: List[Dict[str, Any]] = field(default_factory=list)


def _empty_summary(capital: float) -> Dict[str, float]:
    return {
        "trades": 0,
        "net_pnl": 0.0,
        "return_pct": 0.0,
        "max_drawdown": 0.0,
        "final_equity": capital,
    }


def _compute_max_drawdown(equity_points: List[float]) -> float:
    if not equity_points:
        return 0.0
    peak = equity_points[0]
    max_drawdown = 0.0
    for equity in equity_points[1:]:
        if equity > peak:
            peak = equity
        if peak <= 0:
            continue
        drawdown = (equity / peak - 1.0) * 100.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _moving_average(values: List[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        return [None] * len(values)
    out: List[Optional[float]] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def run_ma_crossover(bars: List[OHLCBar], fast: int, slow: int, capital: float) -> BacktestResult:
    if not bars or fast <= 0 or slow <= 0 or fast >= slow:
        return BacktestResult(trades=[], summary=_empty_summary(capital))

    closes = [b.close for b in bars]
    fast_ma = _moving_average(closes, fast)
    slow_ma = _moving_average(closes, slow)

    position_qty = 0.0
    entry_price = 0.0
    entry_dt = None
    trades: List[Trade] = []
    equity = capital
    peak_equity = capital
    max_drawdown = 0.0

    # loop until len-2 so we can use i+1 safely
    for i in range(1, len(bars) - 1):
        f, s = fast_ma[i], slow_ma[i]
        pf, ps = fast_ma[i - 1], slow_ma[i - 1]
        if None in (f, s, pf, ps):
            continue

        cross_up = pf < ps and f >= s
        cross_dn = pf > ps and f <= s

        next_bar = bars[i + 1]  # execute on next day's open

        if position_qty == 0.0 and cross_up:
            entry_price = next_bar.open
            position_qty = equity / entry_price
            entry_dt = next_bar.date

        elif position_qty > 0.0 and cross_dn:
            exit_price = next_bar.open
            pnl = (exit_price - entry_price) * position_qty
            pnl_pct = (exit_price / entry_price - 1.0) * 100.0
            equity += pnl
            trades.append(
                Trade(
                    entry_date=datetime.combine(entry_dt, datetime.min.time()),
                    exit_date=datetime.combine(next_bar.date, datetime.min.time()),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                )
            )
            position_qty = 0.0
            entry_price = 0.0
            entry_dt = None

        # Track drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity / peak_equity - 1.0) * 100.0
        if dd < max_drawdown:
            max_drawdown = dd

    # Liquidate if still in position
    if position_qty > 0.0 and entry_dt:
        last_bar = bars[-1]
        exit_price = last_bar.close
        pnl = (exit_price - entry_price) * position_qty
        pnl_pct = (exit_price / entry_price - 1.0) * 100.0
        equity += pnl
        trades.append(
            Trade(
                entry_date=datetime.combine(entry_dt, datetime.min.time()),
                exit_date=datetime.combine(last_bar.date, datetime.min.time()),
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
            )
        )

    net_pnl = equity - capital
    return_pct = (equity / capital - 1.0) * 100.0 if capital > 0 else 0.0
    summary = {
        "trades": len(trades),
        "net_pnl": net_pnl,
        "return_pct": return_pct,
        "max_drawdown": max_drawdown,
        "final_equity": equity,
    }

    return BacktestResult(trades=trades, summary=summary)


def run_ema_boll_breakout(
    bars: List[OHLCBar],
    ema_period: int = 5,
    bb_period: int = 20,
    bb_dev: float = 1.5,
    capital: float = 100000.0,
) -> BacktestResult:
    """Run EMA + Bollinger breakout strategy on OHLC bars.

    Strategy rules:
    - LONG when close crosses above upper Bollinger band and close > EMA.
    - SHORT when close crosses below lower Bollinger band and close < EMA.
    - Repeated same-direction signals are ignored.
    - On opposite signal, current position is closed and reversed.
    """
    if (
        not bars
        or ema_period <= 0
        or bb_period <= 1
        or bb_dev <= 0
        or capital <= 0
    ):
        return BacktestResult(trades=[], summary=_empty_summary(capital))

    df = pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        index=pd.to_datetime([b.date for b in bars]),
    )

    # Coerce numeric columns to avoid type issues from external data providers.
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    if df.empty:
        return BacktestResult(trades=[], summary=_empty_summary(capital))

    warmup = max(ema_period, bb_period)
    if len(df) <= warmup:
        return BacktestResult(trades=[], summary=_empty_summary(capital))

    close = df["close"]
    ema = close.ewm(span=ema_period, adjust=False, min_periods=ema_period).mean()
    bb_middle = close.rolling(window=bb_period, min_periods=bb_period).mean()
    bb_std = close.rolling(window=bb_period, min_periods=bb_period).std(ddof=0)
    bb_upper = bb_middle + bb_dev * bb_std
    bb_lower = bb_middle - bb_dev * bb_std

    signals: List[Dict[str, Any]] = []
    last_signal: Optional[str] = None

    for i in range(1, len(df)):
        prev_close = close.iat[i - 1]
        curr_close = close.iat[i]
        curr_ema = ema.iat[i]
        prev_upper = bb_upper.iat[i - 1]
        curr_upper = bb_upper.iat[i]
        prev_lower = bb_lower.iat[i - 1]
        curr_lower = bb_lower.iat[i]

        if pd.isna(curr_ema) or pd.isna(prev_upper) or pd.isna(curr_upper) or pd.isna(prev_lower) or pd.isna(curr_lower):
            continue

        ts = df.index[i].to_pydatetime()

        long_signal = (
            prev_close <= prev_upper
            and curr_close > curr_upper
            and curr_close > curr_ema
            and last_signal != "LONG"
        )
        short_signal = (
            prev_close >= prev_lower
            and curr_close < curr_lower
            and curr_close < curr_ema
            and last_signal != "SHORT"
        )

        if long_signal:
            signals.append(
                {
                    "datetime": ts,
                    "signal": "LONG",
                    "price": float(curr_close),
                    "ema": float(curr_ema),
                    "bb_upper": float(curr_upper),
                }
            )
            last_signal = "LONG"
        elif short_signal:
            signals.append(
                {
                    "datetime": ts,
                    "signal": "SHORT",
                    "price": float(curr_close),
                    "ema": float(curr_ema),
                    "bb_lower": float(curr_lower),
                }
            )
            last_signal = "SHORT"

    trades: List[Trade] = []
    equity = capital
    equity_points = [capital]
    position = 0  # 1 for long, -1 for short
    qty = 0.0
    entry_price = 0.0
    entry_dt: Optional[datetime] = None

    def _close_position(exit_price: float, exit_dt: datetime) -> None:
        nonlocal equity, position, qty, entry_price, entry_dt
        if position == 0 or qty <= 0 or entry_dt is None or entry_price <= 0:
            return

        if position > 0:
            pnl = (exit_price - entry_price) * qty
        else:
            pnl = (entry_price - exit_price) * qty

        notional = entry_price * qty
        pnl_pct = (pnl / notional) * 100.0 if notional > 0 else 0.0
        equity += pnl
        trades.append(
            Trade(
                entry_date=entry_dt,
                exit_date=exit_dt,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
            )
        )
        equity_points.append(equity)
        position = 0
        qty = 0.0
        entry_price = 0.0
        entry_dt = None

    for sig in signals:
        direction = 1 if sig["signal"] == "LONG" else -1
        sig_price = float(sig["price"])
        sig_dt = sig["datetime"]
        if sig_price <= 0:
            continue

        if position == direction:
            continue

        if position != 0:
            _close_position(exit_price=sig_price, exit_dt=sig_dt)

        if equity <= 0:
            continue
        qty = equity / sig_price
        if qty <= 0:
            continue
        position = direction
        entry_price = sig_price
        entry_dt = sig_dt

    if position != 0 and entry_dt is not None:
        _close_position(
            exit_price=float(close.iat[-1]),
            exit_dt=df.index[-1].to_pydatetime(),
        )

    net_pnl = equity - capital
    return_pct = (equity / capital - 1.0) * 100.0 if capital > 0 else 0.0
    summary = {
        "trades": len(trades),
        "signals": len(signals),
        "long_signals": sum(1 for s in signals if s["signal"] == "LONG"),
        "short_signals": sum(1 for s in signals if s["signal"] == "SHORT"),
        "net_pnl": net_pnl,
        "return_pct": return_pct,
        "max_drawdown": _compute_max_drawdown(equity_points),
        "final_equity": equity,
    }

    return BacktestResult(trades=trades, summary=summary, signals=signals)
