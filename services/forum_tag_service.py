import discord
import re
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Regex pattern to identify framework tags: "Framework X.Y"
FRAMEWORK_TAG_PATTERN = re.compile(r'^Framework\s+\d+\.\d+$', re.IGNORECASE)


class ForumTagService:
    """Service for caching and categorizing forum channel tags.
    
    Tags are cached in memory with a 24-hour TTL.
    Cache is populated on /configure and on first /missionpoll use if empty.
    """

    def __init__(self):
        self._framework_tags: list[str] = []
        self._composition_tags: list[str] = []
        self._all_tags: list[discord.ForumTag] = []
        self._last_fetched: float = 0.0
        self._cache_ttl: float = 86400.0  # 24 hours in seconds

    @property
    def is_stale(self) -> bool:
        """Check if the cache is older than 24 hours or empty."""
        if not self._all_tags:
            return True
        return (time.time() - self._last_fetched) > self._cache_ttl

    @property
    def framework_tags(self) -> list[str]:
        return list(self._framework_tags)

    @property
    def composition_tags(self) -> list[str]:
        return list(self._composition_tags)

    @property
    def all_tags(self) -> list[discord.ForumTag]:
        return list(self._all_tags)

    def _categorize_tags(self, tags: list[discord.ForumTag]):
        """Categorize tags into framework and composition lists."""
        self._framework_tags = []
        self._composition_tags = []
        self._all_tags = list(tags)

        for tag in tags:
            if FRAMEWORK_TAG_PATTERN.match(tag.name.strip()):
                self._framework_tags.append(tag.name.strip())
            else:
                self._composition_tags.append(tag.name.strip())

        self._framework_tags.sort()
        self._composition_tags.sort()
        logger.info(
            f"Tag cache updated: {len(self._framework_tags)} framework tags, "
            f"{len(self._composition_tags)} composition tags"
        )

    async def refresh_tags(self, guild: discord.Guild, briefing_channel_id: int):
        """Force-refresh tags from the forum channel."""
        forum_channel = guild.get_channel(briefing_channel_id)
        if not forum_channel or forum_channel.type != discord.ChannelType.forum:
            logger.warning(f"Forum channel {briefing_channel_id} not found or not a forum channel")
            return

        self._categorize_tags(forum_channel.available_tags)
        self._last_fetched = time.time()
        logger.info(f"Refreshed tag cache from #{forum_channel.name}")

    async def ensure_cache(self, guild: discord.Guild, briefing_channel_id: int):
        """Ensure tag cache is populated and fresh. Refreshes if stale or empty."""
        if self.is_stale:
            await self.refresh_tags(guild, briefing_channel_id)

    def get_tag_by_name(self, name: str) -> Optional[discord.ForumTag]:
        """Find a cached ForumTag object by its name (case-insensitive)."""
        for tag in self._all_tags:
            if tag.name.strip().lower() == name.strip().lower():
                return tag
        return None


# Singleton instance
forum_tag_service = ForumTagService()
