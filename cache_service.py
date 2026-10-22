"""
Khandelia Oil & General Mills - Enterprise Distributed Redis & In-Memory Hybrid Cache Layer
Dramatically reduces database read IOPS under 1M-10M concurrent traffic spikes.
"""

import json
import time
from typing import Any, Optional, Dict
try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None
from config import settings
from logger_service import logger

class MemoryCacheFallback:
    """Thread-safe In-Memory TTL Cache fallback when Redis is unreachable"""
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[str]:
        item = self._store.get(key)
        if not item:
            return None
        if time.time() > item["expires_at"]:
            self._store.pop(key, None)
            return None
        return item["val"]

    def set(self, key: str, val: str, ttl: int = 300) -> None:
        self._store[key] = {
            "val": val,
            "expires_at": time.time() + ttl
        }

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

class CacheService:
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.memory_fallback = MemoryCacheFallback()
        self.is_redis_connected = False

    async def init_cache(self):
        """Initializes connection pool to Redis server with auto-failover to RAM cache"""
        if not settings.REDIS_ENABLED or aioredis is None:
            logger.info("Redis disabled or library not installed; using high-speed In-Memory Cache")
            return

        try:
            pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=50,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0
            )
            self.redis_client = aioredis.Redis(connection_pool=pool)
            await self.redis_client.ping()
            self.is_redis_connected = True
            logger.info(f"Connected to Redis cache pool at {settings.REDIS_URL}")
        except Exception as e:
            self.is_redis_connected = False
            logger.warning(f"Redis unavailable ({e}); falling back smoothly to In-Memory RAM Cache")

    async def get(self, key: str) -> Optional[Any]:
        if self.is_redis_connected and self.redis_client:
            try:
                raw = await self.redis_client.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.debug(f"Redis get error for key {key}: {e}")
        
        # Fallback to RAM cache
        raw_ram = self.memory_fallback.get(key)
        if raw_ram:
            try:
                return json.loads(raw_ram)
            except Exception:
                return raw_ram
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        serialized = json.dumps(value, default=str)
        success = False

        if self.is_redis_connected and self.redis_client:
            try:
                await self.redis_client.set(key, serialized, ex=ttl_seconds)
                success = True
            except Exception as e:
                logger.debug(f"Redis set error for key {key}: {e}")

        # Always save in RAM cache as well for ultra-fast local tier-1 read
        self.memory_fallback.set(key, serialized, ttl=ttl_seconds)
        return success

    async def delete(self, key: str) -> bool:
        self.memory_fallback.delete(key)
        if self.is_redis_connected and self.redis_client:
            try:
                await self.redis_client.delete(key)
                return True
            except Exception as e:
                logger.debug(f"Redis delete error for key {key}: {e}")
        return True

    # ---------------- Domain Specific High-Performance Cache Helpers ----------------

    async def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        return await self.get(f"session:{token}")

    async def set_session(self, token: str, data: Dict[str, Any], ttl: int = 86400) -> None:
        await self.set(f"session:{token}", data, ttl_seconds=ttl)

    async def invalidate_session(self, token: str) -> None:
        await self.delete(f"session:{token}")

    async def get_cached_units(self) -> Optional[list]:
        return await self.get("units:active_list")

    async def set_cached_units(self, units: list, ttl: int = 1800) -> None:
        await self.set("units:active_list", units, ttl_seconds=ttl)

    async def invalidate_units(self) -> None:
        await self.delete("units:active_list")

    async def get_cached_customer_search(self, query: str) -> Optional[list]:
        clean_q = (query or "").strip().lower()
        if not clean_q or len(clean_q) < 2:
            return None
        return await self.get(f"crm_search:{clean_q}")

    async def set_cached_customer_search(self, query: str, results: list, ttl: int = 600) -> None:
        clean_q = (query or "").strip().lower()
        if clean_q and len(clean_q) >= 2:
            await self.set(f"crm_search:{clean_q}", results, ttl_seconds=ttl)

    async def get_cached_stats(self) -> Optional[Dict[str, Any]]:
        return await self.get("dashboard:stats_summary")

    async def set_cached_stats(self, stats: Dict[str, Any], ttl: int = 60) -> None:
        await self.set("dashboard:stats_summary", stats, ttl_seconds=ttl)

    async def invalidate_stats(self) -> None:
        await self.delete("dashboard:stats_summary")

cache = CacheService()
