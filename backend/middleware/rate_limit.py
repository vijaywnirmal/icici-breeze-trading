from __future__ import annotations

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, Optional
import time

from ..utils.redis_config import check_rate_limit, get_rate_limit_remaining, is_redis_available
from ..utils.response import error_response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis for distributed rate limiting."""
    
    def __init__(self, app, calls_per_hour: int = 1000, calls_per_minute: int = 100):
        super().__init__(app)
        self.calls_per_hour = calls_per_hour
        self.calls_per_minute = calls_per_minute
        self._local_cache: Dict[str, Dict[str, int]] = {}  # Fallback when Redis unavailable
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for certain paths
        if self._should_skip_rate_limit(request.url.path):
            return await call_next(request)
        
        # Get client identifier (IP address)
        client_ip = self._get_client_ip(request)
        if not client_ip:
            return await call_next(request)
        
        # Check rate limits
        if not self._check_rate_limit(client_ip):
            remaining = self._get_remaining_requests(client_ip)
            return JSONResponse(
                status_code=429,
                content=error_response(
                    "Rate limit exceeded", 
                    error=f"Too many requests. Try again later. Remaining: {remaining}"
                )
            )
        
        # Add rate limit headers
        response = await call_next(request)
        remaining = self._get_remaining_requests(client_ip)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Limit"] = str(self.calls_per_hour)
        
        return response
    
    def _should_skip_rate_limit(self, path: str) -> bool:
        """Skip rate limiting for certain paths."""
        skip_paths = [
            "/docs",
            "/redoc", 
            "/openapi.json",
            "/health",
            "/favicon.ico"
        ]
        return any(path.startswith(skip) for skip in skip_paths)
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP address from request."""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # Check for real IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback to direct client IP
        if hasattr(request, "client") and request.client:
            return request.client.host
        
        return None
    
    def _check_rate_limit(self, client_ip: str) -> bool:
        """Check if client is within rate limits."""
        if is_redis_available():
            # Use Redis for distributed rate limiting
            return (
                check_rate_limit(f"{client_ip}:hour", self.calls_per_hour, 3600) and
                check_rate_limit(f"{client_ip}:minute", self.calls_per_minute, 60)
            )
        else:
            # Fallback to local memory cache
            return self._check_local_rate_limit(client_ip)
    
    def _check_local_rate_limit(self, client_ip: str) -> bool:
        """Check rate limit using local memory cache."""
        now = time.time()
        current_hour = int(now // 3600)
        current_minute = int(now // 60)
        
        if client_ip not in self._local_cache:
            self._local_cache[client_ip] = {
                "hour": current_hour,
                "minute": current_minute,
                "hour_count": 0,
                "minute_count": 0
            }
        
        client_data = self._local_cache[client_ip]
        
        # Reset counters if hour/minute changed
        if client_data["hour"] != current_hour:
            client_data["hour"] = current_hour
            client_data["hour_count"] = 0
        
        if client_data["minute"] != current_minute:
            client_data["minute"] = current_minute
            client_data["minute_count"] = 0
        
        # Check limits
        if (client_data["hour_count"] >= self.calls_per_hour or 
            client_data["minute_count"] >= self.calls_per_minute):
            return False
        
        # Increment counters
        client_data["hour_count"] += 1
        client_data["minute_count"] += 1
        
        return True
    
    def _get_remaining_requests(self, client_ip: str) -> int:
        """Get remaining requests for client."""
        if is_redis_available():
            return min(
                get_rate_limit_remaining(f"{client_ip}:hour", self.calls_per_hour),
                get_rate_limit_remaining(f"{client_ip}:minute", self.calls_per_minute)
            )
        else:
            # Fallback calculation
            if client_ip not in self._local_cache:
                return self.calls_per_hour
            
            client_data = self._local_cache[client_ip]
            return min(
                max(0, self.calls_per_hour - client_data["hour_count"]),
                max(0, self.calls_per_minute - client_data["minute_count"])
            )
