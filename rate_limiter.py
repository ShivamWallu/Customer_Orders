"""
Khandelia Oil & General Mills - Enterprise Rate Limiting & Abuse Prevention Engine
Prevents DDoS, brute-force OTP attempts, and order submission spam.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse
from config import settings
from logger_service import logger

def get_real_client_ip(request: Request) -> str:
    """Extracts client IP behind Cloudflare, Nginx reverse proxy, or load balancer"""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return get_remote_address(request) or "127.0.0.1"

# Initialize SlowAPI Limiter
limiter = Limiter(
    key_func=get_real_client_ip,
    default_limits=[settings.RATE_LIMIT_GLOBAL],
    storage_uri=settings.REDIS_URL if settings.REDIS_ENABLED and settings.RAW_DATABASE_URL.startswith("postgres") else "memory://"
)

def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Returns clean, structured JSON when rate limit threshold is crossed"""
    client_ip = get_real_client_ip(request)
    logger.warning(
        f"Rate limit exceeded by IP: {client_ip} on endpoint {request.url.path} (Limit: {exc.detail})"
    )
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too many requests in a short time. Please wait a moment before trying again.",
                "detail": str(exc.detail)
            }
        },
        headers={"Retry-After": "60"}
    )
