import logging
from typing import Optional

import discord

from .schedule_config_repository import schedule_config_repository

logger = logging.getLogger(__name__)


async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Return configured log channel for this guild, if available and sendable."""
    config = await schedule_config_repository.get_config(guild.id)
    if not config:
        return None

    log_channel_id = config.get("log_channel_id")
    if not log_channel_id:
        return None

    channel = guild.get_channel(log_channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(log_channel_id)
        except Exception:
            return None

    if isinstance(channel, discord.TextChannel):
        return channel
    return None


async def report_failure(
    guild: Optional[discord.Guild],
    source: str,
    message: str,
    exc: Optional[Exception] = None,
) -> bool:
    """Send a failure record to the configured log channel.

    Returns True if sent, False if no log channel exists or sending failed.
    """
    if guild is None:
        return False

    log_channel = await get_log_channel(guild)
    if log_channel is None:
        return False

    payload = f"[FAIL] **{source}**\n{message}"
    if exc is not None:
        payload += f"\n{type(exc).__name__}: {exc}"

    # Discord message limit protection
    if len(payload) > 1900:
        payload = payload[:1897] + "..."

    try:
        await log_channel.send(payload)
        return True
    except Exception as send_err:
        logger.debug(f"Failed to send failure log to channel {log_channel.id}: {send_err}")
        return False
