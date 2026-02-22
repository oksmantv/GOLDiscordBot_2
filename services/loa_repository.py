from .database_connection import db_connection
from typing import Optional
from datetime import date


class LOARepository:
    """Repository for Leave of Absence database operations."""

    async def create_loa(
        self,
        guild_id: int,
        user_id: int,
        start_date: date,
        end_date: date,
        reason: Optional[str] = None,
    ) -> dict:
        """Create a new LOA record and return it."""
        query = """
        INSERT INTO leave_of_absence (guild_id, user_id, start_date, end_date, reason)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *;
        """
        row = await db_connection.execute_single(query, guild_id, user_id, start_date, end_date, reason)
        return dict(row)

    async def get_active_loas_by_user(self, guild_id: int, user_id: int) -> list[dict]:
        """Get all active (non-expired) LOAs for a specific user."""
        query = """
        SELECT * FROM leave_of_absence
        WHERE guild_id = $1 AND user_id = $2 AND expired = FALSE
        ORDER BY start_date ASC;
        """
        rows = await db_connection.execute_query(query, guild_id, user_id)
        return [dict(r) for r in rows]

    async def get_active_loas_by_guild(self, guild_id: int) -> list[dict]:
        """Get all active LOAs for a guild, sorted by end_date ascending."""
        query = """
        SELECT * FROM leave_of_absence
        WHERE guild_id = $1 AND expired = FALSE
        ORDER BY end_date ASC;
        """
        rows = await db_connection.execute_query(query, guild_id)
        return [dict(r) for r in rows]

    async def get_loa_by_id(self, loa_id: int) -> Optional[dict]:
        """Get a specific LOA by ID."""
        query = "SELECT * FROM leave_of_absence WHERE id = $1;"
        row = await db_connection.execute_single(query, loa_id)
        return dict(row) if row else None

    async def mark_expired(self, loa_id: int) -> None:
        """Mark an LOA as expired."""
        query = "UPDATE leave_of_absence SET expired = TRUE WHERE id = $1;"
        await db_connection.execute_command(query, loa_id)

    async def mark_notified(self, loa_id: int) -> None:
        """Mark an LOA as notified (user has been DM'd about expiry)."""
        query = "UPDATE leave_of_absence SET notified = TRUE WHERE id = $1;"
        await db_connection.execute_command(query, loa_id)

    async def update_message_info(self, loa_id: int, message_id: int, channel_id: int) -> None:
        """Update the announcement message ID and channel ID for an LOA."""
        query = """
        UPDATE leave_of_absence
        SET message_id = $2, channel_id = $3
        WHERE id = $1;
        """
        await db_connection.execute_command(query, loa_id, message_id, channel_id)

    async def get_expired_unnotified(self, guild_id: int) -> list[dict]:
        """Get all expired LOAs that haven't been notified yet."""
        query = """
        SELECT * FROM leave_of_absence
        WHERE guild_id = $1 AND expired = TRUE AND notified = FALSE
        ORDER BY end_date ASC;
        """
        rows = await db_connection.execute_query(query, guild_id)
        return [dict(r) for r in rows]

    async def check_overlap(
        self, guild_id: int, user_id: int, start_date: date, end_date: date
    ) -> Optional[dict]:
        """Check if a new LOA overlaps with any existing active LOA for the user.

        Two date ranges overlap if: start1 <= end2 AND start2 <= end1.
        Returns the first overlapping LOA or None.
        """
        query = """
        SELECT * FROM leave_of_absence
        WHERE guild_id = $1 AND user_id = $2 AND expired = FALSE
          AND start_date <= $4 AND end_date >= $3
        LIMIT 1;
        """
        row = await db_connection.execute_single(query, guild_id, user_id, start_date, end_date)
        return dict(row) if row else None


# Singleton instance
loa_repository = LOARepository()
