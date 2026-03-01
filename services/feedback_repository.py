from datetime import date
from typing import Optional
from .database_connection import db_connection


class FeedbackRepository:
    """Repository for feedback_posts CRUD operations."""

    async def has_feedback_for_date(self, guild_id: int, event_date: date) -> bool:
        """Check if a feedback post already exists for this guild + date."""
        query = """
        SELECT 1 FROM feedback_posts
        WHERE guild_id = $1 AND event_date = $2
        LIMIT 1;
        """
        result = await db_connection.execute_single(query, guild_id, event_date)
        return result is not None

    async def create_feedback_post(
        self, guild_id: int, event_date: date, thread_id: int
    ) -> bool:
        """Record that a feedback thread was created."""
        query = """
        INSERT INTO feedback_posts (guild_id, event_date, thread_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, event_date) DO NOTHING;
        """
        result = await db_connection.execute_command(query, guild_id, event_date, thread_id)
        return "INSERT" in (result or "")

    async def get_feedback_post(
        self, guild_id: int, event_date: date
    ) -> Optional[dict]:
        """Get the feedback post record for a guild + date."""
        query = """
        SELECT id, guild_id, event_date, thread_id, created_at
        FROM feedback_posts
        WHERE guild_id = $1 AND event_date = $2;
        """
        row = await db_connection.execute_single(query, guild_id, event_date)
        if row:
            return {
                "id": row[0],
                "guild_id": row[1],
                "event_date": row[2],
                "thread_id": row[3],
                "created_at": row[4],
            }
        return None

    async def delete_feedback_post(self, guild_id: int, event_date: date) -> bool:
        """Delete a feedback post record (e.g., to allow re-creation)."""
        query = """
        DELETE FROM feedback_posts WHERE guild_id = $1 AND event_date = $2;
        """
        result = await db_connection.execute_command(query, guild_id, event_date)
        return "DELETE 1" in (result or "")


# Singleton
feedback_repository = FeedbackRepository()
