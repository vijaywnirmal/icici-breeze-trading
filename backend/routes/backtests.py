from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..utils.postgres import get_conn, ensure_tables
from ..utils.response import error_response, success_response, log_exception
from ..services.historical_service import get_ohlc_daily
from ..services.backtest_service import run_ma_crossover, run_ema_boll_breakout


router = APIRouter(prefix="/api", tags=["backtests"])


class RunBacktestPayload(BaseModel):
    user_id: Optional[str] = Field(None, description="UUID of user")
    symbol: str = Field(..., description="Symbol, e.g. NIFTY")
    start_date: date
    end_date: date
    strategy: str = Field("ma_crossover")
    params: Dict[str, Any] = Field(default_factory=dict)


DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"


def _serialize_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for sig in signals:
        row = dict(sig)
        ts = row.get("datetime")
        if isinstance(ts, datetime):
            row["datetime"] = ts.isoformat()
        serialized.append(row)
    return serialized


@router.post("/backtests/run")
def run_backtest(payload: RunBacktestPayload) -> Dict[str, Any]:
    try:
        ensure_tables()
        bars = get_ohlc_daily(payload.symbol, payload.start_date, payload.end_date)
        if not bars:
            return error_response("No OHLC data available for given range")

        strategy_name = (payload.strategy or "").strip().lower()
        if strategy_name == "ma_crossover":
            fast = int(payload.params.get("fast", 20))
            slow = int(payload.params.get("slow", 50))
            capital = float(payload.params.get("capital", 100000))
            result = run_ma_crossover(bars, fast=fast, slow=slow, capital=capital)
        elif strategy_name in {"ema_boll", "ema_boll_breakout", "5ema_boll"}:
            ema_period = int(payload.params.get("ema_period", 5))
            bb_period = int(payload.params.get("bb_period", 20))
            bb_dev = float(payload.params.get("bb_dev", 1.5))
            capital = float(payload.params.get("capital", 100000))
            result = run_ema_boll_breakout(
                bars,
                ema_period=ema_period,
                bb_period=bb_period,
                bb_dev=bb_dev,
                capital=capital,
            )
        else:
            return error_response("Unsupported strategy", error=payload.strategy)

        serialized_signals = _serialize_signals(result.signals)

        # Persist summary and trades
        with get_conn() as conn:
            if conn is None:
                return success_response(
                    "Backtest computed",
                    backtest_id=None,
                    summary=result.summary,
                    trades=[t.__dict__ for t in result.trades],
                    signals=serialized_signals,
                )
            user_id = payload.user_id or DEFAULT_USER_ID
            row = conn.execute(
                text(
                    """
                    INSERT INTO backtests (user_id, symbol, strategy, params, start_date, end_date, summary)
                    VALUES (:user_id, :symbol, :strategy, CAST(:params AS JSONB), :start, :end, CAST(:summary AS JSONB))
                    RETURNING id
                    """
                ),
                {
                    "user_id": user_id,
                    "symbol": payload.symbol.upper(),
                    "strategy": payload.strategy,
                    "params": __import__("json").dumps(payload.params),
                    "start": payload.start_date,
                    "end": payload.end_date,
                    "summary": __import__("json").dumps(result.summary),
                },
            )
            bt_id = row.fetchone()[0]

            # insert trades
            for idx, t in enumerate(result.trades, start=1):
                conn.execute(
                    text(
                        """
                        INSERT INTO trades (backtest_id, trade_no, entry_date, exit_date, entry_price, exit_price, pnl, pnl_pct)
                        VALUES (:bid, :no, :entry_dt, :exit_dt, :entry_px, :exit_px, :pnl, :pnl_pct)
                        """
                    ),
                    {
                        "bid": bt_id,
                        "no": idx,
                        "entry_dt": t.entry_date,
                        "exit_dt": t.exit_date,
                        "entry_px": t.entry_price,
                        "exit_px": t.exit_price,
                        "pnl": t.pnl,
                        "pnl_pct": t.pnl_pct,
                    },
                )

        return success_response(
            "Backtest saved",
            backtest_id=str(bt_id),
            summary=result.summary,
            signals=serialized_signals,
        )
    except Exception as exc:
        log_exception(exc, context="backtests.run")
        return error_response("Exception while running backtest", error=str(exc))


@router.get("/backtests/{backtest_id}")
def get_backtest(backtest_id: str) -> Dict[str, Any]:
    try:
        with get_conn() as conn:
            if conn is None:
                return error_response("Database not configured")
            row = conn.execute(text("SELECT id, user_id, symbol, strategy, params, start_date, end_date, summary, created_at FROM backtests WHERE id = :id"), {"id": backtest_id}).fetchone()
            if not row:
                return error_response("Backtest not found")
            trades = conn.execute(text("SELECT trade_no, entry_date, exit_date, entry_price, exit_price, pnl, pnl_pct FROM trades WHERE backtest_id = :id ORDER BY trade_no"), {"id": backtest_id}).fetchall()
            trades_list = [
                {
                    "trade_no": t[0],
                    "entry_date": t[1],
                    "exit_date": t[2],
                    "entry_price": float(t[3]) if t[3] is not None else None,
                    "exit_price": float(t[4]) if t[4] is not None else None,
                    "pnl": float(t[5]) if t[5] is not None else None,
                    "pnl_pct": float(t[6]) if t[6] is not None else None,
                }
                for t in trades
            ]
            bt = {
                "id": str(row[0]),
                "user_id": str(row[1]),
                "symbol": row[2],
                "strategy": row[3],
                "params": row[4],
                "start_date": row[5],
                "end_date": row[6],
                "summary": row[7],
                "created_at": row[8],
                "trades": trades_list,
            }
            return success_response("Backtest loaded", backtest=bt)
    except Exception as exc:
        log_exception(exc, context="backtests.get")
        return error_response("Exception while fetching backtest", error=str(exc))


@router.get("/backtests")
def list_backtests(user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        with get_conn() as conn:
            if conn is None:
                return error_response("Database not configured")
            if user_id:
                q = "SELECT id, symbol, strategy, created_at, summary FROM backtests WHERE user_id = :uid ORDER BY created_at DESC"
                rows = conn.execute(text(q), {"uid": user_id}).fetchall()
            else:
                q = "SELECT id, symbol, strategy, created_at, summary FROM backtests ORDER BY created_at DESC LIMIT 100"
                rows = conn.execute(text(q)).fetchall()
            items = [
                {
                    "id": str(r[0]),
                    "symbol": r[1],
                    "strategy": r[2],
                    "created_at": r[3],
                    "summary": r[4],
                }
                for r in rows
            ]
            return success_response("Backtests", items=items)
    except Exception as exc:
        log_exception(exc, context="backtests.list")
        return error_response("Exception while listing backtests", error=str(exc))


