from .database_connection import db_connection
from typing import Optional


class RosterRepository:
    """Repository for Platoon Roster member database operations."""

    async def upsert_member(
        self,
        guild_id: int,
        user_id: int,
        nickname: str,
        rank_prefix: Optional[str],
        rank_name: Optional[str],
        rank_order: int,
        is_active: bool,
        is_reserve: bool,
        subgroup: Optional[str],
        on_loa: bool,
    ) -> dict:
        """Insert or update a roster member.

        ``reserve_since`` is set to NOW() only when the member first
        transitions to reserve.  It is cleared when they leave reserve.
        """
        query = """
        INSERT INTO roster_members
            (guild_id, user_id, nickname, rank_prefix, rank_name,
             rank_order, is_active, is_reserve, subgroup, on_loa,
             last_seen, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), NOW())
        ON CONFLICT (guild_id, user_id)
        DO UPDATE SET
            nickname    = EXCLUDED.nickname,
            rank_prefix = EXCLUDED.rank_prefix,
            rank_name   = EXCLUDED.rank_name,
            rank_order  = EXCLUDED.rank_order,
            is_active   = EXCLUDED.is_active,
            is_reserve  = EXCLUDED.is_reserve,
            subgroup    = EXCLUDED.subgroup,
            on_loa      = EXCLUDED.on_loa,
            last_seen   = NOW(),
            updated_at  = NOW()
        RETURNING *;
        """
        row = await db_connection.execute_single(
            query, guild_id, user_id, nickname, rank_prefix, rank_name,
            rank_order, is_active, is_reserve, subgroup, on_loa,
        )
        return dict(row)

    async def remove_member(self, guild_id: int, user_id: int) -> None:
        """Remove a member who no longer has the @Member role."""
        query = "DELETE FROM roster_members WHERE guild_id = $1 AND user_id = $2;"
        await db_connection.execute_command(query, guild_id, user_id)

    async def get_active_members(self, guild_id: int) -> list[dict]:
        """Get all active roster members ordered by rank."""
        query = """
        SELECT * FROM roster_members
        WHERE guild_id = $1 AND is_active = TRUE
        ORDER BY rank_order ASC, nickname ASC;
        """
        rows = await db_connection.execute_query(query, guild_id)
        return [dict(r) for r in rows]

    async def get_reserve_members(self, guild_id: int) -> list[dict]:
        """Get all reserve roster members ordered alphabetically."""
        query = """
        SELECT * FROM roster_members
        WHERE guild_id = $1 AND is_reserve = TRUE
        ORDER BY nickname ASC;
        """
        rows = await db_connection.execute_query(query, guild_id)
        return [dict(r) for r in rows]

    async def get_all_members(self, guild_id: int) -> list[dict]:
        """Get every roster member for a guild."""
        query = """
        SELECT * FROM roster_members
        WHERE guild_id = $1
        ORDER BY rank_order ASC, nickname ASC;
        """
        rows = await db_connection.execute_query(query, guild_id)
        return [dict(r) for r in rows]

    async def get_member_count(self, guild_id: int) -> int:
        """Total @Member count."""
        query = "SELECT COUNT(*) FROM roster_members WHERE guild_id = $1;"
        row = await db_connection.execute_single(query, guild_id)
        return row[0] if row else 0

    async def get_active_count(self, guild_id: int) -> int:
        """Total @Active count."""
        query = "SELECT COUNT(*) FROM roster_members WHERE guild_id = $1 AND is_active = TRUE;"
        row = await db_connection.execute_single(query, guild_id)
        return row[0] if row else 0

    async def get_reserve_count(self, guild_id: int) -> int:
        """Total @Reserve count."""
        query = "SELECT COUNT(*) FROM roster_members WHERE guild_id = $1 AND is_reserve = TRUE;"
        row = await db_connection.execute_single(query, guild_id)
        return row[0] if row else 0

    async def remove_absent_members(self, guild_id: int, present_user_ids: list[int]) -> int:
        """Remove roster entries for users no longer in the guild with @Member.

        Returns the number of rows deleted.
        """
        if not present_user_ids:
            # No members at all — wipe the guild roster
            query = "DELETE FROM roster_members WHERE guild_id = $1;"
            result = await db_connection.execute_command(query, guild_id)
        else:
            query = """
            DELETE FROM roster_members
            WHERE guild_id = $1 AND user_id != ALL($2::BIGINT[]);
            """
            result = await db_connection.execute_command(query, guild_id, present_user_ids)
        # asyncpg returns e.g. "DELETE 3"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0


# Singleton instance
roster_repository = RosterRepository()
