import discord
import re
import random
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from .forum_tag_service import forum_tag_service, FRAMEWORK_TAG_PATTERN
from .mission_poll_repository import mission_poll_repository
from .event_repository import event_repository
from .schedule_config_repository import schedule_config_repository

logger = logging.getLogger(__name__)

# Composition tag abbreviation mapping (used only when answer exceeds 55 chars)
COMPOSITION_ABBREVIATIONS = {
    "infantry": "INF",
    "motorised": "MOTO",
    "mechanized": "MECH",
    "air assault": "AIR",
    "amphibious": "AMPH",
    "armored": "ARM",
    "battlebus": "BB",
    "special forces": "SF",
}

MAX_POLL_ANSWER_LENGTH = 55
MAX_POLL_OPTIONS = 10


def ordinal(n: int) -> str:
    """Return ordinal string for an integer (1st, 2nd, 3rd, etc.)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_event_date(event_date: date) -> str:
    """Format a date as 'Thursday 19th February'."""
    day_name = event_date.strftime("%A")
    day_ord = ordinal(event_date.day)
    month_name = event_date.strftime("%B")
    return f"{day_name} {day_ord} {month_name}"


def abbreviate_framework(tag_name: str) -> str:
    """Convert 'Framework 3.0' -> 'FW 3.0'."""
    match = re.match(r'Framework\s+(\d+\.\d+)', tag_name, re.IGNORECASE)
    if match:
        return f"FW {match.group(1)}"
    return tag_name


def format_poll_answer(mission_name: str, composition_tags: list[str]) -> str:
    """Format a poll answer within the 55-char Discord limit.
    
    Strategy:
    1. Full name + full tag names
    2. 'Operation' -> 'Op' + full tag names
    3. 'Op' + abbreviated tag names
    4. Truncate name with '…' + abbreviated tags
    """
    tag_str = "".join(f"[{t}]" for t in composition_tags)

    # Attempt 1: full name + full tags
    answer = f"{mission_name} {tag_str}" if tag_str else mission_name
    if len(answer) <= MAX_POLL_ANSWER_LENGTH:
        return answer

    # Attempt 2: shorten "Operation" to "Op"
    short_name = re.sub(r'\bOperation\b', 'Op', mission_name, flags=re.IGNORECASE)
    answer = f"{short_name} {tag_str}" if tag_str else short_name
    if len(answer) <= MAX_POLL_ANSWER_LENGTH:
        return answer

    # Attempt 3: abbreviated tags
    abbrev_tags = []
    for t in composition_tags:
        abbrev = COMPOSITION_ABBREVIATIONS.get(t.lower(), t[:4].upper())
        abbrev_tags.append(abbrev)
    tag_str_abbrev = "".join(f"[{a}]" for a in abbrev_tags)
    answer = f"{short_name} {tag_str_abbrev}" if tag_str_abbrev else short_name
    if len(answer) <= MAX_POLL_ANSWER_LENGTH:
        return answer

    # Attempt 4: truncate name
    max_name_len = MAX_POLL_ANSWER_LENGTH - len(tag_str_abbrev) - 2  # space + ellipsis
    if max_name_len < 5:
        max_name_len = 5
    truncated_name = short_name[: max_name_len - 1] + "…"
    answer = f"{truncated_name} {tag_str_abbrev}" if tag_str_abbrev else truncated_name
    return answer[:MAX_POLL_ANSWER_LENGTH]


def format_link_entry(mission_name: str, composition_tags: list[str], thread_url: str) -> str:
    """Format a link entry for the briefings embed (same format as poll answers)."""
    tag_str = "".join(f"[{t}]" for t in composition_tags)

    # Use short name
    short_name = re.sub(r'\bOperation\b', 'Op', mission_name, flags=re.IGNORECASE)
    display = f"{short_name} {tag_str}".strip() if tag_str else short_name

    # Abbreviate if too long for readability
    if len(display) > 60:
        abbrev_tags = []
        for t in composition_tags:
            abbrev = COMPOSITION_ABBREVIATIONS.get(t.lower(), t[:4].upper())
            abbrev_tags.append(abbrev)
        tag_str_abbrev = "".join(f"[{a}]" for a in abbrev_tags)
        display = f"{short_name} {tag_str_abbrev}".strip() if tag_str_abbrev else short_name

    return f"🔗 [{display}]({thread_url})"


async def fetch_all_forum_threads(guild: discord.Guild, forum_channel_id: int) -> list[discord.Thread]:
    """Fetch all threads (active + archived) from a forum channel."""
    forum_channel = guild.get_channel(forum_channel_id)
    if not forum_channel or forum_channel.type != discord.ChannelType.forum:
        logger.warning(f"Forum channel {forum_channel_id} not found or not a forum")
        return []

    threads = []

    # Active threads
    if hasattr(forum_channel, "threads"):
        threads.extend(forum_channel.threads or [])

    # Archived threads (public)
    try:
        async for thread in forum_channel.archived_threads(limit=None):
            threads.append(thread)
    except Exception as e:
        logger.warning(f"Error fetching archived threads: {e}")

    # De-duplicate by thread ID
    seen = set()
    unique = []
    for t in threads:
        if t.id not in seen:
            seen.add(t.id)
            unique.append(t)

    logger.info(f"Fetched {len(unique)} unique threads from forum channel {forum_channel_id}")
    return unique


def get_thread_tags(thread: discord.Thread) -> list[str]:
    """Get tag names from a forum thread."""
    if hasattr(thread, "applied_tags"):
        return [tag.name.strip() for tag in thread.applied_tags]
    return []


def get_thread_composition_tags(thread: discord.Thread) -> list[str]:
    """Get only composition (non-framework) tags from a thread."""
    tags = get_thread_tags(thread)
    return [t for t in tags if not FRAMEWORK_TAG_PATTERN.match(t)]


def filter_threads_by_tags(
    threads: list[discord.Thread],
    framework: str,
    composition: str = "All",
) -> list[discord.Thread]:
    """Filter threads by framework tag and optionally composition tag."""
    filtered = []
    for thread in threads:
        tags = get_thread_tags(thread)
        tag_names_lower = [t.lower() for t in tags]

        # Must have the framework tag
        if framework.lower() not in tag_names_lower:
            continue

        # If composition filter is not "All", must have that composition tag
        if composition.lower() != "all":
            if composition.lower() not in tag_names_lower:
                continue

        filtered.append(thread)

    return filtered


async def get_excluded_thread_ids(guild_id: int) -> set[int]:
    """Get thread IDs that won a poll for an event within the last 2 weeks (from event date).
    
    Deduplication window: 2 weeks from the event date of the winning poll.
    """
    recent_winners = await mission_poll_repository.get_recent_winners(guild_id)
    today = date.today()
    excluded = set()

    for winner in recent_winners:
        event_date = winner["event_date"]
        # If the event was less than 2 weeks ago, exclude this thread
        if isinstance(event_date, datetime):
            event_date = event_date.date()
        if today - event_date < timedelta(weeks=2):
            excluded.add(winner["winning_thread_id"])

    return excluded


async def extract_author_from_thread(thread: discord.Thread) -> str:
    """Extract author name from thread.
    
    Strategy:
    1. Check opening post for 'Created by: NAME' pattern
    2. Compare with thread.owner display name (ignoring rank prefixes)
    3. Fall back to thread owner or thread metadata
    """
    owner_name = None

    # Try to get thread owner display name
    if thread.owner:
        owner_name = thread.owner.display_name
    elif thread.owner_id:
        try:
            guild = thread.guild
            member = guild.get_member(thread.owner_id)
            if member:
                owner_name = member.display_name
            else:
                # User left the server - try to get from thread metadata
                owner_name = None
        except Exception:
            pass

    # Try to parse author from the opening post
    post_author = None
    try:
        # Fetch the first message (starter message) of the thread
        starter = thread.starter_message
        if not starter:
            starter = await thread.fetch_message(thread.id)

        if starter and starter.content:
            # Look for "Created by:", "Author:", "Mission Maker:" patterns
            # Allow for markdown formatting like **Created by:**
            pattern = re.compile(
                r'(?:\*{0,2})(?:Created\s+by|Author|Mission\s+Maker)(?:\*{0,2})\s*[:：]\s*(?:\*{0,2})\s*(.+?)(?:\*{0,2})\s*(?:\n|$)',
                re.IGNORECASE
            )
            match = pattern.search(starter.content)
            if match:
                post_author = match.group(1).strip().strip("*_ ")
    except Exception as e:
        logger.debug(f"Could not fetch starter message for thread {thread.id}: {e}")

    if post_author and owner_name:
        # Compare: strip rank prefixes from owner name for matching
        # Common rank prefixes: Pvt., Pfc., LCpl., Cpl., Sgt., SSgt., etc.
        rank_pattern = re.compile(
            r'^(?:Pvt|Pfc|LCpl|Cpl|Sgt|SSgt|GySgt|MSgt|1stSgt|MGySgt|'
            r'2ndLt|1stLt|Capt|Maj|LtCol|Col|BGen|MajGen|LtGen|Gen|'
            r'Rct|Pte|Tpr|Bdr|Spr|Sig|Cfn|Fus|Gds|Rfn)\.\s*',
            re.IGNORECASE,
        )
        owner_stripped = rank_pattern.sub('', owner_name).strip()
        post_stripped = rank_pattern.sub('', post_author).strip()

        # If they match (case-insensitive), we have high confidence
        if owner_stripped.lower() == post_stripped.lower():
            return post_author  # Use the post version (likely cleaner)
        else:
            # Don't match; prefer thread owner
            return owner_name
    elif post_author:
        return post_author
    elif owner_name:
        return owner_name
    else:
        return "Unknown"


async def send_dm_safe(user: discord.User, content: str = None, embed: discord.Embed = None, 
                       fallback_channel: discord.TextChannel = None):
    """Send a DM to a user, falling back to a channel message if DMs are disabled."""
    try:
        await user.send(content=content, embed=embed)
    except discord.Forbidden:
        if fallback_channel:
            try:
                await fallback_channel.send(content=content, embed=embed)
            except Exception as e:
                logger.warning(f"Failed to send fallback message to #{fallback_channel.name}: {e}")
        else:
            logger.warning(f"Cannot DM user {user} and no fallback channel available")
    except Exception as e:
        logger.warning(f"Failed to DM user {user}: {e}")
        if fallback_channel:
            try:
                await fallback_channel.send(content=content, embed=embed)
            except Exception:
                pass


async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Get the configured log channel for the guild."""
    config = await schedule_config_repository.get_config(guild.id)
    if config and config.get("log_channel_id"):
        channel = guild.get_channel(config["log_channel_id"])
        if channel:
            return channel
    return None
