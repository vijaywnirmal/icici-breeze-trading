from __future__ import annotations

import os
import json
import redis
from typing import Optional, Any, Dict, Union
from datetime import datetime, timedelta
import logging

from .config import settings

logger = logging.getLogger(__name__)

# Global Redis client instance
_redis_client: Optional[redis.Redis] = None

def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client instance. Returns None if Redis is not configured."""
    global _redis_client
    
    if _redis_client is not None:
        return _redis_client
    
    try:
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        _redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
        
        # Test connection
        _redis_client.ping()
        logger.info("Redis connection established successfully")
        return _redis_client
        
    except Exception as e:
        logger.warning(f"Redis not available: {e}. Falling back to in-memory caching.")
        _redis_client = None
        return None

def is_redis_available() -> bool:
    """Check if Redis is available and working."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        client.ping()
        return True
    except Exception:
        return False

# Cache key prefixes for organization
class CacheKeys:
    SESSION = "session"
    MARKET_STATUS = "market_status"
    LIVE_PRICES = "live_prices"
    INSTRUMENTS_SEARCH = "instruments_search"
    RATE_LIMIT = "rate_limit"
    API_RESPONSE = "api_response"
    USER_PROFILE = "user_profile"

def make_key(prefix: str, identifier: str) -> str:
    """Create a standardized cache key."""
    return f"{prefix}:{identifier}"

def cache_set(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Set a value in Redis cache with optional TTL (seconds)."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        
        # Serialize value to JSON
        if isinstance(value, (dict, list)):
            serialized_value = json.dumps(value)
        else:
            serialized_value = str(value)
        
        if ttl:
            return client.setex(key, ttl, serialized_value)
        else:
            return client.set(key, serialized_value)
    except Exception as e:
        logger.warning(f"Failed to set cache key {key}: {e}")
        return False

def cache_get(key: str, default: Any = None) -> Any:
    """Get a value from Redis cache."""
    try:
        client = get_redis_client()
        if client is None:
            return default
        
        value = client.get(key)
        if value is None:
            return default
        
        # Try to deserialize JSON, fallback to string
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
            
    except Exception as e:
        logger.warning(f"Failed to get cache key {key}: {e}")
        return default

def cache_delete(key: str) -> bool:
    """Delete a key from Redis cache."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        return client.delete(key) > 0
    except Exception as e:
        logger.warning(f"Failed to delete cache key {key}: {e}")
        return False

def cache_exists(key: str) -> bool:
    """Check if a key exists in Redis cache."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        return client.exists(key) > 0
    except Exception as e:
        logger.warning(f"Failed to check cache key {key}: {e}")
        return False

def cache_ttl(key: str) -> int:
    """Get TTL for a key in seconds. Returns -1 if no TTL, -2 if key doesn't exist."""
    try:
        client = get_redis_client()
        if client is None:
            return -2
        return client.ttl(key)
    except Exception as e:
        logger.warning(f"Failed to get TTL for key {key}: {e}")
        return -2

def cache_increment(key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
    """Increment a numeric value in cache. Useful for rate limiting."""
    try:
        client = get_redis_client()
        if client is None:
            return 0
        
        result = client.incr(key, amount)
        if ttl and result == amount:  # First time setting this key
            client.expire(key, ttl)
        return result
    except Exception as e:
        logger.warning(f"Failed to increment cache key {key}: {e}")
        return 0

def cache_hset(hash_key: str, field: str, value: Any) -> bool:
    """Set a field in a Redis hash."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        
        if isinstance(value, (dict, list)):
            serialized_value = json.dumps(value)
        else:
            serialized_value = str(value)
        
        return client.hset(hash_key, field, serialized_value) >= 0
    except Exception as e:
        logger.warning(f"Failed to hset {hash_key}.{field}: {e}")
        return False

def cache_hget(hash_key: str, field: str, default: Any = None) -> Any:
    """Get a field from a Redis hash."""
    try:
        client = get_redis_client()
        if client is None:
            return default
        
        value = client.hget(hash_key, field)
        if value is None:
            return default
        
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    except Exception as e:
        logger.warning(f"Failed to hget {hash_key}.{field}: {e}")
        return default

def cache_hgetall(hash_key: str) -> Dict[str, Any]:
    """Get all fields from a Redis hash."""
    try:
        client = get_redis_client()
        if client is None:
            return {}
        
        data = client.hgetall(hash_key)
        result = {}
        for field, value in data.items():
            try:
                result[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                result[field] = value
        return result
    except Exception as e:
        logger.warning(f"Failed to hgetall {hash_key}: {e}")
        return {}

def cache_hexists(hash_key: str, field: str) -> bool:
    """Check if a field exists in a Redis hash."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        return client.hexists(hash_key, field)
    except Exception as e:
        logger.warning(f"Failed to hexists {hash_key}.{field}: {e}")
        return False

def cache_hdel(hash_key: str, field: str) -> bool:
    """Delete a field from a Redis hash."""
    try:
        client = get_redis_client()
        if client is None:
            return False
        return client.hdel(hash_key, field) > 0
    except Exception as e:
        logger.warning(f"Failed to hdel {hash_key}.{field}: {e}")
        return False

# Convenience functions for common use cases
def cache_session(user_id: str, session_data: Dict[str, Any], ttl: int = 86400) -> bool:
    """Cache user session data for 24 hours by default."""
    key = make_key(CacheKeys.SESSION, user_id)
    return cache_set(key, session_data, ttl)

def get_cached_session(user_id: str) -> Optional[Dict[str, Any]]:
    """Get cached user session data."""
    key = make_key(CacheKeys.SESSION, user_id)
    return cache_get(key)

def cache_market_status(status_data: Dict[str, Any], ttl: int = 60) -> bool:
    """Cache market status for 1 minute by default."""
    key = make_key(CacheKeys.MARKET_STATUS, "current")
    return cache_set(key, status_data, ttl)

def get_cached_market_status() -> Optional[Dict[str, Any]]:
    """Get cached market status."""
    key = make_key(CacheKeys.MARKET_STATUS, "current")
    return cache_get(key)

def cache_live_price(symbol: str, price_data: Dict[str, Any], ttl: int = 3600) -> bool:
    """Cache live price data for 1 hour by default."""
    return cache_hset(CacheKeys.LIVE_PRICES, symbol, price_data)

def get_cached_live_prices(symbols: list) -> Dict[str, Any]:
    """Get cached live prices for multiple symbols."""
    if not symbols:
        return {}
    
    try:
        client = get_redis_client()
        if client is None:
            return {}
        
        # Get all symbols at once
        data = client.hmget(CacheKeys.LIVE_PRICES, symbols)
        result = {}
        for symbol, value in zip(symbols, data):
            if value is not None:
                try:
                    result[symbol] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    result[symbol] = value
        return result
    except Exception as e:
        logger.warning(f"Failed to get cached live prices: {e}")
        return {}

def check_rate_limit(user_id: str, limit: int = 100, window: int = 3600) -> bool:
    """Check if user is within rate limit. Returns True if allowed."""
    key = make_key(CacheKeys.RATE_LIMIT, user_id)
    current = cache_increment(key, 1, window)
    return current <= limit

def get_rate_limit_remaining(user_id: str, limit: int = 100) -> int:
    """Get remaining rate limit for user."""
    key = make_key(CacheKeys.RATE_LIMIT, user_id)
    current = cache_get(key, 0)
    return max(0, limit - current)
