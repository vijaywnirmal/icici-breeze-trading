from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from sqlalchemy import text

from ..utils.postgres import get_conn
from ..utils.response import error_response, success_response, log_exception
from ..utils.session import get_breeze
from ..utils.redis_config import (
    cache_market_status, get_cached_market_status, 
    cache_set, cache_get, make_key, CacheKeys
)
from .quotes import _is_market_open_ist


router = APIRouter(prefix="/api", tags=["instruments"])


@router.get("/market/status")
def market_status() -> Dict[str, Any]:
    """Check if the market is currently open."""
    try:
        # Try to get cached market status first
        cached_status = get_cached_market_status()
        if cached_status:
            return success_response("Market status", **cached_status)
        
        # Calculate market status
        is_open = _is_market_open_ist()
        status_data = {
            "is_open": is_open, 
            "status": "open" if is_open else "closed"
        }
        
        # Cache the result for 1 minute
        cache_market_status(status_data, ttl=60)
        
        return success_response("Market status", **status_data)
    except Exception as exc:
        log_exception(exc, context="market.status")
        return error_response("Failed to check market status", error=str(exc))


@router.get("/instruments/search")
def instruments_search(
    q: str = Query(..., description="Search query for symbol or company name"),
    exchange: Optional[str] = Query(None, description="Filter by exchange (NSE, BSE)"),
    websocket_only: bool = Query(False, description="Only return WebSocket-enabled instruments"),
    limit: int = Query(20, description="Maximum number of results")
) -> Dict[str, Any]:
    """Search instruments by symbol or company name.

    Example: /api/instruments/search?q=RELIANCE&exchange=NSE&websocket_only=true&limit=10
    """
    try:
        if not q or len(q.strip()) < 2:
            return error_response("Search query must be at least 2 characters")

        # Create cache key based on search parameters
        cache_key = make_key(CacheKeys.INSTRUMENTS_SEARCH, f"{q}_{exchange}_{websocket_only}_{limit}")
        
        # Try to get cached results first
        cached_results = cache_get(cache_key)
        if cached_results:
            return success_response("Instruments search", **cached_results)

        search_term = f"%{q.strip().upper()}%"
        
        where_conditions = [
            "UPPER(symbol) LIKE :search_term OR UPPER(company_name) LIKE :search_term OR UPPER(short_name) LIKE :search_term"
        ]
        params: Dict[str, Any] = {"search_term": search_term}
        
        if exchange:
            where_conditions.append("exchange_code = :exchange")
            params["exchange"] = exchange.upper()
            
        if websocket_only:
            where_conditions.append("websocket_enabled = TRUE")

        sql = text(f"""
            SELECT token, symbol, short_name, company_name, series, isin, lot_size, exchange, exchange_code, websocket_enabled
            FROM instruments 
            WHERE {' AND '.join(where_conditions)}
            ORDER BY 
                websocket_enabled DESC,
                CASE 
                    WHEN UPPER(symbol) = :exact_term THEN 1
                    WHEN UPPER(symbol) LIKE :prefix_term THEN 2
                    WHEN UPPER(company_name) LIKE :prefix_term THEN 3
                    ELSE 4
                END,
                symbol
            LIMIT :limit
        """)
        
        params.update({
            "exact_term": q.strip().upper(),
            "prefix_term": f"{q.strip().upper()}%",
            "limit": limit,
        })

        with get_conn() as conn:
            if conn is None:
                return error_response("Database not configured")
            rows = conn.execute(sql, params).fetchall()
            items = [
                {
                    "token": r[0],
                    "symbol": r[1],
                    "short_name": r[2],
                    "company_name": r[3],
                    "series": r[4],
                    "isin": r[5],
                    "lot_size": r[6],
                    "exchange": r[7],
                    "exchange_code": r[8],
                    "websocket_enabled": r[9],
                }
                for r in rows
            ]
            
            result_data = {"items": items, "total": len(items)}
            
            # Cache the results for 5 minutes
            cache_set(cache_key, result_data, ttl=300)
            
            return success_response("Instruments search", **result_data)
    except Exception as exc:
        log_exception(exc, context="instruments.search")
        return error_response("Failed to search instruments", error=str(exc))


