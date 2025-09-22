from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import text

from ..utils.postgres import get_conn
from ..utils.response import success_response, error_response, log_exception
from ..services.ws_stream_manager import STREAM_MANAGER
from .quotes import _is_market_open_ist
from ..utils.session import get_breeze

router = APIRouter(prefix="/api", tags=["option-chain"])


def get_next_expiry_date() -> str:
    """Get the next Tuesday expiry date for options (weekly for Nifty 50)."""
    today = datetime.now()
    
    # Find next Tuesday
    days_ahead = 1 - today.weekday()  # Tuesday is 1
    if days_ahead <= 0:  # Target day already happened this week
        days_ahead += 7
    
    next_tuesday = today + timedelta(days=days_ahead)
    return next_tuesday.strftime("%Y-%m-%dT06:00:00.000Z")


def get_monthly_expiry_date() -> str:
    """Get the last Tuesday of the current month for Bank Nifty and FIN NIFTY options."""
    today = datetime.now()
    
    # Get the last day of current month
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    
    last_day_of_month = next_month - timedelta(days=1)
    
    # Find the last Tuesday of the month
    # Start from the last day and work backwards to find the last Tuesday
    current_date = last_day_of_month
    while current_date.weekday() != 1:  # Tuesday is 1
        current_date -= timedelta(days=1)
    
    # If the last Tuesday has already passed this month, get the last Tuesday of next month
    if current_date < today:
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        
        next_month_last_day = next_month - timedelta(days=1)
        current_date = next_month_last_day
        while current_date.weekday() != 1:  # Tuesday is 1
            current_date -= timedelta(days=1)
    
    return current_date.strftime("%Y-%m-%dT06:00:00.000Z")


def round_to_nearest_50(price: float) -> int:
    """Round price to the nearest 50."""
    return int(round(price / 50) * 50)


def round_to_nearest_100(price: float) -> int:
    """Round price to the nearest 100."""
    return int(round(price / 100) * 100)


def calculate_nifty_strikes(nifty_price: float) -> Dict[str, Any]:
    """
    Calculate 7 strike prices based on current Nifty price:
    - 1 ATM (At The Money) - closest to current price
    - 3 ITM (In The Money) - below ATM for calls, above ATM for puts
    - 3 OTM (Out The Money) - above ATM for calls, below ATM for puts
    
    All strikes are rounded to nearest 50.
    """
    # Round current price to nearest 50 to get ATM strike
    atm_strike = round_to_nearest_50(nifty_price)
    
    # Calculate strikes
    strikes = []
    
    # 3 ITM strikes (below ATM)
    for i in range(3, 0, -1):
        itm_strike = atm_strike - (i * 50)
        strikes.append(itm_strike)
    
    # ATM strike
    strikes.append(atm_strike)
    
    # 3 OTM strikes (above ATM)
    for i in range(1, 4):
        otm_strike = atm_strike + (i * 50)
        strikes.append(otm_strike)
    
    # Sort strikes
    strikes.sort()
    
    # Create call and put data structures
    calls = []
    puts = []
    
    for strike in strikes:
        # Determine if ITM, ATM, or OTM for calls
        if strike < atm_strike:
            call_type = "ITM"
        elif strike == atm_strike:
            call_type = "ATM"
        else:
            call_type = "OTM"
        
        # Determine if ITM, ATM, or OTM for puts
        if strike > atm_strike:
            put_type = "ITM"
        elif strike == atm_strike:
            put_type = "ATM"
        else:
            put_type = "OTM"
        
        # Create call option data
        calls.append({
            "strike_price": strike,
            "type": call_type,
            "right": "call",
            "ltp": 0,
            "volume": 0,
            "open_interest": 0,
            "change": 0,
            "change_percent": 0,
            "best_bid_price": 0,
            "best_offer_price": 0,
            "last_traded_time": None,
            "token": None,
        })
        
        # Create put option data
        puts.append({
            "strike_price": strike,
            "type": put_type,
            "right": "put",
            "ltp": 0,
            "volume": 0,
            "open_interest": 0,
            "change": 0,
            "change_percent": 0,
            "best_bid_price": 0,
            "best_offer_price": 0,
            "last_traded_time": None,
            "token": None,
        })
    
    return {
        "strikes": strikes,
        "atm_strike": atm_strike,
        "calls": calls,
        "puts": puts,
        "nifty_price": nifty_price
    }


