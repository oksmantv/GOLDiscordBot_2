from datetime import date, timedelta, datetime
from collections import defaultdict
import discord
from config import Config
from services import event_repository
from services.schedule_config_repository import schedule_config_repository
import difflib

async def build_schedule_embed(guild):
    import logging
    logger = logging.getLogger("schedule_embed_service")
    today = date.today()
    now_local = datetime.now()
    start_date = today - timedelta(weeks=2)
    end_date = today + timedelta(weeks=4)
    events = await event_repository.get_events_by_guild_and_date_range(Config.GUILD_ID, start_date, end_date)

    # Get config for this guild (for briefing_channel_id)
    config = await schedule_config_repository.get_config(Config.GUILD_ID)
    briefing_channel_id = config["briefing_channel_id"] if config else None

    # Build header
    editors = set()
    instructors = set()
    for event in events:
        if event.type == "Mission" and event.date.weekday() in [3, 6]:  # Thursday or Sunday
            if event.creator_name:
                editors.add(event.creator_name)
        if event.type == "Training" and event.date.weekday() == 3:  # Thursday
            if event.creator_name:
                instructors.add(event.creator_name)
    editors_str = ", ".join(sorted(editors)) if editors else "None"
    instructors_str = ", ".join(sorted(instructors)) if instructors else "None"
    year = today.year
    GOL_ICON = "<:GOL:985630086487228527>"
    header = (
        f"Current Event Rotation: {year}\n"
        f":pen_fountain: Editors: {editors_str}\n"
        f":repeat: Instructors: {instructors_str}\n"
        f"{GOL_ICON} Use Command /schedule to update or view the schedule.\n"
        "Here you can now find the mission schedule, we will try as best as possible to announce ahead of time with at least the basic information about the mission. "
        "You can find briefings in #⁠mission-briefings, but here you can see the schedule."
    )

    # Group events by month
    months = defaultdict(list)
    for event in events:
        month_key = event.date.strftime('%B %Y')
        months[month_key].append(event)

    # Custom Discord emoji markup
    ICONS = {
        "Training": "<:Training:1173686838926512199>",
        "Mission": "<:Mission:1173686836451885076>"
    }

    def ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"

    unix_ts = int(now_local.timestamp())
    header_with_time = header + f"\n\nLast updated: <t:{unix_ts}:f> (<t:{unix_ts}:R>)"
    embed = discord.Embed(
        title=f"GOL Schedule (Next 8 Weeks)",
        description=header_with_time,
        color=discord.Color.blue()
    )
    # --- New logic: one field per week, with month label above first week of each month ---
    # Gather all events, sort by date
    all_events = sorted(events, key=lambda e: e.date)
    # Group events by week start
    week_groups = defaultdict(list)
    for event in all_events:
        week_start_for_event = event.date - timedelta(days=event.date.weekday())
        week_groups[week_start_for_event].append(event)
    week_keys = sorted(week_groups.keys())
    # For month labeling
    last_month = None
    # Calculate current week range with custom cutoff: Sunday 20:00 UTC
    from datetime import timezone, time as dtime
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    # Find the most recent Monday
    week_start = today - timedelta(days=today.weekday())
    # Find the next Sunday
    week_end_date = week_start + timedelta(days=6)
    # Set cutoff to Sunday 20:00 UTC
    week_end_cutoff = datetime.combine(week_end_date, dtime(hour=20, minute=0, tzinfo=timezone.utc))
    # If now is after the cutoff, move to next week
    if now_utc > week_end_cutoff:
        week_start = week_start + timedelta(days=7)
        week_end_date = week_start + timedelta(days=6)
        week_end_cutoff = datetime.combine(week_end_date, dtime(hour=20, minute=0, tzinfo=timezone.utc))
    for week_start_dt in week_keys:
        week_events = week_groups[week_start_dt]
        week_num = week_start_dt.isocalendar()[1]
        field_name = f"📅 Week {week_num}"
        week_lines = []
        added_thursday = False
        added_sunday = False
        for event in sorted(week_events, key=lambda e: (e.date, 0 if (e.date.weekday() == 3 and e.type == 'Training') else (1 if (e.date.weekday() == 3 and e.type == 'Mission') else 2))):
            icon = ICONS.get(event.type, '')
            day = ordinal(event.date.day)
            month_full = event.date.strftime('%B')
            weekday = event.date.weekday()
            # Try to find a matching briefing post link
            briefing_link = None
            if briefing_channel_id and event.name:
                from services.schedule_embed_service import find_briefing_post_link
                try:
                    briefing_link = await find_briefing_post_link(guild, briefing_channel_id, event.name, min_ratio=0.8)
                    logger.info(f"[BRIEFING LINK] Event: '{event.name}' | Link: {briefing_link}")
                except Exception as e:
                    logger.warning(f"[BRIEFING LINK ERROR] Event: '{event.name}' | Error: {e}")
            # Format event name as a link if briefing_link is found
            if briefing_link:
                event_name_display = f"[{event.name}]({briefing_link})"
            else:
                event_name_display = event.name or 'N/A'
            event_str = f"{icon} {event_name_display} by {event.creator_name or 'N/A'}"
            # Bold if event is in current week (before Sunday 20:00 UTC cutoff)
            event_datetime_utc = datetime.combine(event.date, dtime.min, tzinfo=timezone.utc)
            if week_start <= event.date <= week_end_date and event_datetime_utc <= week_end_cutoff:
                event_str = f"**{event_str}**"
            # Add marker only above first Thursday Training or Sunday Mission, with date
            if weekday == 3 and event.type == 'Training' and not added_thursday:
                marker = f"Thursday {day} {month_full}"
                if week_start <= event.date <= week_end_date and event_datetime_utc <= week_end_cutoff:
                    marker = f"**{marker}**"
                week_lines.append(marker)
                added_thursday = True
            # Insert separator if both Thursday and Sunday exist in the same week
            if weekday == 6 and event.type == 'Mission' and not added_sunday:
                if added_thursday:
                    week_lines.append('\u200b')
                marker = f"Sunday {day} {month_full}"
                if week_start <= event.date <= week_end_date and event_datetime_utc <= week_end_cutoff:
                    marker = f"**{marker}**"
                week_lines.append(marker)
                added_sunday = True
            week_lines.append(event_str)
        value = "\n".join(week_lines)
        if len(value) > 1024:
            value = value[:1000] + "... (truncated)"
        embed.add_field(name=field_name, value=value, inline=False)
        # Add a whitespace separator field for separation, except after the last week
        if week_start_dt != week_keys[-1]:
            embed.add_field(name='', value='\u200b', inline=False)
    embed.set_footer(text="")
    return embed