@router.get("/instruments/websocket-enabled")
def get_websocket_enabled_instruments(
    exchange: Optional[str] = Query(None, description="Filter by exchange (NSE, BSE)"),
    limit: int = Query(1000, description="Maximum number of results")
) -> Dict[str, Any]:
    """Get all WebSocket-enabled instruments for bulk subscription.
    
    This endpoint returns all instruments that are enabled for WebSocket streaming,
    formatted for easy bulk subscription via the WebSocket API.
    """
    try:
        where_conditions = ["websocket_enabled = TRUE"]
        params: Dict[str, Any] = {}
        
        if exchange:
            where_conditions.append("exchange_code = :exchange")
            params["exchange"] = exchange.upper()

        sql = text(f"""
            SELECT token, symbol, short_name, company_name, exchange, exchange_code
            FROM instruments 
            WHERE {' AND '.join(where_conditions)}
            ORDER BY exchange, symbol
            LIMIT :limit
        """)
        
        params["limit"] = limit

        with get_conn() as conn:
            result = conn.execute(sql, params)
            rows = result.fetchall()
            
            instruments = []
            for row in rows:
                # Format for WebSocket subscription
                instrument = {
                    "token": row.token,
                    "symbol": row.symbol,
                    "stock_code": row.symbol,  # For WebSocket compatibility
                    "company_name": row.company_name,
                    "short_name": row.short_name,
                    "exchange": row.exchange,
                    "exchange_code": row.exchange_code or row.exchange,
                    "product_type": "cash"  # Default for equity
                }
                instruments.append(instrument)

            return success_response({
                "instruments": instruments,
                "count": len(instruments),
                "exchange_filter": exchange,
                "websocket_ready": True
            })

    except Exception as exc:
        log_exception(exc, context="get_websocket_enabled_instruments")
        return error_response("Failed to fetch WebSocket-enabled instruments", error=str(exc))


@router.get("/instruments/live-trading")
def live_trading_instruments(
    q: str = Query(..., description="Search query for company name or symbol"),
    limit: int = Query(20, description="Maximum number of results")
) -> Dict[str, Any]:
    """Search WebSocket-enabled instruments for Live Trading interface.
    
    This endpoint is specifically designed for the Live Trading search functionality,
    returning only instruments that are enabled for real-time WebSocket streaming.
    """
    try:
        if not q or len(q.strip()) < 2:
            return error_response("Search query must be at least 2 characters")

        search_term = f"%{q.strip().upper()}%"
        
        sql = text("""
            SELECT token, token as symbol, company_name
            FROM instruments 
            WHERE websocket_enabled = TRUE 
            AND (UPPER(token) LIKE :search_term OR UPPER(company_name) LIKE :search_term)
            ORDER BY 
                CASE 
                    WHEN UPPER(company_name) LIKE :prefix_term THEN 1
                    WHEN UPPER(token) = :exact_term THEN 2
                    WHEN UPPER(token) LIKE :prefix_term THEN 3
                    ELSE 4
                END,
                company_name, token
            LIMIT :limit
        """)
        
        params = {
            "search_term": search_term,
            "exact_term": q.strip().upper(),
            "prefix_term": f"{q.strip().upper()}%",
            "limit": limit
        }

        with get_conn() as conn:
            if conn is None:
                return error_response("Database not configured")
            rows = conn.execute(sql, params).fetchall()
            items = [
                {
                    "token": r[0],
                    "symbol": r[1],
                    "short_name": r[1],  # Add short_name for compatibility
                    "company_name": r[2],
                    "exchange": "NSE",  # Default to NSE since we removed the exchange filter
                    "exchange_code": "NSE",  # Add exchange_code for compatibility
                }
                for r in rows
            ]
            return success_response("Live trading instruments", items=items, total=len(items))
    except Exception as exc:
        log_exception(exc, context="instruments.live_trading")
        return error_response("Failed to search live trading instruments", error=str(exc))