def calculate_finnifty_strikes(finnifty_price: float) -> Dict[str, Any]:
    """
    Calculate 7 strike prices based on current FIN NIFTY price:
    - 1 ATM (At The Money) - closest to current price
    - 3 ITM (In The Money) - below ATM for calls, above ATM for puts
    - 3 OTM (Out The Money) - above ATM for calls, below ATM for puts
    
    All strikes are rounded to nearest 50.
    """
    # Round current price to nearest 50 to get ATM strike
    atm_strike = round_to_nearest_50(finnifty_price)
    
    # Calculate strikes
    strikes = []
    
    # 3 ITM strikes (below ATM)
    for i in range(3, 0, -1):
        itm_strike = atm_strike - (i * 50)
        strikes.append(itm_strike)
    
    # ATM strike
    strikes.append(atm_strike)
    
    # 3 OTM strikes (above ATM)
    for i in range(1, 4):
        otm_strike = atm_strike + (i * 50)
        strikes.append(otm_strike)
    
    # Create calls and puts data
    calls = []
    puts = []
    
    for strike in strikes:
        # Create call option data
        call_data = {
            "strike_price": strike,
            "last_price": 0.0,
            "volume": 0,
            "open_interest": 0,
            "change": 0.0,
            "change_percent": 0.0
        }
        calls.append(call_data)
        
        # Create put option data
        put_data = {
            "strike_price": strike,
            "last_price": 0.0,
            "volume": 0,
            "open_interest": 0,
            "change": 0.0,
            "change_percent": 0.0
        }
        puts.append(put_data)
    
    return {
        "calls": calls,
        "puts": puts,
        "underlying_price": finnifty_price,
        "atm_strike": atm_strike
    }


def calculate_banknifty_strikes(banknifty_price: float) -> Dict[str, Any]:
    """
    Calculate 7 strike prices based on current Bank Nifty price:
    - 1 ATM (At The Money) - closest to current price
    - 3 ITM (In The Money) - below ATM for calls, above ATM for puts
    - 3 OTM (Out The Money) - above ATM for calls, below ATM for puts
    
    All strikes are rounded to nearest 100.
    """
    # Round current price to nearest 100 to get ATM strike
    atm_strike = round_to_nearest_100(banknifty_price)
    
    # Calculate strikes
    strikes = []
    
    # 3 ITM strikes (below ATM)
    for i in range(3, 0, -1):
        itm_strike = atm_strike - (i * 100)
        strikes.append(itm_strike)
    
    # ATM strike
    strikes.append(atm_strike)
    
    # 3 OTM strikes (above ATM)
    for i in range(1, 4):
        otm_strike = atm_strike + (i * 100)
        strikes.append(otm_strike)
    
    # Sort strikes
    strikes.sort()
    
    # Create call and put data structures
    calls = []
    puts = []
    
    for strike in strikes:
        # Determine if ITM, ATM, or OTM for calls
        if strike < atm_strike:
            call_type = "ITM"
        elif strike == atm_strike:
            call_type = "ATM"
        else:
            call_type = "OTM"
        
        # Determine if ITM, ATM, or OTM for puts
        if strike > atm_strike:
            put_type = "ITM"
        elif strike == atm_strike:
            put_type = "ATM"
        else:
            put_type = "OTM"
        
        # Create call option data
        calls.append({
            "strike_price": strike,
            "type": call_type,
            "right": "call",
            "ltp": 0,
            "volume": 0,
            "open_interest": 0,
            "change": 0,
            "change_percent": 0,
            "best_bid_price": 0,
            "best_offer_price": 0,
            "last_traded_time": None,
            "token": None,
        })
        
        # Create put option data
        puts.append({
            "strike_price": strike,
            "type": put_type,
            "right": "put",
            "ltp": 0,
            "volume": 0,
            "open_interest": 0,
            "change": 0,
            "change_percent": 0,
            "best_bid_price": 0,
            "best_offer_price": 0,
            "last_traded_time": None,
            "token": None,
        })
    
    return {
        "strikes": strikes,
        "atm_strike": atm_strike,
        "calls": calls,
        "puts": puts,
        "banknifty_price": banknifty_price
    }


