import time
from .database_connection import db_connection
from typing import Optional

_loa_config_cache: dict[int, tuple[dict, float]] = {}
_LOA_CONFIG_TTL = 300.0  # 5 minutes


class LOAConfigRepository:
    """Repository for LOA channel configuration."""

    def _invalidate(self, guild_id: int) -> None:
        _loa_config_cache.pop(guild_id, None)

    async def get_config(self, guild_id: int) -> Optional[dict]:
        """Get the LOA config for a guild."""
        now = time.monotonic()
        cached = _loa_config_cache.get(guild_id)
        if cached is not None:
            val, ts = cached
            if now - ts < _LOA_CONFIG_TTL:
                return val

        query = "SELECT * FROM loa_config WHERE guild_id = $1;"
        row = await db_connection.execute_single(query, guild_id)
        result = dict(row) if row else None
        if result is not None:
            _loa_config_cache[guild_id] = (result, now)
        return result

    async def set_config(self, guild_id: int, channel_id: int, message_id: int) -> None:
        """Set or update the LOA config for a guild."""
        query = """
        INSERT INTO loa_config (guild_id, channel_id, message_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id)
        DO UPDATE SET channel_id = $2, message_id = $3;
        """
        await db_connection.execute_command(query, guild_id, channel_id, message_id)
        self._invalidate(guild_id)


# Singleton instance
loa_config_repository = LOAConfigRepository()
