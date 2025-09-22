from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
import contextlib
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..utils.response import log_exception
from ..services.breeze_service import BreezeService
from ..utils.session import get_breeze
from ..utils.config import settings
from ..services.quotes_cache import get_cached_quote
from ..services.ws_stream_manager import STREAM_MANAGER
from .quotes import _is_market_open_ist

router = APIRouter(tags=["stream"])
@router.websocket("/ws/stocks")
async def ws_stocks(websocket: WebSocket) -> None:
    # Alias to existing ticks socket for stock/index data
    return await ws_ticks(websocket)


@dataclass
class ConnectionState:
    """Per-connection registry for subscriptions and flow control."""
    symbol: Optional[str] = None
    exchange_code: str = "NSE"
    product_type: str = "cash"
    last_sent_ts: float = 0.0
    last_sent_ts_by_symbol: Dict[str, float] | None = None
    subscriptions: Dict[str, Dict[str, str]] | None = None
    min_interval_ms: int = 250
    breeze: Optional[BreezeService] = None


@router.websocket("/ws/options")
async def ws_options(websocket: WebSocket) -> None:
    """Dedicated WebSocket for option chain data only."""
    await websocket.accept()
    # Send a small hello so DevTools shows an initial frame
    try:
        await websocket.send_text(json.dumps({"type": "hello", "scope": "options"}))
    except Exception:
        pass
    state = ConnectionState()
    state.last_sent_ts_by_symbol = {}
    state.subscriptions = {}
    # Track this connection's selected expiry (YYYY-MM-DD)
    state.selected_expiry_iso = ""
    breeze_ws_connected = False
    loop = asyncio.get_running_loop()
    STREAM_MANAGER.set_loop(loop)
    STREAM_MANAGER.register_client(websocket, loop, is_option_client=True)
    
    # The stream manager will automatically broadcast to this client via _broadcast_options
    # since we registered it as an option client above


    def _ensure_breeze_runtime() -> Optional[BreezeService]:
        """Ensure a BreezeService is available from runtime or .env fallback."""
        try:
            runtime = get_breeze()
            if runtime is not None:
                return runtime
            log_exception(Exception("No active Breeze session found"), context="ws_options.ensure_breeze_runtime")
        except Exception as exc:
            log_exception(exc, context="ws_options.ensure_breeze_runtime")
        return None

    # Per-connection filtered forwarder to ensure only selected expiry ticks are sent
    async def _forward_filtered_option_tick(tick: Dict[str, Any]) -> None:
        try:
            sel = getattr(state, 'selected_expiry_iso', '') or ''
            # Detect presence of market depth payload
            has_depth = False
            try:
                has_depth = bool(
                    (tick.get('bids') and isinstance(tick.get('bids'), list) and len(tick.get('bids')) > 0) or
                    (tick.get('asks') and isinstance(tick.get('asks'), list) and len(tick.get('asks')) > 0) or
                    (tick.get('depth') and isinstance(tick.get('depth'), list) and len(tick.get('depth')) > 0)
                )
            except Exception:
                has_depth = False

            if sel:
                # Extract expiry from tick or alias
                raw_exp = tick.get('expiry_date') or ''
                if not raw_exp:
                    sym = str(tick.get('symbol') or '')
                    if '|' in sym:
                        parts = sym.split('|')
                        if len(parts) >= 2:
                            raw_exp = parts[1]
                norm = ''
                try:
                    if isinstance(raw_exp, str) and 'T' in raw_exp:
                        norm = raw_exp[:10]
                    elif isinstance(raw_exp, str) and '-' in raw_exp and len(raw_exp.split('-')) == 3 and raw_exp.split('-')[1].isalpha():
                        # DD-Mon-YYYY
                        from datetime import datetime
                        norm = datetime.strptime(raw_exp, '%d-%b-%Y').strftime('%Y-%m-%d')
                    else:
                        from datetime import datetime
                        norm = datetime.fromisoformat(str(raw_exp).replace('Z', '+00:00')).date().isoformat()
                except Exception:
                    norm = str(raw_exp)[:10]

                # If we cannot determine expiry but this is a depth tick, allow it and stamp current expiry
                if not norm and has_depth:
                    try:
                        tick['expiry_date'] = sel
                    except Exception:
                        pass
                elif norm and norm != sel:
                    # If the tick has a determinable expiry that doesn't match current selection, drop it
                    return

            await websocket.send_text(json.dumps(tick))
        except Exception as exc:
            log_exception(exc, context="ws_options.forward_filtered")

    # Register this filtered handler
    STREAM_MANAGER._option_tick_handlers = getattr(STREAM_MANAGER, '_option_tick_handlers', [])
    STREAM_MANAGER._option_tick_handlers.append(_forward_filtered_option_tick)

    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                msg = json.loads(msg_text)
            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "context": "parse",
                    "message": "Invalid JSON"
                }))
                continue

            action = (msg.get("action") or "").lower()

            if action == "subscribe_options":
                underlying = (msg.get("underlying") or "NIFTY").upper()
                
                # Map frontend symbols to Breeze API stock codes for options
                breeze_stock_code = underlying
                if underlying == "BANKNIFTY":
                    breeze_stock_code = "CNXBAN"
                elif underlying == "FINNIFTY":
                    breeze_stock_code = "NIFFIN"
                # NIFTY remains "NIFTY"
                
                expiry_date = msg.get("expiry_date")
                strikes = msg.get("strikes", [])
                right_req = (msg.get("right") or "both").lower()
                
                # Silence verbose subscription request log
                
                if not expiry_date or not strikes:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "subscribe_options",
                        "message": "expiry_date and strikes required"
                    }))
                    continue

                if not _is_market_open_ist():
                    # If market is closed, send cached last-known values for each requested strike
                    from ..services.quotes_cache import get_cached_quote
                    for strike in strikes:
                        try:
                            alias = f"{underlying}|{expiry_date}|CALL|{int(strike)}"
                            cached = get_cached_quote(alias)
                            if cached:
                                await websocket.send_text(json.dumps({
                                    "type": "tick",
                                    "symbol": alias,
                                    **cached,
                                    "note": "market closed; using cache"
                                }))
                            alias_put = f"{underlying}|{expiry_date}|PUT|{int(strike)}"
                            cached_p = get_cached_quote(alias_put)
                            if cached_p:
                                await websocket.send_text(json.dumps({
                                    "type": "tick",
                                    "symbol": alias_put,
                                    **cached_p,
                                    "note": "market closed; using cache"
                                }))
                        except Exception:
                            pass
                    await websocket.send_text(json.dumps({
                        "type": "info",
                        "message": "Market closed; option subscription may not receive live data"
                    }))
                    # Continue to subscribe as well to keep flow consistent

                try:
                    # Ensure Breeze WS is connected before subscribing
                    try:
                        STREAM_MANAGER.connect()
                    except Exception as exc:
                        log_exception(exc, context="ws_options.ensure_connect")
                        # Continue; subscribe_option will attempt to connect again if needed
                    
                    # Convert ISO expiry date to Breeze format (DD-Mon-YYYY) and compute keep key
                    from datetime import datetime
                    try:
                        if 'T' in expiry_date:
                            # Parse ISO format: 2025-09-09T06:00:00.000Z
                            dt = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
                            breeze_expiry = dt.strftime('%d-%b-%Y')
                        else:
                            breeze_expiry = expiry_date
                    except Exception as e:
                        # Keep quiet on parse errors to avoid terminal noise
                        breeze_expiry = expiry_date
                    
                    keep_iso = (expiry_date or '')[:10]
                    # Remember this connection's selected expiry (date-only)
                    try:
                        state.selected_expiry_iso = keep_iso
                    except Exception:
                        state.selected_expiry_iso = keep_iso
                    # Silent conversion info
                    # Ensure only this expiry remains subscribed
                    try:
                        STREAM_MANAGER.unsubscribe_options_except(keep_iso)
                    except Exception:
                        pass
                    
                    # Subscribe to option chain via stream manager
                    for strike in strikes:
                        # Subscribe only to requested side(s)
                        if right_req in ("call", "both"):
                            STREAM_MANAGER.subscribe_option(
                                stock_code=breeze_stock_code,
                                exchange_code="NFO",
                                expiry_date=breeze_expiry,
                                strike_price=str(strike),
                                right="call",
                                product_type="options"
                            )
                        if right_req in ("put", "both"):
                            STREAM_MANAGER.subscribe_option(
                                stock_code=breeze_stock_code,
                                exchange_code="NFO",
                                expiry_date=breeze_expiry,
                                strike_price=str(strike),
                                right="put",
                                product_type="options"
                            )
                    
                    # Also try subscribing with BSE exchange for market depth data
                    # Some options might have better market depth on BSE
                    try:
                        for strike in strikes:
                            if right_req in ("call", "both"):
                                STREAM_MANAGER.subscribe_option(
                                    stock_code=breeze_stock_code,
                                    exchange_code="BSE",
                                    expiry_date=breeze_expiry,
                                    strike_price=str(strike),
                                    right="call",
                                    product_type="options"
                                )
                            if right_req in ("put", "both"):
                                STREAM_MANAGER.subscribe_option(
                                    stock_code=breeze_stock_code,
                                    exchange_code="BSE",
                                    expiry_date=breeze_expiry,
                                    strike_price=str(strike),
                                    right="put",
                                    product_type="options"
                                )
                        # Silent BSE subscription info
                    except Exception as exc:
                        # Silent BSE failure info
                        pass
                    
                    response_msg = {
                        "type": "subscribed",
                        "underlying": underlying,
                        "expiry_date": expiry_date,
                        "strikes": strikes,
                        "message": f"Subscribed to {len(strikes)} strikes for {underlying} options"
                    }
                    await websocket.send_text(json.dumps(response_msg))
                except Exception as exc:
                    log_exception(exc, context="ws_options.subscribe_options")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "subscribe_options",
                        "message": str(exc)
                    }))

            elif action == "unsubscribe_options":
                try:
                    # Unsubscribe all option subscriptions
                    STREAM_MANAGER.unsubscribe_all_options()
                    await websocket.send_text(json.dumps({
                        "type": "unsubscribed",
                        "message": "All option subscriptions removed"
                    }))
                except Exception as exc:
                    log_exception(exc, context="ws_options.unsubscribe_options")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "unsubscribe_options",
                        "message": str(exc)
                    }))

            elif action == "subscribe_market_depth":
                underlying = (msg.get("underlying") or "NIFTY").upper()
                
                # Map frontend symbols to Breeze API stock codes for options
                breeze_stock_code = underlying
                if underlying == "BANKNIFTY":
                    breeze_stock_code = "CNXBAN"
                elif underlying == "FINNIFTY":
                    breeze_stock_code = "NIFFIN"
                # NIFTY remains "NIFTY"
                
                expiry_date = msg.get("expiry_date")
                strikes = msg.get("strikes", [])
                right_req = (msg.get("right") or "both").lower()
                
                # Silence verbose market depth request log
                
                if not expiry_date or not strikes:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "subscribe_market_depth",
                        "message": "expiry_date and strikes required"
                    }))
                    continue

                if not _is_market_open_ist():
                    await websocket.send_text(json.dumps({
                        "type": "info",
                        "message": "Market closed; market depth subscription may not receive live data"
                    }))

                try:
                    # Ensure Breeze WS is connected before subscribing
                    try:
                        STREAM_MANAGER.connect()
                    except Exception as exc:
                        log_exception(exc, context="ws_options.ensure_connect_market_depth")
                    
                    # Convert ISO expiry date to Breeze format (DD-Mon-YYYY)
                    from datetime import datetime
                    try:
                        if 'T' in expiry_date:
                            # Parse ISO format: 2025-09-09T06:00:00.000Z
                            dt = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
                            breeze_expiry = dt.strftime('%d-%b-%Y')
                        else:
                            breeze_expiry = expiry_date
                    except Exception as e:
                        # Keep quiet on parse errors to avoid terminal noise
                        breeze_expiry = expiry_date
                    
                    # Subscribe to market depth for option chain via stream manager
                    for strike in strikes:
                        # Subscribe only to requested side(s)
                        if right_req in ("call", "both"):
                            STREAM_MANAGER.subscribe_option_market_depth(
                                stock_code=breeze_stock_code,
                                exchange_code="NFO",
                                expiry_date=breeze_expiry,
                                strike_price=str(strike),
                                right="call",
                                product_type="options"
                            )
                        if right_req in ("put", "both"):
                            STREAM_MANAGER.subscribe_option_market_depth(
                                stock_code=breeze_stock_code,
                                exchange_code="NFO",
                                expiry_date=breeze_expiry,
                                strike_price=str(strike),
                                right="put",
                                product_type="options"
                            )
                    
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "message": f"Market depth subscribed for {len(strikes)} strikes",
                        "underlying": underlying,
                        "expiry_date": expiry_date,
                        "strikes": strikes
                    }))
                    
                except Exception as exc:
                    log_exception(exc, context="ws_options.subscribe_market_depth")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "subscribe_market_depth",
                        "message": str(exc)
                    }))

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "context": "action",
                    "message": "Unknown action. Use 'subscribe_options', 'subscribe_market_depth', or 'unsubscribe_options'"
                }))

    except WebSocketDisconnect:
        try:
            pass
        except Exception as exc:
            log_exception(exc, context="ws_options.disconnect_cleanup")
    finally:
        with contextlib.suppress(Exception):
            # Remove this connection's handler
            if hasattr(STREAM_MANAGER, '_option_tick_handlers'):
                try:
                    STREAM_MANAGER._option_tick_handlers.remove(_forward_filtered_option_tick)
                except ValueError:
                    pass
            STREAM_MANAGER.unregister_client(websocket)
            await websocket.close()