@router.get("/option-chain/nifty-strikes")
def get_nifty_strikes(
    nifty_price: Optional[float] = Query(None, description="Current Nifty 50 price (if not provided, will fetch from Breeze)")
) -> Dict[str, Any]:
    """Get Nifty 50 option chain data with real market data."""
    try:
        # Get current Nifty price
        current_price = nifty_price
        if current_price is None:
            # Fetch from Breeze if not provided
            breeze = get_breeze()
            if breeze:
                try:
                    nifty_quote = breeze.client.get_quotes(
                        stock_code="NIFTY",
                        exchange_code="NSE",
                        product_type="cash"
                    )
                    if nifty_quote and isinstance(nifty_quote, dict) and nifty_quote.get("Success"):
                        success_data = nifty_quote.get("Success", [])
                        if isinstance(success_data, list) and success_data:
                            current_price = success_data[0].get("ltp", 24741)
                    elif nifty_quote and isinstance(nifty_quote, list) and nifty_quote:
                        current_price = nifty_quote[0].get("ltp", 24741)
                except Exception as e:
                    log_exception(e, context="option_chain.get_nifty_price")
                    current_price = 24741  # Fallback to yesterday's close
            else:
                current_price = 24741  # Fallback to yesterday's close
        
        # Ensure we have a valid price
        if not current_price or current_price <= 0:
            current_price = 24741
        
        # Calculate strikes for the option chain
        # The websocket subscription will populate real-time data
        strike_data = calculate_nifty_strikes(current_price)
        expiry_date = get_next_expiry_date()
        is_open = _is_market_open_ist()
        
        # Always return calculated strikes - websocket will update with real data
        options_data = {
            "calls": strike_data["calls"],
            "puts": strike_data["puts"],
            "expiry_date": expiry_date,
            "underlying": "NIFTY 50",
            "underlying_price": current_price,
            "atm_strike": strike_data["atm_strike"],
            "strikes": strike_data["strikes"],
            "market_open": is_open,
        }
        
        return success_response("Nifty 50 option chain data", **options_data)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_nifty_strikes")
        return error_response("Failed to fetch Nifty option chain", error=str(exc))


@router.get("/option-chain/banknifty-strikes")
def get_banknifty_strikes(
    banknifty_price: Optional[float] = Query(None, description="Current Bank Nifty price (if not provided, will fetch from Breeze)")
) -> Dict[str, Any]:
    """Get calculated Bank Nifty strike prices (7 strikes: ATM + 3 ITM + 3 OTM)."""
    try:
        # Get current Bank Nifty price
        current_price = banknifty_price
        if current_price is None:
            # Fetch from Breeze if not provided
            breeze = get_breeze()
            if breeze:
                try:
                    banknifty_quote = breeze.client.get_quotes(
                        stock_code="CNXBAN",
                        exchange_code="NSE",
                        product_type="cash"
                    )
                    if banknifty_quote and isinstance(banknifty_quote, dict) and banknifty_quote.get("Success"):
                        success_data = banknifty_quote.get("Success", [])
                        if isinstance(success_data, list) and success_data:
                            current_price = success_data[0].get("ltp", 52000)
                    elif banknifty_quote and isinstance(banknifty_quote, list) and banknifty_quote:
                        current_price = banknifty_quote[0].get("ltp", 52000)
                except Exception as e:
                    log_exception(e, context="option_chain.get_banknifty_price")
                    current_price = 52000  # Fallback to default Bank Nifty price
            else:
                current_price = 52000  # Fallback to default Bank Nifty price
        
        # Ensure we have a valid price
        if not current_price or current_price <= 0:
            current_price = 52000
        
        # Calculate strikes for the option chain
        # The websocket subscription will populate real-time data
        strike_data = calculate_banknifty_strikes(current_price)
        expiry_date = get_monthly_expiry_date()
        is_open = _is_market_open_ist()
        
        # Always return calculated strikes - websocket will update with real data
        options_data = {
            "calls": strike_data["calls"],
            "puts": strike_data["puts"],
            "expiry_date": expiry_date,
            "underlying": "BANK NIFTY",
            "underlying_price": current_price,
            "atm_strike": strike_data["atm_strike"],
            "strikes": strike_data["strikes"],
            "market_open": is_open,
        }
        
        return success_response("Bank Nifty option chain data", **options_data)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_banknifty_strikes")
        return error_response("Failed to calculate Bank Nifty strikes", error=str(exc))

