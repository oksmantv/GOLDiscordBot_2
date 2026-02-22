from .database_connection import db_connection
from typing import Optional


class LOAConfigRepository:
    """Repository for LOA channel configuration."""

    async def get_config(self, guild_id: int) -> Optional[dict]:
        """Get the LOA config for a guild."""
        query = "SELECT * FROM loa_config WHERE guild_id = $1;"
        row = await db_connection.execute_single(query, guild_id)
        return dict(row) if row else None

    async def set_config(self, guild_id: int, channel_id: int, message_id: int) -> None:
        """Set or update the LOA config for a guild."""
        query = """
        INSERT INTO loa_config (guild_id, channel_id, message_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id)
        DO UPDATE SET channel_id = $2, message_id = $3;
        """
        await db_connection.execute_command(query, guild_id, channel_id, message_id)


# Singleton instance
loa_config_repository = LOAConfigRepository()