async def find_briefing_post_link(guild, forum_channel_id, mission_name, min_ratio=0.8):
    """
    Search for a forum post (thread) in the given forum_channel_id whose title matches mission_name with at least min_ratio similarity.
    Returns the Discord message URL if found, else None.
    """
    forum_channel = guild.get_channel(forum_channel_id)
    if not forum_channel or forum_channel.type != discord.ChannelType.forum:
        return None
    # Fetch all threads (posts) in the forum
    threads = []
    if hasattr(forum_channel, 'threads'):
        # In discord.py, threads is a property (list), not a coroutine
        threads = forum_channel.threads or []
    if not threads:
        # fallback for discord.py <2.3: use active_threads + archived_threads
        if hasattr(forum_channel, 'active_threads'):
            threads += await forum_channel.active_threads()
        if hasattr(forum_channel, 'archived_threads'):
            archived = await forum_channel.archived_threads()
            # archived_threads() may return a flattened list or a manager with flatten()
            if hasattr(archived, 'flatten'):
                threads += await archived.flatten()
            else:
                threads += archived
    # Fuzzy match
    best_match = None
    best_ratio = 0
    for thread in threads:
        ratio = difflib.SequenceMatcher(None, mission_name.lower(), thread.name.lower()).ratio()
        if ratio > best_ratio and ratio >= min_ratio:
            best_match = thread
            best_ratio = ratio
    if best_match:
        # For forum posts, the correct link is /channels/{guild_id}/{thread.id}
        return f"https://discord.com/channels/{guild.id}/{best_match.id}"
    return None