@router.get("/option-chain/finnifty-strikes")
def get_finnifty_strikes(
    finnifty_price: Optional[float] = Query(None, description="Current FIN NIFTY price (if not provided, will fetch from Breeze)")
) -> Dict[str, Any]:
    """Get calculated FIN NIFTY strike prices (7 strikes: ATM + 3 ITM + 3 OTM)."""
    try:
        # Get current FIN NIFTY price
        current_price = finnifty_price
        if current_price is None:
            # Fetch from Breeze if not provided
            breeze = get_breeze()
            if breeze:
                try:
                    finnifty_quote = breeze.client.get_quotes(
                        stock_code="NIFFIN",
                        exchange_code="NSE",
                        product_type="cash"
                    )
                    if finnifty_quote and isinstance(finnifty_quote, dict) and finnifty_quote.get("Success"):
                        success_data = finnifty_quote.get("Success", [])
                        if isinstance(success_data, list) and success_data:
                            current_price = success_data[0].get("ltp", 20000)
                    elif finnifty_quote and isinstance(finnifty_quote, list) and finnifty_quote:
                        current_price = finnifty_quote[0].get("ltp", 20000)
                except Exception as e:
                    log_exception(e, context="option_chain.get_finnifty_price")
                    current_price = 20000  # Fallback to default FIN NIFTY price
            else:
                current_price = 20000  # Fallback to default FIN NIFTY price
        
        # Ensure we have a valid price
        if not current_price or current_price <= 0:
            current_price = 20000
        
        # Calculate strikes for the option chain
        # The websocket subscription will populate real-time data
        strike_data = calculate_finnifty_strikes(current_price)
        expiry_date = get_monthly_expiry_date()
        is_open = _is_market_open_ist()
        
        # Always return calculated strikes - websocket will update with real data
        options_data = {
            "calls": strike_data["calls"],
            "puts": strike_data["puts"],
            "expiry_date": expiry_date,
            "underlying": "FIN NIFTY",
            "underlying_price": current_price,
            "market_open": is_open,
        }
        
        return success_response("FIN NIFTY option chain data", **options_data)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_finnifty_strikes")
        return error_response("Failed to calculate FIN NIFTY strikes", error=str(exc))

@router.get("/option-chain/nifty50")
def get_nifty50_option_chain(
    expiry_date: Optional[str] = Query(None, description="Expiry date in ISO format"),
    right: Optional[str] = Query(None, description="Option type: call or put"),
    strike_price: Optional[float] = Query(None, description="Strike price filter")
) -> Dict[str, Any]:
    """Get Nifty 50 option chain data - empty data structure for WebSocket population."""
    try:
        # Use next Tuesday if no expiry date provided
        if not expiry_date:
            expiry_date = get_next_expiry_date()
        
        is_open = _is_market_open_ist()

        # Return empty data structure - will be populated by WebSocket
        options_data = {
            "calls": [],
            "puts": [],
            "expiry_date": expiry_date,
            "underlying": "NIFTY 50",
            "underlying_price": 24700,  # Default fallback
            "market_open": is_open,
        }
        
        return success_response("Nifty 50 option chain data", **options_data)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_nifty50_option_chain")
        return error_response("Failed to fetch option chain data", error=str(exc))


@router.get("/option-chain/banknifty50")
def get_banknifty50_option_chain(
    expiry_date: Optional[str] = Query(None, description="Expiry date in ISO format"),
    right: Optional[str] = Query(None, description="Option type: call or put"),
    strike_price: Optional[float] = Query(None, description="Strike price filter")
) -> Dict[str, Any]:
    """Get Bank Nifty option chain data - empty data structure for WebSocket population."""
    try:
        # Use monthly expiry if no expiry date provided
        if not expiry_date:
            expiry_date = get_monthly_expiry_date()
        
        is_open = _is_market_open_ist()

        # Return empty data structure - will be populated by WebSocket
        options_data = {
            "calls": [],
            "puts": [],
            "expiry_date": expiry_date,
            "underlying": "BANK NIFTY",
            "underlying_price": 52000,  # Default fallback
            "market_open": is_open,
        }
        
        return success_response("Bank Nifty option chain data", **options_data)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_banknifty50_option_chain")
        return error_response("Failed to fetch option chain data", error=str(exc))


@router.get("/option-chain/finnifty50")
def get_finnifty50_option_chain(
    expiry_date: Optional[str] = Query(None, description="Expiry date in ISO format"),
    right: Optional[str] = Query(None, description="Option type: call or put"),
    strike_price: Optional[float] = Query(None, description="Strike price filter")
) -> Dict[str, Any]:
    """Get FIN NIFTY option chain data - empty data structure for WebSocket population."""
    try:
        # Use monthly expiry if no expiry date provided
        if not expiry_date:
            expiry_date = get_monthly_expiry_date()
        
        is_open = _is_market_open_ist()

        # Return empty data structure - will be populated by WebSocket
        options_data = {
            "calls": [],
            "puts": [],
            "expiry_date": expiry_date,
            "underlying": "FIN NIFTY",
            "underlying_price": 20000,  # Default fallback
            "market_open": is_open,
        }
        
        return success_response("FIN NIFTY option chain data", **options_data)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_finnifty50_option_chain")
        return error_response("Failed to fetch option chain data", error=str(exc))