@router.get("/instruments/lookup")
def instruments_lookup(tokens: str = Query(..., description="Comma-separated list of tokens"), exchange: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Resolve ICICI tokens to symbol/company/exchange from instruments table.

    Example: /api/instruments/lookup?tokens=800078,10515
    """
    try:
        token_list = [t.strip() for t in (tokens or "").split(",") if t.strip()]
        if not token_list:
            return error_response("No tokens provided")

        where = "token = ANY(:tokens)"
        params: Dict[str, Any] = {"tokens": token_list}
        if exchange:
            where += " AND exchange = :exchange"
            params["exchange"] = exchange.upper()

        sql = text(
            f"SELECT token, symbol, company_name, series, isin, lot_size, exchange FROM instruments WHERE {where}"
        )

        with get_conn() as conn:
            if conn is None:
                return error_response("Database not configured")
            rows = conn.execute(sql, params).fetchall()
            items = [
                {
                    "token": r[0],
                    "symbol": r[1],
                    "company_name": r[2],
                    "series": r[3],
                    "isin": r[4],
                    "lot_size": r[5],
                    "exchange": r[6],
                }
                for r in rows
            ]
            return success_response("Instruments lookup", items=items)
    except Exception as exc:
        log_exception(exc, context="instruments.lookup")
        return error_response("Failed to lookup instruments", error=str(exc))


@router.post("/instruments/subscribe-all")
def subscribe_all_instruments(
    exchange: Optional[str] = Query(None, description="Filter by exchange (NSE, BSE)"),
    websocket_only: bool = Query(True, description="Only subscribe to WebSocket-enabled instruments"),
    limit: int = Query(1000, description="Maximum number of instruments to subscribe to")
) -> Dict[str, Any]:
    """Subscribe to all instruments from the database using breeze.subscribe_feeds."""
    try:
        # Get Breeze service
        breeze = get_breeze()
        if not breeze:
            return error_response("No active Breeze session found. Please login first.")
        
        # Build query to get instruments
        where_conditions = []
        params = {}
        
        if exchange:
            where_conditions.append("exchange_code = :exchange")
            params["exchange"] = exchange.upper()
        
        if websocket_only:
            where_conditions.append("websocket_enabled = true")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        with get_conn() as conn:
            if conn is None:
                return error_response("Database connection failed")
            
            # Get all tokens from instruments table
            query = f"""
                SELECT token, short_name, company_name, exchange_code
                FROM instruments 
                WHERE {where_clause}
                ORDER BY exchange_code, company_name
                LIMIT :limit
            """
            params["limit"] = limit
            
            result = conn.execute(text(query), params)
            rows = result.fetchall()
            
            if not rows:
                return success_response("No instruments found", subscribed_count=0, tokens=[])
            
            # Extract tokens for subscription
            tokens = [row[0] for row in rows]  # row[0] is the token column
            
            # Subscribe to all tokens using breeze.subscribe_feeds
            try:
                breeze.client.subscribe_feeds(stock_token=tokens)
                
                # Log the subscription
                log_exception(
                    Exception(f"Subscribed to {len(tokens)} instruments"), 
                    context="subscribe_all_instruments",
                    exchange=exchange,
                    websocket_only=websocket_only,
                    token_count=len(tokens)
                )
                
                return success_response(
                    f"Successfully subscribed to {len(tokens)} instruments",
                    subscribed_count=len(tokens),
                    tokens=tokens[:10],  # Show first 10 tokens as sample
                    exchange=exchange,
                    websocket_only=websocket_only
                )
                
            except Exception as subscribe_exc:
                log_exception(subscribe_exc, context="breeze.subscribe_feeds")
                return error_response(
                    f"Failed to subscribe to instruments: {str(subscribe_exc)}",
                    error=str(subscribe_exc),
                    token_count=len(tokens)
                )
                
    except Exception as exc:
        log_exception(exc, context="instruments.subscribe_all")
        return error_response("Failed to subscribe to all instruments", error=str(exc))


@router.get("/instruments/tokens")
def get_instrument_tokens(
    exchange: Optional[str] = Query(None, description="Filter by exchange (NSE, BSE)"),
    websocket_only: bool = Query(True, description="Only return WebSocket-enabled instruments"),
    limit: int = Query(100, description="Maximum number of tokens to return")
) -> Dict[str, Any]:
    """Get all instrument tokens from the database without subscribing."""
    try:
        # Build query to get instruments
        where_conditions = []
        params = {}
        
        if exchange:
            where_conditions.append("exchange_code = :exchange")
            params["exchange"] = exchange.upper()
        
        if websocket_only:
            where_conditions.append("websocket_enabled = true")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        with get_conn() as conn:
            if conn is None:
                return error_response("Database connection failed")
            
            # Get all tokens from instruments table
            query = f"""
                SELECT token, short_name, company_name, exchange_code
                FROM instruments 
                WHERE {where_clause}
                ORDER BY exchange_code, company_name
                LIMIT :limit
            """
            params["limit"] = limit
            
            result = conn.execute(text(query), params)
            rows = result.fetchall()
            
            if not rows:
                return success_response("No instruments found", count=0, tokens=[])
            
            # Format response
            items = [
                {
                    "token": row[0],
                    "short_name": row[1],
                    "company_name": row[2],
                    "exchange": row[3]
                }
                for row in rows
            ]
            
            return success_response(
                f"Found {len(items)} instruments",
                count=len(items),
                tokens=[item["token"] for item in items],
                items=items
            )
                
    except Exception as exc:
        log_exception(exc, context="instruments.get_tokens")
        return error_response("Failed to get instrument tokens", error=str(exc))


@router.get("/nifty50/stocks")
def get_nifty50_stocks() -> Dict[str, Any]:
    """Get Nifty50 stocks list for ticker display.
    
    Returns a list of Nifty50 stocks with their tokens and symbols.
    """
    try:
        # Define a basic list of Nifty50 stocks
        # This is a simplified list - in production, you might want to fetch this from a more reliable source
        nifty50_stocks = [
            {"symbol": "RELIANCE", "token": "2885633", "company_name": "RELIANCE INDUSTRIES LTD"},
            {"symbol": "TCS", "token": "2953217", "company_name": "TATA CONSULTANCY SERVICES LTD"},
            {"symbol": "HDFCBANK", "token": "3419649", "company_name": "HDFC BANK LTD"},
            {"symbol": "INFY", "token": "408065", "company_name": "INFOSYS LTD"},
            {"symbol": "HINDUNILVR", "token": "356865", "company_name": "HINDUSTAN UNILEVER LTD"},
            {"symbol": "ITC", "token": "424961", "company_name": "ITC LTD"},
            {"symbol": "SBIN", "token": "779521", "company_name": "STATE BANK OF INDIA"},
            {"symbol": "BHARTIARTL", "token": "2714625", "company_name": "BHARTI AIRTEL LTD"},
            {"symbol": "KOTAKBANK", "token": "492033", "company_name": "KOTAK MAHINDRA BANK LTD"},
            {"symbol": "LT", "token": "2933761", "company_name": "LARSEN & TOUBRO LTD"},
            {"symbol": "ASIANPAINT", "token": "60417", "company_name": "ASIAN PAINTS LTD"},
            {"symbol": "AXISBANK", "token": "1510401", "company_name": "AXIS BANK LTD"},
            {"symbol": "MARUTI", "token": "2815745", "company_name": "MARUTI SUZUKI INDIA LTD"},
            {"symbol": "SUNPHARMA", "token": "857857", "company_name": "SUN PHARMACEUTICAL INDUSTRIES LTD"},
            {"symbol": "TITAN", "token": "897537", "company_name": "TITAN COMPANY LTD"},
            {"symbol": "ULTRACEMCO", "token": "2952193", "company_name": "ULTRATECH CEMENT LTD"},
            {"symbol": "WIPRO", "token": "969473", "company_name": "WIPRO LTD"},
            {"symbol": "NESTLEIND", "token": "4598529", "company_name": "NESTLE INDIA LTD"},
            {"symbol": "POWERGRID", "token": "3834113", "company_name": "POWER GRID CORP OF INDIA LTD"},
            {"symbol": "NTPC", "token": "2977281", "company_name": "NTPC LTD"},
            {"symbol": "ONGC", "token": "633601", "company_name": "OIL & NATURAL GAS CORP LTD"},
            {"symbol": "TECHM", "token": "3465729", "company_name": "TECH MAHINDRA LTD"},
            {"symbol": "TATAMOTORS", "token": "884737", "company_name": "TATA MOTORS LTD"},
            {"symbol": "JSWSTEEL", "token": "3001089", "company_name": "JSW STEEL LTD"},
            {"symbol": "BAJFINANCE", "token": "81153", "company_name": "BAJAJ FINANCE LTD"},
            {"symbol": "HCLTECH", "token": "1850625", "company_name": "HCL TECHNOLOGIES LTD"},
            {"symbol": "DRREDDY", "token": "225537", "company_name": "DR REDDYS LABORATORIES LTD"},
            {"symbol": "BAJAJFINSV", "token": "4267265", "company_name": "BAJAJ FINSERV LTD"},
            {"symbol": "ADANIPORTS", "token": "3861249", "company_name": "ADANI PORTS & SPECIAL ECONOMIC ZONE LTD"},
            {"symbol": "COALINDIA", "token": "5215745", "company_name": "COAL INDIA LTD"},
            {"symbol": "TATASTEEL", "token": "895745", "company_name": "TATA STEEL LTD"},
            {"symbol": "GRASIM", "token": "315393", "company_name": "GRASIM INDUSTRIES LTD"},
            {"symbol": "M&M", "token": "2815745", "company_name": "MAHINDRA & MAHINDRA LTD"},
            {"symbol": "BRITANNIA", "token": "140033", "company_name": "BRITANNIA INDUSTRIES LTD"},
            {"symbol": "EICHERMOT", "token": "232961", "company_name": "EICHER MOTORS LTD"},
            {"symbol": "HEROMOTOCO", "token": "345089", "company_name": "HERO MOTOCORP LTD"},
            {"symbol": "DIVISLAB", "token": "2800641", "company_name": "DIVIS LABORATORIES LTD"},
            {"symbol": "CIPLA", "token": "177665", "company_name": "CIPLA LTD"},
            {"symbol": "SHREECEM", "token": "794369", "company_name": "SHREE CEMENT LTD"},
            {"symbol": "APOLLOHOSP", "token": "3861249", "company_name": "APOLLO HOSPITALS ENTERPRISE LTD"},
            {"symbol": "BAJAJ-AUTO", "token": "4267265", "company_name": "BAJAJ AUTO LTD"},
            {"symbol": "INDUSINDBK", "token": "3001089", "company_name": "INDUSIND BANK LTD"},
            {"symbol": "TATACONSUM", "token": "884737", "company_name": "TATA CONSUMER PRODUCTS LTD"},
            {"symbol": "BPCL", "token": "633601", "company_name": "BHARAT PETROLEUM CORP LTD"},
            {"symbol": "HINDALCO", "token": "1850625", "company_name": "HINDALCO INDUSTRIES LTD"},
            {"symbol": "UPL", "token": "225537", "company_name": "UPL LTD"},
            {"symbol": "SBILIFE", "token": "4267265", "company_name": "SBI LIFE INSURANCE COMPANY LTD"},
            {"symbol": "ICICIBANK", "token": "3861249", "company_name": "ICICI BANK LTD"},
            {"symbol": "SHRIRAMFIN", "token": "5215745", "company_name": "SHRIRAM FINANCE LTD"},
            {"symbol": "ADANIENT", "token": "895745", "company_name": "ADANI ENTERPRISES LTD"},
            {"symbol": "HDFCLIFE", "token": "315393", "company_name": "HDFC LIFE INSURANCE COMPANY LTD"}
        ]
        
        return success_response(
            "Nifty50 stocks list",
            count=len(nifty50_stocks),
            stocks=nifty50_stocks
        )
        
    except Exception as exc:
        log_exception(exc, context="instruments.get_nifty50_stocks")
        return error_response("Failed to get Nifty50 stocks", error=str(exc))


def _example_join_trades() -> str:
    """Illustrative SQL for joining trades/orders that store token to instruments.

    This is not executed here but provided for reference.
    """
    return (
        "SELECT t.trade_id, i.symbol, i.company_name, i.exchange "
        "FROM trades t JOIN instruments i ON t.token = i.token"
    )


