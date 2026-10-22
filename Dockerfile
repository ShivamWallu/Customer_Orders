# -------------------------------------------------------------
# Khandelia Oil & General Mills - Enterprise Production Dockerfile
# Optimized for High-Concurrency FastAPI + Asyncpg + Redis
# -------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ----------------- Final Production Image -----------------
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python wheels from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy project source files
COPY . .

# Create order slips directory with write permissions
RUN mkdir -p order_slips images && chmod -R 755 order_slips images

# Expose FastAPI port
EXPOSE 8000

# Healthcheck probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production Entrypoint with Gunicorn multi-core workers
CMD ["python", "-m", "gunicorn", "-c", "gunicorn_conf.py", "main:app"]