@router.get("/option-chain/expiry-dates")
def get_expiry_dates(index: Optional[str] = Query(None, description="Index name: NIFTY, BANKNIFTY, or FINNIFTY")) -> Dict[str, Any]:
    """Get available expiry dates for options based on index type."""
    try:
        today = datetime.now()
        expiry_dates = []
        
        if index and index.upper() in ["BANKNIFTY", "FINNIFTY"]:
            # For Bank Nifty and FIN NIFTY: monthly expiry (last Tuesday of month)
            for i in range(4):  # Next 4 months
                # Calculate the last Tuesday of current month + i months
                target_month = today.month + i
                target_year = today.year
                
                # Handle year rollover
                while target_month > 12:
                    target_month -= 12
                    target_year += 1
                
                # Get last day of target month
                if target_month == 12:
                    next_month = datetime(target_year + 1, 1, 1)
                else:
                    next_month = datetime(target_year, target_month + 1, 1)
                
                last_day_of_month = next_month - timedelta(days=1)
                
                # Find the last Tuesday of the month
                current_date = last_day_of_month
                while current_date.weekday() != 1:  # Tuesday is 1
                    current_date -= timedelta(days=1)
                
                # Only include if it's today or in the future (today's expiry should remain until midnight)
                if current_date.date() >= today.date():
                    expiry_dates.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "iso_date": current_date.strftime("%Y-%m-%dT06:00:00.000Z"),
                        "display": current_date.strftime("%d %b %Y")
                    })
        else:
            # For Nifty 50: weekly expiry (next 4 Tuesdays)
            for i in range(4):
                # Find next Tuesday (including today if it's Tuesday)
                days_ahead = 1 - today.weekday()  # Tuesday is 1
                if days_ahead < 0:  # Target day already happened this week (but not today)
                    days_ahead += 7
                
                next_tuesday = today + timedelta(days=days_ahead + (i * 7))
                # Only include if it's today or in the future (today's expiry should remain until midnight)
                if next_tuesday.date() >= today.date():
                    expiry_dates.append({
                        "date": next_tuesday.strftime("%Y-%m-%d"),
                        "iso_date": next_tuesday.strftime("%Y-%m-%dT06:00:00.000Z"),
                        "display": next_tuesday.strftime("%d %b %Y")
                    })
        
        return success_response("Available expiry dates", dates=expiry_dates)
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_expiry_dates")
        return error_response("Failed to fetch expiry dates", error=str(exc))


@router.get("/option-chain/underlying-price")
def get_underlying_price() -> Dict[str, Any]:
    """Get current Nifty 50 underlying price - placeholder for WebSocket data."""
    try:
        # Return default price - will be updated by WebSocket
        return success_response("Underlying price", price={"ltp": 24700, "close": 24700})
        
    except Exception as exc:
        log_exception(exc, context="option_chain.get_underlying_price")
        return error_response("Failed to fetch underlying price", error=str(exc))


