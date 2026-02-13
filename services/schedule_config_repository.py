from .database_connection import db_connection

class ScheduleConfigRepository:
    """Repository for storing and retrieving schedule config (channel_id, message_id) per guild."""
    async def set_config(self, guild_id: int, channel_id: int, message_id: int, briefing_channel_id: int, log_channel_id: int = None):
        query = """
        INSERT INTO schedule_config (guild_id, channel_id, message_id, briefing_channel_id, log_channel_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2, message_id = $3, briefing_channel_id = $4, log_channel_id = $5;
        """
        await db_connection.execute_command(query, guild_id, channel_id, message_id, briefing_channel_id, log_channel_id)

    async def update_log_channel(self, guild_id: int, log_channel_id: int):
        """Update only the log channel for an existing config."""
        query = """
        UPDATE schedule_config SET log_channel_id = $2 WHERE guild_id = $1;
        """
        await db_connection.execute_command(query, guild_id, log_channel_id)

    async def get_config(self, guild_id: int):
        query = """
        SELECT channel_id, message_id, briefing_channel_id, log_channel_id FROM schedule_config WHERE guild_id = $1;
        """
        result = await db_connection.execute_single(query, guild_id)
        if result:
            return {
                "channel_id": result[0],
                "message_id": result[1],
                "briefing_channel_id": result[2],
                "log_channel_id": result[3]
            }
        return None

schedule_config_repository = ScheduleConfigRepository()
