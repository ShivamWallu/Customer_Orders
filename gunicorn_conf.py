"""
Khandelia Oil & General Mills - Production Gunicorn Configuration
Manages multi-core Uvicorn worker processes for high-concurrency 10M traffic scaling.
"""

import multiprocessing
import os

# Binding
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# Worker Processes: (2 x cores) + 1, capped at 16 for memory efficiency
cores = multiprocessing.cpu_count()
default_workers = max(2, min(cores * 2 + 1, 16))
workers = int(os.getenv("WEB_CONCURRENCY", default_workers))

# Worker Class for Asynchronous FastAPI execution
worker_class = "uvicorn.workers.UvicornWorker"

# Connections & Concurrency
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))
max_requests = int(os.getenv("MAX_REQUESTS", "50000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "1000"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Logging & Observability
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Security & Limits
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

def on_starting(server):
    server.log.info(f"Starting Khandelia Enterprise Order Suite with {workers} workers on {bind}")