@router.post("/option-chain/subscribe")
def subscribe_option_chain_strikes(
    stock_code: str = Query(..., description="Underlying symbol, e.g., ICIBAN / NIFTY"),
    exchange_code: str = Query("NFO", description="Options segment, typically NFO"),
    product_type: str = Query("options", description="Product type for options"),
    right: str = Query("both", description="call, put, or both"),
    expiry_date: str = Query(..., description="Expiry in ISO format, e.g., 2025-08-28T06:00:00.000Z"),
    limit: Optional[int] = Query(None, description="Max number of strikes to subscribe (after filtering)"),
) -> Dict[str, Any]:
    """Fetch option chain for the given underlying/expiry and subscribe all strikes via WS.

    Requires an active Breeze session. Only full-form tokens (e.g., "X.Y!<id>") are used to
    avoid segment prefix mistakes.
    """
    try:
        # Skip live WS subscription when market is closed
        if not _is_market_open_ist():
            return success_response(
                "Market closed; live subscription skipped",
                underlying=stock_code.upper(),
                expiry_date=expiry_date,
                right=right,
                exchange_code=exchange_code,
                subscribed_count=0,
                market_open=False,
            )

        # Get Breeze service
        breeze = get_breeze()
        if not breeze:
            return error_response("No active Breeze session found. Please login first.")
        
        if not hasattr(breeze.client, 'session_key') or not breeze.client.session_key:
            return error_response("Breeze session found but no session key. Please login again.")

        # Subscribe to option chain data via websocket
        try:
            # Convert expiry date format for Breeze API
            from datetime import datetime
            expiry_dt = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
            breeze_expiry = expiry_dt.strftime("%d-%b-%Y")  # Format: "13-Feb-2025"
            
            # Debug logging (commented out to reduce terminal noise)
            # print(f"🔍 Option Chain Subscription Debug:")
            # print(f"   Stock Code: {stock_code}")
            # print(f"   Exchange Code: {exchange_code}")
            # print(f"   Expiry Date: {expiry_date} -> {breeze_expiry}")
            # print(f"   Right: {right}")
            # print(f"   Limit: {limit}")
            
            # Calculate strike prices around current underlying price
            # Get current underlying price first
            underlying_price = 24741  # Default NIFTY price
            try:
                underlying_quote = breeze.client.get_quotes(
                    stock_code=stock_code,
                    exchange_code="NSE",
                    product_type="cash"
                )
                if underlying_quote and underlying_quote.get("Success"):
                    success_data = underlying_quote.get("Success", [])
                    if success_data:
                        underlying_price = success_data[0].get("ltp", underlying_price)
            except Exception as e:
                log_exception(e, context="option_chain.get_underlying_price")
            
            # Calculate strikes around current price
            if stock_code.upper() == "NIFTY":
                # NIFTY strikes are in 50-point intervals
                atm_strike = round(underlying_price / 50) * 50
                strikes = [atm_strike - 150, atm_strike - 100, atm_strike - 50, 
                          atm_strike, atm_strike + 50, atm_strike + 100, atm_strike + 150]
            elif stock_code.upper() == "BANKNIFTY":
                # BANKNIFTY strikes are in 100-point intervals
                atm_strike = round(underlying_price / 100) * 100
                strikes = [atm_strike - 300, atm_strike - 200, atm_strike - 100,
                          atm_strike, atm_strike + 100, atm_strike + 200, atm_strike + 300]
            else:
                # Default to 50-point intervals
                atm_strike = round(underlying_price / 50) * 50
                strikes = [atm_strike - 150, atm_strike - 100, atm_strike - 50,
                          atm_strike, atm_strike + 50, atm_strike + 100, atm_strike + 150]
            
            subscribed_count = 0
            
            # Get the websocket stream manager to handle subscriptions
            from ..services.ws_stream_manager import STREAM_MANAGER
            
            # Subscribe to each strike for both calls and puts
            for strike in strikes[:limit] if limit else strikes:
                try:
                    # Subscribe to CALL option
                    if right in ["both", "call"]:
                        # Use the websocket stream manager to subscribe
                        STREAM_MANAGER.subscribe_option(
                            stock_code=stock_code,
                            exchange_code=exchange_code,
                            expiry_date=breeze_expiry,
                            strike_price=str(strike),
                            right="call",
                            product_type=product_type
                        )
                        subscribed_count += 1
                    
                    # Subscribe to PUT option
                    if right in ["both", "put"]:
                        # Use the websocket stream manager to subscribe
                        STREAM_MANAGER.subscribe_option(
                            stock_code=stock_code,
                            exchange_code=exchange_code,
                            expiry_date=breeze_expiry,
                            strike_price=str(strike),
                            right="put",
                            product_type=product_type
                        )
                        subscribed_count += 1
                        
                except Exception as e:
                    log_exception(e, context="option_chain.subscribe_strike", strike=strike)
                    continue
            
            return success_response(
                "Option chain subscribed successfully via websocket",
                underlying=stock_code.upper(),
                expiry_date=expiry_date,
                right=right,
                exchange_code=exchange_code,
                subscribed_count=subscribed_count,
                strikes=strikes,
                underlying_price=underlying_price,
                market_open=True
            )
            
        except Exception as e:
            log_exception(e, context="option_chain.subscribe_option_chain")
            return error_response("Failed to subscribe to option chain", error=str(e))

    except Exception as exc:
        log_exception(exc, context="option_chain.subscribe_option_chain_strikes")
        return error_response("Failed to subscribe option chain strikes", error=str(exc))
