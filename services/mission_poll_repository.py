import json
import logging
from datetime import datetime, timezone
from typing import Optional, List
from .database_connection import db_connection

logger = logging.getLogger(__name__)


class MissionPollRepository:
    """Repository for mission_polls table CRUD operations."""

    async def create_poll(
        self,
        guild_id: int,
        poll_message_id: int,
        channel_id: int,
        target_event_id: int,
        framework_filter: str,
        composition_filter: str,
        mission_thread_ids: list[int],
        poll_end_time: datetime,
        created_by: int,
        links_message_id: int = None,
    ) -> int:
        """Insert a new poll record. Returns the new poll ID."""
        query = """
        INSERT INTO mission_polls 
            (guild_id, poll_message_id, channel_id, target_event_id,
             framework_filter, composition_filter, mission_thread_ids,
             poll_end_time, status, created_by, links_message_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, 'active', $9, $10)
        RETURNING id;
        """
        thread_ids_json = json.dumps(mission_thread_ids)
        result = await db_connection.execute_single(
            query,
            guild_id,
            poll_message_id,
            channel_id,
            target_event_id,
            framework_filter,
            composition_filter,
            thread_ids_json,
            poll_end_time,
            created_by,
            links_message_id,
        )
        poll_id = result["id"] if result else None
        logger.info(f"Created mission poll #{poll_id} for event {target_event_id}")
        return poll_id

    async def get_active_polls(self, guild_id: int = None) -> list[dict]:
        """Get all active polls, optionally filtered by guild."""
        if guild_id:
            query = """
            SELECT id, guild_id, poll_message_id, channel_id, target_event_id,
                   framework_filter, composition_filter, mission_thread_ids,
                   poll_end_time, status, winning_thread_id, created_by, created_at,
                   links_message_id
            FROM mission_polls WHERE status = 'active' AND guild_id = $1
            ORDER BY poll_end_time;
            """
            results = await db_connection.execute_query(query, guild_id)
        else:
            query = """
            SELECT id, guild_id, poll_message_id, channel_id, target_event_id,
                   framework_filter, composition_filter, mission_thread_ids,
                   poll_end_time, status, winning_thread_id, created_by, created_at,
                   links_message_id
            FROM mission_polls WHERE status = 'active'
            ORDER BY poll_end_time;
            """
            results = await db_connection.execute_query(query)
        return [self._row_to_dict(row) for row in results]

    async def get_active_poll_for_event(self, target_event_id: int) -> Optional[dict]:
        """Check if there's already an active poll for a given event."""
        query = """
        SELECT id, guild_id, poll_message_id, channel_id, target_event_id,
               framework_filter, composition_filter, mission_thread_ids,
               poll_end_time, status, winning_thread_id, created_by, created_at,
               links_message_id
        FROM mission_polls WHERE status = 'active' AND target_event_id = $1;
        """
        result = await db_connection.execute_single(query, target_event_id)
        return self._row_to_dict(result) if result else None

    async def get_recent_winners(self, guild_id: int) -> list[dict]:
        """Get completed polls to check for deduplication (winners only)."""
        query = """
        SELECT mp.id, mp.winning_thread_id, e.date as event_date
        FROM mission_polls mp
        JOIN events e ON mp.target_event_id = e.id
        WHERE mp.guild_id = $1 
          AND mp.status = 'completed' 
          AND mp.winning_thread_id IS NOT NULL;
        """
        results = await db_connection.execute_query(query, guild_id)
        return [{"id": row[0], "winning_thread_id": row[1], "event_date": row[2]} for row in results]

    async def mark_completed(self, poll_id: int, winning_thread_id: int):
        """Mark a poll as completed with the winning thread."""
        query = """
        UPDATE mission_polls SET status = 'completed', winning_thread_id = $2 WHERE id = $1;
        """
        await db_connection.execute_command(query, poll_id, winning_thread_id)
        logger.info(f"Poll #{poll_id} marked completed, winner thread: {winning_thread_id}")

    async def mark_failed(self, poll_id: int):
        """Mark a poll as failed."""
        query = """
        UPDATE mission_polls SET status = 'failed' WHERE id = $1;
        """
        await db_connection.execute_command(query, poll_id)
        logger.warning(f"Poll #{poll_id} marked as failed")

    def _row_to_dict(self, row) -> dict:
        """Convert a database row to a dictionary."""
        if not row:
            return {}
        thread_ids = row[7]
        if isinstance(thread_ids, str):
            thread_ids = json.loads(thread_ids)
        return {
            "id": row[0],
            "guild_id": row[1],
            "poll_message_id": row[2],
            "channel_id": row[3],
            "target_event_id": row[4],
            "framework_filter": row[5],
            "composition_filter": row[6],
            "mission_thread_ids": thread_ids,
            "poll_end_time": row[8],
            "status": row[9],
            "winning_thread_id": row[10],
            "created_by": row[11],
            "created_at": row[12],
            "links_message_id": row[13] if len(row) > 13 else None,
        }


# Singleton instance
mission_poll_repository = MissionPollRepository()
