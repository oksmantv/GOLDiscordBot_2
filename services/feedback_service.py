import discord
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from .event_repository import event_repository
from .feedback_repository import feedback_repository
from .raid_helper_service import raid_helper_service
from .schedule_config_repository import schedule_config_repository
from config import Config

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")

# ── Event schedule times (UK timezone) ─────────────────────────────────
# Thursday: 18:50 – 21:50 UK
# Sunday:   16:50 – 19:50 UK
EVENT_SCHEDULE = {
    3: {"start": time(18, 50), "end": time(21, 50)},   # Thursday (weekday 3)
    6: {"start": time(16, 50), "end": time(19, 50)},   # Sunday   (weekday 6)
}

# ── Feedback templates ─────────────────────────────────────────────────
THURSDAY_TEMPLATE = (
    "Please provide your feedback for today's event. "
    "Use the format below:\n\n"
    "**Training:**\n"
    "(Your feedback on the training session)\n\n"
    "**Editing:**\n"
    "(Your feedback on the mission editing/design)\n\n"
    "**Execution:**\n"
    "(Your feedback on mission execution and overall gameplay)"
)

SUNDAY_TEMPLATE = (
    "Please provide your feedback for today's event. "
    "Use the format below:\n\n"
    "**Editing:**\n"
    "(Your feedback on the mission editing/design)\n\n"
    "**Execution:**\n"
    "(Your feedback on mission execution and overall gameplay)"
)


def is_event_day(d: date) -> bool:
    """Return True if the date is a Thursday or Sunday."""
    return d.weekday() in EVENT_SCHEDULE


def get_event_end_uk(d: date) -> Optional[datetime]:
    """Return the event end datetime in UK tz for the given date, or None."""
    sched = EVENT_SCHEDULE.get(d.weekday())
    if not sched:
        return None
    return datetime.combine(d, sched["end"], tzinfo=UK_TZ)


def build_thread_title(event_date: date, events: list) -> str:
    """Build the feedback thread title from the date and event names.

    Thursday → "26-02-2026: Dragon Training + Rasman Down"
    Sunday   → "01-03-2026: Operation Frozen Road"
    """
    date_str = event_date.strftime("%d-%m-%Y")

    if event_date.weekday() == 3:  # Thursday
        training_name = ""
        mission_name = ""
        for ev in events:
            if ev.type == "Training" and ev.name.strip():
                training_name = ev.name.strip()
            elif ev.type == "Mission" and ev.name.strip():
                mission_name = ev.name.strip()

        parts = [p for p in [training_name, mission_name] if p]
        if parts:
            return f"{date_str}: {' + '.join(parts)}"
        return f"{date_str}: Thursday Event"

    else:  # Sunday
        mission_name = ""
        for ev in events:
            if ev.type == "Mission" and ev.name.strip():
                mission_name = ev.name.strip()
        if mission_name:
            return f"{date_str}: {mission_name}"
        return f"{date_str}: Sunday Event"


def get_feedback_template(event_date: date) -> str:
    """Return the appropriate feedback template for the day."""
    if event_date.weekday() == 3:
        return THURSDAY_TEMPLATE
    return SUNDAY_TEMPLATE


async def find_raid_helper_message_id(
    guild: discord.Guild, event_date: date
) -> Optional[int]:
    """Find the Raid-Helper event post message ID for a given date.

    Scans the events channel for a Raid-Helper embed matching the date.
    Returns the message ID (= Raid-Helper event ID) or None.
    """
    # Find the events channel by name pattern
    events_channel = None
    for ch in guild.text_channels:
        if "events" in ch.name.lower():
            events_channel = ch
            break

    if not events_channel:
        logger.debug("No events channel found for Raid-Helper lookup")
        return None

    day_name = event_date.strftime("%A")
    day_num = event_date.day
    month_name = event_date.strftime("%B")
    iso_str = event_date.isoformat()

    search_variants = [
        f"{day_name}",
        f"{day_num} {month_name}",
        f"{month_name} {day_num}",
        iso_str,
        event_date.strftime("%d/%m"),
    ]

    try:
        async for msg in events_channel.history(limit=50, oldest_first=False):
            for embed in msg.embeds:
                haystack = " ".join(
                    filter(
                        None,
                        [
                            embed.title or "",
                            embed.description or "",
                            " ".join(f.name + " " + f.value for f in embed.fields),
                        ],
                    )
                ).lower()

                has_day = day_name.lower() in haystack
                has_date = any(v.lower() in haystack for v in search_variants[1:])
                if has_day and has_date:
                    logger.info(
                        f"Found Raid-Helper event post for {event_date}: message {msg.id}"
                    )
                    return msg.id

            # Also check plain message content
            if msg.content:
                content_lower = msg.content.lower()
                has_day = day_name.lower() in content_lower
                has_date = any(v.lower() in content_lower for v in search_variants[1:])
                if has_day and has_date:
                    logger.info(
                        f"Found Raid-Helper event post for {event_date}: message {msg.id}"
                    )
                    return msg.id
    except Exception as e:
        logger.warning(f"Error searching events channel for Raid-Helper post: {e}")

    logger.debug(f"No Raid-Helper event post found for {event_date}")
    return None


