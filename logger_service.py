"""
Khandelia Oil & General Mills - Enterprise Structured JSON Logging & Observability
Provides microsecond-precision timing, request correlation IDs, and Sentry hooks.
"""

import sys
import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from config import settings

# Request Correlation ID context
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

class JSONFormatter(logging.Formatter):
    """Formats log records into compact, structured JSON for high-throughput log collectors"""
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
            "environment": settings.ENVIRONMENT
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Setup root logger
logger = logging.getLogger("kogm_enterprise")
logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logger.handlers.clear()
logger.addHandler(handler)
logger.propagate = False

# Initialize Sentry if DSN is set
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.05
        )
        logger.info("Sentry error tracking initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to initialize Sentry: {e}")

class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Middleware that injects X-Request-ID header, tracks execution time, and logs structured requests"""
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Response-Time-Ms"] = str(duration_ms)

            # Avoid logging noisy health checks and static files
            path = request.url.path
            if not path.startswith(("/images", "/js", "/favicon.ico")) and path != "/health":
                logger.info(
                    f"{request.method} {path} - {response.status_code} ({duration_ms}ms)"
                )
            return response
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Unhandled Exception on {request.method} {request.url.path} after {duration_ms}ms: {exc}",
                exc_info=True
            )
            raise exc
        finally:
            request_id_ctx.reset(token)
