"""
Khandelia Oil & General Mills Pvt. Ltd. - Enterprise Settings & Scalability Config
Targeting High-Concurrency Traffic (1 to 10 Million Users / Transactions)
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Environment & Application Metadata
    APP_NAME: str = "Khandelia Enterprise Order Engine"
    APP_VERSION: str = "2.0.0-PROD"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production").lower()
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Core Security & Admin Auth
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "Admin@123#")
    AUTH_SECRET_TOKEN: str = os.getenv("AUTH_SECRET_TOKEN", "KOGM_ADMIN_SECURE_TOKEN_2026_XYZ")
    SECRET_TOKEN: str = os.getenv("SECRET_TOKEN", "KOGM_SECRET_TOKEN_2026")
    BACKEND_BASE_URL: str = os.getenv("BACKEND_BASE_URL", "https://order.khandelia.online")

    # Primary Database (Async Engine Support)
    RAW_DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///orders.db")
    
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Converts raw database url to proper async driver url"""
        url = self.RAW_DATABASE_URL
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return url

    # Optional Read Replica for 10M Concurrent Read Load Distribution
    RAW_READ_REPLICA_URL: Optional[str] = os.getenv("DATABASE_READ_REPLICA_URL")

    @property
    def ASYNC_READ_REPLICA_URL(self) -> Optional[str]:
        if not self.RAW_READ_REPLICA_URL:
            return None
        url = self.RAW_READ_REPLICA_URL
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    # Connection Pooling Parameters (Tuned for High Concurrency)
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "50"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "100"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    # Redis Distributed Cache & Session Store
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_ENABLED: bool = os.getenv("REDIS_ENABLED", "true").lower() == "true"
    REDIS_CACHE_TTL_CATALOG: int = int(os.getenv("REDIS_CACHE_TTL_CATALOG", "3600")) # 1 hour
    REDIS_CACHE_TTL_SESSION: int = int(os.getenv("REDIS_CACHE_TTL_SESSION", "86400")) # 24 hours
    REDIS_CACHE_TTL_SEARCH: int = int(os.getenv("REDIS_CACHE_TTL_SEARCH", "600")) # 10 mins

    # Rate Limiting Guardrails (SlowAPI / Token Bucket)
    RATE_LIMIT_GLOBAL: str = os.getenv("RATE_LIMIT_GLOBAL", "200/minute")
    RATE_LIMIT_ORDER_SUBMIT: str = os.getenv("RATE_LIMIT_ORDER_SUBMIT", "15/minute")
    RATE_LIMIT_OTP: str = os.getenv("RATE_LIMIT_OTP", "6/minute")
    RATE_LIMIT_SEARCH: str = os.getenv("RATE_LIMIT_SEARCH", "120/minute")

    # Kit19 OTP Service
    KIT19_API_URL: str = os.getenv("KIT19_API_URL", "https://www.kit19.com/ComposeSMS.aspx")
    KIT19_USERNAME: str = os.getenv("KIT19_USERNAME", "khandelia348774")
    KIT19_PASSWORD: str = os.getenv("KIT19_PASSWORD", "")
    KIT19_SENDER_ID: str = os.getenv("KIT19_SENDER_ID", "KOGMBD")

    # WhatsApp Automation
    TARGET_WHATSAPP_NUMBER: str = os.getenv("TARGET_WHATSAPP_NUMBER", "917814749816")

    # Google Sheets Webhook
    GOOGLE_SHEET_ORDERS_WEBAPP_URL: str = os.getenv(
        "GOOGLE_SHEET_ORDERS_WEBAPP_URL",
        "https://script.google.com/macros/s/AKfycbz34gzaUCbs5znZrvoQ49FSiZPt9bgWK6WToz5Ek3_Y0k7H5hZTeqg0AhoSPaqxUQqA/exec"
    )

    # Observability & Error Tracking
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

settings = Settings()