async def build_mentions(
    guild: discord.Guild, event_date: date
) -> tuple[str, bool]:
    """Build the mentions string for the feedback post.

    Returns (mentions_string, used_raid_helper: bool).
    If Raid-Helper sign-ups are found, mentions each user.
    Otherwise falls back to mentioning the Leadership role.
    """
    rh_message_id = await find_raid_helper_message_id(guild, event_date)

    if rh_message_id:
        user_ids = await raid_helper_service.get_signup_user_ids(rh_message_id)
        if user_ids:
            mentions = " ".join(f"<@{uid}>" for uid in user_ids)
            return mentions, True

    # Fallback: mention Leadership role
    leadership_role = discord.utils.get(guild.roles, name="Leadership")
    if leadership_role:
        return (
            f"{leadership_role.mention}\n\n"
            "⚠️ Could not auto-detect attendees from Raid-Helper. "
            "Please use `/signed` for this event to notify players.",
            False,
        )

    return (
        "⚠️ Could not auto-detect attendees and no Leadership role found. "
        "Please manually notify players.",
        False,
    )


async def create_feedback_thread(
    guild: discord.Guild,
    event_date: date,
    *,
    force: bool = False,
) -> Optional[discord.Thread]:
    """Create a feedback forum thread for the given event date.

    Args:
        guild: The Discord guild.
        event_date: The date of the event.
        force: If True, skip the duplicate check and recreate.

    Returns:
        The created Thread object, or None if skipped/failed.
    """
    # Check for duplicate (unless forced)
    if not force:
        already_exists = await feedback_repository.has_feedback_for_date(
            guild.id, event_date
        )
        if already_exists:
            logger.info(f"Feedback post already exists for {event_date}, skipping")
            return None

    # Get feedback forum channel from config
    config = await schedule_config_repository.get_config(guild.id)
    if not config or not config.get("feedback_channel_id"):
        logger.warning("No feedback forum channel configured")
        return None

    feedback_channel_id = config["feedback_channel_id"]
    forum_channel = guild.get_channel(feedback_channel_id)

    if not forum_channel or forum_channel.type != discord.ChannelType.forum:
        logger.warning(
            f"Feedback channel {feedback_channel_id} not found or not a forum channel"
        )
        return None

    # Get events for this date from DB
    events = await event_repository.get_events_by_guild_and_date_range(
        guild.id, event_date, event_date
    )

    # Build thread title and template
    title = build_thread_title(event_date, events)
    template = get_feedback_template(event_date)

    # Build mentions (Raid-Helper or fallback)
    mentions, used_rh = await build_mentions(guild, event_date)

    # Compose the full message content
    content = f"{mentions}\n\n{template}"

    # Create the forum thread
    try:
        thread_with_message = await forum_channel.create_thread(
            name=title,
            content=content,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=True, everyone=False
            ),
        )

        # create_thread returns a tuple (Thread, Message) for forum channels
        thread = thread_with_message
        if isinstance(thread_with_message, tuple):
            thread = thread_with_message[0]

        # Record in DB
        if force:
            # Remove old record first so we can insert fresh
            await feedback_repository.delete_feedback_post(guild.id, event_date)

        await feedback_repository.create_feedback_post(
            guild.id, event_date, thread.id
        )

        source = "Raid-Helper sign-ups" if used_rh else "Leadership fallback"
        logger.info(
            f"Created feedback thread '{title}' (ID: {thread.id}) "
            f"using {source} for mentions"
        )
        return thread

    except Exception as e:
        logger.error(f"Failed to create feedback thread for {event_date}: {e}")
        return None


async def check_and_create_feedback(guild: discord.Guild) -> Optional[discord.Thread]:
    """Check if an event just ended and create a feedback post if needed.

    Called by the background loop. Only acts if:
    1. Today is Thursday or Sunday
    2. Current time (UK) is within 1 hour after event end
    3. No feedback post has been created yet for today
    """
    now_uk = datetime.now(UK_TZ)
    today = now_uk.date()

    if not is_event_day(today):
        return None

    event_end = get_event_end_uk(today)
    if not event_end:
        return None

    # Only post within the 1-hour window after event end
    if not (event_end <= now_uk <= event_end + timedelta(hours=1)):
        return None

    return await create_feedback_thread(guild, today)
