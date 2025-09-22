from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
import json

from sqlalchemy import text

from ..utils.postgres import get_conn, ensure_tables
from ..utils.response import log_exception
from ..utils.redis_config import (
    cache_live_price, get_cached_live_prices, 
    is_redis_available, CacheKeys
)


TABLE = "ltp_cache"

# In-memory fallback cache when PostgreSQL is not configured/available
_MEM_CACHE: Dict[str, Dict[str, Any]] = {}


def upsert_quote(symbol: str, payload: Dict[str, Any]) -> None:
	"""Upsert a cached quote for a symbol in PostgreSQL ltp_cache and Redis."""
	try:
		# Add timestamp to payload
		payload_with_timestamp = {
			**payload,
			"updated_at": datetime.utcnow().isoformat() + "Z",
		}
		
		# Try Redis first for fast updates
		if is_redis_available():
			try:
				cache_live_price(symbol.upper(), payload_with_timestamp, ttl=3600)  # 1 hour TTL
			except Exception:
				pass  # Continue to PostgreSQL
		
		# Also store in PostgreSQL for persistence
		ensure_tables()
		with get_conn() as conn:
			if conn is None:
				# Fallback to in-memory cache
				_MEM_CACHE[symbol.upper()] = payload_with_timestamp
				return
			conn.execute(
				text(
					f"""
					INSERT INTO {TABLE} (symbol, ltp, close, change_pct, bid, ask, volume, data, updated_at)
					VALUES (:symbol, :ltp, :close, :change_pct, :bid, :ask, :volume, CAST(:data AS JSONB), :updated_at)
					ON CONFLICT (symbol)
					DO UPDATE SET 
						ltp = EXCLUDED.ltp,
						close = EXCLUDED.close,
						change_pct = EXCLUDED.change_pct,
						bid = EXCLUDED.bid,
						ask = EXCLUDED.ask,
						volume = EXCLUDED.volume,
						data = EXCLUDED.data,
						updated_at = EXCLUDED.updated_at
					"""
				),
				{
					"symbol": symbol.upper(),
					"ltp": payload.get("ltp"),
					"close": payload.get("close"),
					"change_pct": payload.get("change_pct"),
					"bid": payload.get("bid"),
					"ask": payload.get("ask"),
					"volume": payload.get("volume"),
					"data": json.dumps(payload),
					"updated_at": datetime.utcnow().isoformat() + "Z",
				},
			)
	except Exception as exc:
		# On any DB error, still keep an in-memory copy so UI can show last-known
		try:
			_MEM_CACHE[symbol.upper()] = payload_with_timestamp
		except Exception:
			pass
		log_exception(exc, context="quotes_cache.upsert_quote", symbol=symbol)


def get_cached_quote(symbol: str) -> Optional[Dict[str, Any]]:
	"""Get cached quote from Redis first, then PostgreSQL, then memory cache."""
	try:
		# Try Redis first for fastest access
		if is_redis_available():
			try:
				cached_prices = get_cached_live_prices([symbol.upper()])
				if cached_prices and symbol.upper() in cached_prices:
					return cached_prices[symbol.upper()]
			except Exception:
				pass  # Continue to PostgreSQL
		
		# Fallback to PostgreSQL
		with get_conn() as conn:
			if conn is None:
				# Fallback to in-memory cache
				return _MEM_CACHE.get(symbol.upper())
			res = conn.execute(
				text(f"SELECT ltp, close, change_pct, bid, ask, volume, data FROM {TABLE} WHERE symbol = :symbol LIMIT 1"), 
				{"symbol": symbol.upper()}
			)
			row = res.fetchone()
			if not row:
				# Try memory cache as a secondary fallback
				return _MEM_CACHE.get(symbol.upper())
			
			# Return structured data with individual columns
			result = {
				"ltp": row[0],
				"close": row[1],
				"change_pct": row[2],
				"bid": row[3],
				"ask": row[4],
				"volume": row[5]
			}
			
			# Also include raw data if available
			if row[6]:
				try:
					raw_data = json.loads(row[6]) if isinstance(row[6], str) else row[6]
					result.update(raw_data)
				except Exception:
					pass
			
			return result
	except Exception as exc:
		# As a last resort, use memory cache
		try:
			cached = _MEM_CACHE.get(symbol.upper())
			if cached:
				return cached
		except Exception:
			pass
		log_exception(exc, context="quotes_cache.get_cached_quote", symbol=symbol)
		return None


def delete_quote(symbol: str) -> None:
	"""Delete a cached quote row for a symbol from PostgreSQL, if configured."""
	try:
		with get_conn() as conn:
			if conn is None:
				# Remove from in-memory cache too
				try:
					_MEM_CACHE.pop(symbol.upper(), None)
				except Exception:
					pass
				return
			conn.execute(text(f"DELETE FROM {TABLE} WHERE symbol = :symbol"), {"symbol": symbol.upper()})
	except Exception as exc:
		log_exception(exc, context="quotes_cache.delete_quote", symbol=symbol)