@router.websocket("/ws/ticks")
async def ws_ticks(websocket: WebSocket) -> None:
    await websocket.accept()
    state = ConnectionState()
    state.last_sent_ts_by_symbol = {}
    state.subscriptions = {}
    breeze_ws_connected = False
    loop = asyncio.get_running_loop()
    STREAM_MANAGER.set_loop(loop)
    STREAM_MANAGER.register_client(websocket, loop)

    def _extract_symbol_from_tick(tick: Dict[str, Any]) -> Optional[str]:
        raw = tick.get("stock_code") or tick.get("symbol") or tick.get("stock_code_name") or tick.get("security_id") or tick.get("scrip_id")
        if not raw:
            return state.symbol
        try:
            code = str(raw).upper().strip()
            if code.endswith(".NS"):
                code = code[:-3]
            return code
        except Exception:
            return state.symbol

    async def forward_tick(tick: Dict[str, Any]) -> None:
        now = time.monotonic() * 1000.0
        sym = _extract_symbol_from_tick(tick) or state.symbol or ""
        last = state.last_sent_ts_by_symbol.get(sym, 0.0) if state.last_sent_ts_by_symbol is not None else 0.0
        if now - last < state.min_interval_ms:
            return
        if state.last_sent_ts_by_symbol is not None:
            state.last_sent_ts_by_symbol[sym] = now

        normalized = {
            "type": "tick",
            "symbol": sym,
            "ltp": tick.get("last") or tick.get("ltp") or tick.get("close") or tick.get("open"),
            "close": tick.get("close"),
            "bid": tick.get("bPrice") or tick.get("best_bid_price"),
            "ask": tick.get("sPrice") or tick.get("best_ask_price"),
            "change_pct": tick.get("change") or tick.get("pChange"),
            "timestamp": tick.get("ltt") or tick.get("datetime") or tick.get("timestamp"),
        }
        await websocket.send_text(json.dumps(normalized))

    def _ensure_breeze_runtime() -> Optional[BreezeService]:
        """Ensure a BreezeService is available from runtime or .env fallback."""
        try:
            runtime = get_breeze()
            if runtime is not None:
                return runtime
            # No fallback - user must login first
            log_exception(Exception("No active Breeze session found"), context="ws_ticks.ensure_breeze_runtime")
        except Exception as exc:
            log_exception(exc, context="ws_ticks.ensure_breeze_runtime")
        return None

    async def send_last_close(symbol: str, exchange_code: str) -> None:
        """Send last close price using cached quote only."""
        cached = get_cached_quote(symbol)
        if cached:
            await websocket.send_text(json.dumps({
                "type": "tick",
                **cached,
                "note": "market closed; using cache"
            }))
        else:
            # No cached data available
            await websocket.send_text(json.dumps({
                "type": "info",
                "message": f"No cached data available for {symbol}",
            }))

    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                msg = json.loads(msg_text)
            except Exception:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "context": "parse",
                    "message": "Invalid JSON"
                }))
                continue

            action = (msg.get("action") or "").lower()

            if action == "subscribe":
                symbol = (msg.get("symbol") or "").upper()
                if not symbol:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "subscribe",
                        "message": "symbol required"
                    }))
                    continue
                state.symbol = symbol
                # Allow client to specify exchange/product; default to NSE/cash
                state.exchange_code = (msg.get("exchange_code") or "NSE").upper()
                state.product_type = (msg.get("product_type") or "cash").lower()

                if not _is_market_open_ist():
                    await send_last_close(symbol, state.exchange_code)
                    await websocket.send_text(json.dumps({
                        "type": "info",
                        "message": "Market closed; WS subscription skipped"
                    }))
                    continue

                await websocket.send_text(json.dumps({
                    "type": "info",
                    "message": "Subscribing via stream manager..."
                }))
                try:
                    STREAM_MANAGER.subscribe(symbol, state.exchange_code, state.product_type)
                except Exception as exc:
                    log_exception(exc, context="ws_ticks.manager_subscribe_single")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "manager_subscribe",
                        "message": str(exc)
                    }))

                await websocket.send_text(json.dumps({
                    "type": "subscribed",
                    "symbol": symbol
                }))
                # Ensure central stream subscription
                try:
                    STREAM_MANAGER.subscribe(symbol, state.exchange_code, state.product_type)
                except Exception as exc:
                    log_exception(exc, context="ws_ticks.manager_subscribe")

            elif action == "subscribe_many":
                items = msg.get("symbols") or []
                if not isinstance(items, list) or not items:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "subscribe_many",
                        "message": "symbols list required"
                    }))
                    continue

                if not _is_market_open_ist():
                    for it in items:
                        try:
                            code = str((it.get("stock_code") or it.get("symbol") or "")).upper()
                            if not code:
                                continue
                            ex = str((it.get("exchange_code") or "NSE")).upper()
                            await send_last_close(code, ex)
                        except Exception as exc:
                            log_exception(exc, context="ws_ticks.subscribe_many.closed")
                    await websocket.send_text(json.dumps({
                        "type": "info",
                        "message": "Market closed; WS subscription skipped"
                    }))
                    continue

                try:
                    STREAM_MANAGER.subscribe_many(items)
                    for it in items:
                        try:
                            code = str((it.get("stock_code") or it.get("symbol") or "")).upper()
                            if code:
                                await websocket.send_text(json.dumps({"type": "subscribed", "symbol": code}))
                        except Exception:
                            pass
                except Exception as exc:
                    log_exception(exc, context="ws_ticks.subscribe_many_manager")
                    await websocket.send_text(json.dumps({"type": "error", "context": "subscribe_many_manager", "message": str(exc)}))

            elif action == "unsubscribe":
                try:
                    if state.symbol and state.breeze:
                        state.breeze.client.unsubscribe_feeds(
                            exchange_code=state.exchange_code,
                            stock_code=state.symbol,
                            product_type=state.product_type
                        )
                        state.breeze.client.on_ticks = None
                        await websocket.send_text(json.dumps({
                            "type": "unsubscribed",
                            "symbol": state.symbol
                        }))
                        try:
                            STREAM_MANAGER.unsubscribe(state.symbol)
                        except Exception as exc:
                            log_exception(exc, context="ws_ticks.manager_unsubscribe")
                        state.symbol = None
                except Exception as exc:
                    log_exception(exc, context="ws_ticks.unsubscribe")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "context": "unsubscribe",
                        "message": str(exc)
                    }))
            elif action == "unsubscribe_many":
                items = msg.get("symbols") or []
                if not isinstance(items, list) or not items:
                    await websocket.send_text(json.dumps({"type": "error", "context": "unsubscribe_many", "message": "symbols list required"}))
                    continue
                try:
                    STREAM_MANAGER.unsubscribe_many(items)
                    for it in items:
                        try:
                            code = str((it.get("stock_code") or it.get("symbol") or "")).upper()
                            if code:
                                await websocket.send_text(json.dumps({"type": "unsubscribed", "symbol": code}))
                        except Exception:
                            pass
                except Exception as exc:
                    log_exception(exc, context="ws_ticks.unsubscribe_many")
                    await websocket.send_text(json.dumps({"type": "error", "context": "unsubscribe_many", "message": str(exc)}))
            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "context": "action",
                    "message": "Unknown action"
                }))

    except WebSocketDisconnect:
        try:
            pass
        except Exception as exc:
            log_exception(exc, context="ws_ticks.disconnect_cleanup")
    finally:
        with contextlib.suppress(Exception):
            STREAM_MANAGER.unregister_client(websocket)
            await websocket.close()
