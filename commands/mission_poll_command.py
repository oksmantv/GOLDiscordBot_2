import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional
from datetime import datetime, date, timedelta, timezone
import random
import re
import logging

from config import Config
from services.forum_tag_service import forum_tag_service
from services.mission_poll_repository import mission_poll_repository
from services.mission_poll_service import (
    fetch_all_forum_threads,
    filter_threads_by_tags,
    get_excluded_thread_ids,
    get_thread_composition_tags,
    format_poll_answer,
    format_link_entry,
    format_event_date,
    abbreviate_framework,
    extract_author_from_thread,
    send_dm_safe,
    get_log_channel,
    ordinal,
    MAX_POLL_OPTIONS,
)
from services.schedule_config_repository import schedule_config_repository
from services.event_repository import event_repository

logger = logging.getLogger(__name__)


class MissionPollCommands(commands.Cog):
    """Cog for the /missionpoll command and poll monitoring background task."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Called when the cog is loaded. Start background task."""
        self._poll_monitor_loop.start()
        logger.info("Mission poll monitor background task started")

    async def cog_unload(self):
        """Called when the cog is unloaded. Stop background task."""
        self._poll_monitor_loop.cancel()

    # ─── Helper: get briefing channel ID from config ───────────────────
    async def _get_briefing_channel_id(self, guild_id: int) -> Optional[int]:
        config = await schedule_config_repository.get_config(guild_id)
        if config:
            return config.get("briefing_channel_id")
        return None

    # ─── Helper: get unassigned mission events in next 2 weeks ─────────
    async def _get_upcoming_unassigned_events(self, guild_id: int):
        today = date.today()
        end_date = today + timedelta(weeks=2)
        events = await event_repository.get_events_by_guild_and_date_range(guild_id, today, end_date)
        # Only Mission type, unassigned (empty name)
        return [e for e in events if e.type == "Mission" and not e.name.strip()]

    # ─── Helper: find Raid-Helper event post in the events channel ─────
    async def _find_event_post_link(self, guild: discord.Guild, event_date: date) -> str | None:
        """Search for a Raid-Helper event post matching the given date.

        Looks for a channel whose name contains 'events' and scans recent
        messages for an embed that mentions the target date.
        Returns a Discord message URL or None.
        """
        # Find the events channel by name pattern (e.g. "events📅❗")
        events_channel = None
        for ch in guild.text_channels:
            if "events" in ch.name.lower():
                events_channel = ch
                break

        if not events_channel:
            logger.debug("No events channel found for event-post linking")
            return None

        # Build date strings to search for in embeds.
        # Raid-Helper can format dates various ways, so we check several.
        day_name = event_date.strftime("%A")        # "Sunday"
        day_num = event_date.day                     # 15
        month_name = event_date.strftime("%B")       # "February"
        iso_str = event_date.isoformat()             # "2026-02-15"
        # Also try DD/MM and DD.MM variants
        search_variants = [
            f"{day_name}",                           # at minimum the weekday
            f"{day_num} {month_name}",               # "15 February"
            f"{month_name} {day_num}",               # "February 15"
            iso_str,                                 # "2026-02-15"
            event_date.strftime("%d/%m"),             # "15/02"
        ]

        try:
            async for msg in events_channel.history(limit=50, oldest_first=False):
                # Check embeds (Raid-Helper posts as embeds)
                for embed in msg.embeds:
                    haystack = " ".join(filter(None, [
                        embed.title or "",
                        embed.description or "",
                        " ".join(f.name + " " + f.value for f in embed.fields),
                    ])).lower()

                    # Need at least the weekday AND one date indicator
                    has_day = day_name.lower() in haystack
                    has_date = any(v.lower() in haystack for v in search_variants[1:])
                    if has_day and has_date:
                        url = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{msg.id}"
                        logger.info(f"Found event post for {event_date}: {url}")
                        return url

                # Also check plain message content as fallback
                if msg.content:
                    content_lower = msg.content.lower()
                    has_day = day_name.lower() in content_lower
                    has_date = any(v.lower() in content_lower for v in search_variants[1:])
                    if has_day and has_date:
                        url = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{msg.id}"
                        logger.info(f"Found event post for {event_date}: {url}")
                        return url
        except Exception as e:
            logger.warning(f"Error searching events channel for event post: {e}")

        logger.debug(f"No event post found for {event_date}")
        return None

    # ─── The slash command ─────────────────────────────────────────────
    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="missionpoll",
        description="Create a mission poll from forum briefings for an upcoming event",
    )
    @app_commands.describe(
        framework="Select the framework version to filter missions",
        event="Select the upcoming event to create a poll for",
        duration="Poll duration in hours (default: 24, min: 12, max: 72)",
        options="Number of missions in the poll (default: 5, min: 3, max: 10)",
        composition="Filter by composition type (default: All)",
    )
    async def missionpoll_command(
        self,
        interaction: discord.Interaction,
        framework: str,
        event: str,
        duration: int = 24,
        options: app_commands.Range[int, 3, 10] = 5,
        composition: str = "All",
    ):
        """Handle the /missionpoll command."""
        # ── Permission check (admin or @Editor) ──
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", ephemeral=True
            )
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)
        is_admin = any(getattr(r.permissions, "administrator", False) for r in member.roles)
        has_editor = any(r.name.strip().lower() == "editor" for r in member.roles)
        if not (is_admin or has_editor):
            await interaction.response.send_message(
                "❌ You must be an admin or have the @Editor role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # ── Validate duration ──
        if duration not in (12, 24, 36, 48, 60, 72):
            await interaction.followup.send(
                "❌ Duration must be one of: 12, 24, 36, 48, 60, 72 hours.", ephemeral=True
            )
            return

        # ── Resolve event ──
        try:
            event_id = int(event)
        except ValueError:
            await interaction.followup.send("❌ Invalid event selection.", ephemeral=True)
            return

        target_event = await event_repository.get_event_by_id(event_id)
        if not target_event:
            await interaction.followup.send("❌ Event not found.", ephemeral=True)
            return

        if target_event.name.strip():
            await interaction.followup.send(
                f"❌ Event **{format_event_date(target_event.date)}** already has a mission assigned: "
                f"*{target_event.name}*. Cannot create a poll for a scheduled event.",
                ephemeral=True,
            )
            return

        # ── Check for existing active poll on this event ──
        existing_poll = await mission_poll_repository.get_active_poll_for_event(event_id)
        if existing_poll:
            await interaction.followup.send(
                f"❌ There is already an active poll for **{format_event_date(target_event.date)}**. "
                "Only one poll per event is allowed.",
                ephemeral=True,
            )
            return

        # ── Get briefing channel ──
        briefing_channel_id = await self._get_briefing_channel_id(guild.id)
        if not briefing_channel_id:
            await interaction.followup.send(
                "❌ No briefing forum channel configured. Use `/configure` first.",
                ephemeral=True,
            )
            return

        # ── Ensure tag cache ──
        await forum_tag_service.ensure_cache(guild, briefing_channel_id)

        # ── Fetch & filter threads ──
        all_threads = await fetch_all_forum_threads(guild, briefing_channel_id)
        filtered = filter_threads_by_tags(all_threads, framework, composition)

        # ── Deduplication: exclude recently scheduled missions ──
        excluded_ids, matched_names = await get_excluded_thread_ids(guild.id, filtered)
        dedup_removed = []
        remaining = []
        for t in filtered:
            if t.id in excluded_ids:
                dedup_removed.append(t)
            else:
                remaining.append(t)

        if dedup_removed:
            logger.info(
                f"Deduplication removed {len(dedup_removed)} missions (scheduled in past 2 weeks): "
                f"{[t.name for t in dedup_removed]}"
            )

        # ── Check result count ──
        log_channel = await get_log_channel(guild)

        if len(remaining) == 0:
            error_embed = discord.Embed(
                title="❌ Mission Poll Failed — No Missions Found",
                color=discord.Color.red(),
                description=(
                    f"No missions matched your filter criteria.\n\n"
                    f"**Framework:** {framework}\n"
                    f"**Composition:** {composition}\n"
                    f"**Target Event:** {format_event_date(target_event.date)}\n"
                    f"**Forum Channel:** #{guild.get_channel(briefing_channel_id).name if guild.get_channel(briefing_channel_id) else 'Unknown'}\n"
                    f"**Total threads scanned:** {len(all_threads)}\n"
                    f"**After framework+composition filter:** {len(filtered)}\n"
                    f"**Removed by deduplication (scheduled in past 2 weeks):** {len(dedup_removed)}\n\n"
                    "💡 Try a different framework version, composition, or wait for the deduplication "
                    "window (2 weeks from event date) to expire."
                ),
            )
            await send_dm_safe(interaction.user, embed=error_embed, fallback_channel=log_channel)
            await interaction.followup.send(
                "❌ No missions found matching your criteria. Check your DMs for details.",
                ephemeral=True,
            )
            return

        if len(remaining) == 1:
            error_embed = discord.Embed(
                title="❌ Mission Poll Cancelled — Only 1 Mission Found",
                color=discord.Color.orange(),
                description=(
                    f"Only **{remaining[0].name}** matched your filter. "
                    "A poll requires at least 2 missions.\n\n"
                    f"**Framework:** {framework}\n"
                    f"**Composition:** {composition}\n"
                    f"**Target Event:** {format_event_date(target_event.date)}\n\n"
                    "💡 Try broadening your filter (e.g. set composition to All)."
                ),
            )
            await send_dm_safe(interaction.user, embed=error_embed, fallback_channel=log_channel)
            await interaction.followup.send(
                "❌ Only 1 mission matched — need at least 2 for a poll. Check your DMs for details.",
                ephemeral=True,
            )
            return

        # ── Random selection if more than requested options ──
        excluded_from_poll = []
        if len(remaining) > options:
            random.shuffle(remaining)
            selected = remaining[:options]
            excluded_from_poll = remaining[options:]
            remaining = selected

            # DM the user about excluded missions
            excluded_names = ", ".join(t.name for t in excluded_from_poll)
            dm_embed = discord.Embed(
                title="ℹ️ Mission Poll — Random Selection Applied",
                color=discord.Color.blue(),
                description=(
                    f"**{len(excluded_from_poll) + options}** missions matched your filter, "
                    f"but you requested {options} options.\n\n"
                    f"**Randomly selected:** {options} missions\n"
                    f"**Excluded:** {excluded_names}"
                ),
            )
            await send_dm_safe(interaction.user, embed=dm_embed, fallback_channel=log_channel)

        # ── Warn about deduplication ──
        if dedup_removed:
            dedup_names = ", ".join(t.name for t in dedup_removed)
            dedup_embed = discord.Embed(
                title="ℹ️ Deduplication Notice",
                color=discord.Color.greyple(),
                description=(
                    f"The following missions were excluded because they were "
                    f"scheduled for an event within the past 2 weeks:\n\n{dedup_names}"
                ),
            )
            await send_dm_safe(interaction.user, embed=dedup_embed, fallback_channel=log_channel)

        # ── Build poll answers ──
        fw_abbrev = abbreviate_framework(framework)
        poll_title = f"{format_event_date(target_event.date)} - Mission Poll [{fw_abbrev}]"

        thread_data = []  # Store (thread, answer_text, composition_tags) for links
        poll = discord.Poll(
            question=poll_title,
            duration=timedelta(hours=duration),
            multiple=True,
        )
        for thread in remaining:
            comp_tags = get_thread_composition_tags(thread)
            answer_text = format_poll_answer(thread.name, comp_tags)
            poll.add_answer(text=answer_text)
            thread_data.append((thread, answer_text, comp_tags))

        # ── Create the Discord Poll ──
        poll_end_dt = datetime.now(timezone.utc) + timedelta(hours=duration)

        # Find @Active role to mention in the poll message
        active_role = discord.utils.get(guild.roles, name="Active")
        poll_content = f"{active_role.mention} Vote for the next mission!" if active_role else None

        try:
            poll_message = await interaction.channel.send(
                content=poll_content,
                poll=poll,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
        except Exception as e:
            logger.error(f"Failed to send poll: {e}")
            await interaction.followup.send(
                f"❌ Failed to create poll: {e}", ephemeral=True
            )
            return

        # ── Build and send links embed ──
        links_title = f"{format_event_date(target_event.date)} - Mission Briefings [{fw_abbrev}]"
        links_lines = []
        for thread, _, comp_tags in thread_data:
            thread_url = f"https://discord.com/channels/{guild.id}/{thread.id}"
            links_lines.append(format_link_entry(thread.name, comp_tags, thread_url))

        links_embed = discord.Embed(
            title=links_title,
            description="\n".join(links_lines),
            color=discord.Color.blue(),
        )

        links_message = None
        try:
            links_message = await interaction.channel.send(embed=links_embed)
        except Exception as e:
            logger.error(f"Failed to send links embed: {e}")

        # ── Save poll to database ──
        mission_thread_ids = [t.id for t, _, _ in thread_data]
        await mission_poll_repository.create_poll(
            guild_id=guild.id,
            poll_message_id=poll_message.id,
            channel_id=interaction.channel.id,
            target_event_id=target_event.id,
            framework_filter=framework,
            composition_filter=composition,
            mission_thread_ids=mission_thread_ids,
            poll_end_time=poll_end_dt,
            created_by=interaction.user.id,
            links_message_id=links_message.id if links_message else None,
        )

        confirmation_msg = (
            f"✅ Mission poll created for **{format_event_date(target_event.date)}** [{fw_abbrev}] "
            f"with {len(remaining)} options. Poll ends in {duration}h."
        )
        dm_ok = await send_dm_safe(interaction.user, content=confirmation_msg, fallback_channel=log_channel)
        if not dm_ok and log_channel:
            try:
                await log_channel.send(confirmation_msg)
            except Exception:
                pass
        await interaction.followup.send(confirmation_msg, ephemeral=True)

    # ─── Autocomplete: framework ───────────────────────────────────────
    @missionpoll_command.autocomplete("framework")
    async def framework_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            guild = interaction.guild
            if not guild:
                return []
            briefing_channel_id = await self._get_briefing_channel_id(guild.id)
            if not briefing_channel_id:
                return [app_commands.Choice(name="⚠️ Run /configure first", value="NONE")]

            await forum_tag_service.ensure_cache(guild, briefing_channel_id)
            choices = []
            for tag_name in forum_tag_service.framework_tags:
                if current.lower() in tag_name.lower():
                    choices.append(app_commands.Choice(name=tag_name, value=tag_name))
            return choices[:25]
        except Exception as e:
            logger.error(f"Framework autocomplete error: {e}")
            return []

    # ─── Autocomplete: composition ─────────────────────────────────────
    @missionpoll_command.autocomplete("composition")
    async def composition_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            guild = interaction.guild
            if not guild:
                return []
            briefing_channel_id = await self._get_briefing_channel_id(guild.id)
            if not briefing_channel_id:
                return [app_commands.Choice(name="⚠️ Run /configure first", value="NONE")]

            await forum_tag_service.ensure_cache(guild, briefing_channel_id)
            choices = [app_commands.Choice(name="All (any composition)", value="All")]
            for tag_name in forum_tag_service.composition_tags:
                if current.lower() in tag_name.lower() or not current:
                    choices.append(app_commands.Choice(name=tag_name, value=tag_name))
            return choices[:25]
        except Exception as e:
            logger.error(f"Composition autocomplete error: {e}")
            return []

    # ─── Autocomplete: event ───────────────────────────────────────────
    @missionpoll_command.autocomplete("event")
    async def event_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            guild = interaction.guild
            if not guild:
                return []
            events = await self._get_upcoming_unassigned_events(guild.id)
            choices = []
            for ev in events:
                label = f"{format_event_date(ev.date)} — [Unassigned]"
                if current.lower() in label.lower() or not current:
                    choices.append(app_commands.Choice(name=label, value=str(ev.id)))
            return choices[:25]
        except Exception as e:
            logger.error(f"Event autocomplete error: {e}")
            return []

    # ─── Autocomplete: duration ────────────────────────────────────────
    @missionpoll_command.autocomplete("duration")
    async def duration_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        presets = [
            app_commands.Choice(name="12 hours", value=12),
            app_commands.Choice(name="24 hours (default)", value=24),
            app_commands.Choice(name="36 hours", value=36),
            app_commands.Choice(name="48 hours", value=48),
            app_commands.Choice(name="60 hours", value=60),
            app_commands.Choice(name="72 hours", value=72),
        ]
        if current:
            return [c for c in presets if current in str(c.value) or current.lower() in c.name.lower()]
        return presets

    # ─── Background task: poll monitor (every 30 minutes) ──────────────
    @tasks.loop(minutes=30)
    async def _poll_monitor_loop(self):
        """Check for ended polls and process results."""
        try:
            active_polls = await mission_poll_repository.get_active_polls()
            now = datetime.now(timezone.utc)

            for poll_data in active_polls:
                poll_end = poll_data["poll_end_time"]
                # Ensure timezone-aware
                if poll_end.tzinfo is None:
                    poll_end = poll_end.replace(tzinfo=timezone.utc)

                if now < poll_end:
                    continue  # Not ended yet

                logger.info(f"Processing ended poll #{poll_data['id']}")
                await self._process_ended_poll(poll_data)

        except Exception as e:
            logger.error(f"Poll monitor loop error: {e}")

    @_poll_monitor_loop.before_loop
    async def _before_poll_monitor(self):
        await self.bot.wait_until_ready()

    async def _process_ended_poll(self, poll_data: dict):
        """Process a poll that has ended: determine winner & auto-schedule."""
        guild = self.bot.get_guild(poll_data["guild_id"])
        if not guild:
            logger.warning(f"Guild {poll_data['guild_id']} not found for poll #{poll_data['id']}")
            await mission_poll_repository.mark_failed(poll_data["id"])
            return

        log_channel = await get_log_channel(guild)

        # Try to get the poll creator for DMs
        creator = None
        try:
            creator = guild.get_member(poll_data["created_by"])
            if not creator:
                creator = await self.bot.fetch_user(poll_data["created_by"])
        except Exception:
            pass

        # Fetch the poll message
        channel = guild.get_channel(poll_data["channel_id"])
        if not channel:
            logger.warning(f"Channel {poll_data['channel_id']} not found")
            await mission_poll_repository.mark_failed(poll_data["id"])
            if creator:
                await send_dm_safe(
                    creator,
                    content=f"❌ Poll #{poll_data['id']} failed: channel not found.",
                    fallback_channel=log_channel,
                )
            return

        try:
            poll_message = await channel.fetch_message(poll_data["poll_message_id"])
        except discord.NotFound:
            logger.warning(f"Poll message {poll_data['poll_message_id']} deleted")
            await mission_poll_repository.mark_failed(poll_data["id"])
            error_msg = (
                f"❌ **Poll Failed** — Poll message was deleted.\n"
                f"Poll #{poll_data['id']} for event ID {poll_data['target_event_id']}."
            )
            dm_ok = False
            if creator:
                dm_ok = await send_dm_safe(creator, content=error_msg, fallback_channel=log_channel)
            if not dm_ok and log_channel:
                await log_channel.send(error_msg)
            return
        except Exception as e:
            logger.error(f"Failed to fetch poll message: {e}")
            await mission_poll_repository.mark_failed(poll_data["id"])
            return

        # ── Read poll results ──
        if not poll_message.poll:
            logger.warning(f"Message {poll_message.id} has no poll data")
            await mission_poll_repository.mark_failed(poll_data["id"])
            return

        # Tally votes per answer index
        vote_counts = {}
        for i, answer in enumerate(poll_message.poll.answers):
            vote_counts[i] = answer.vote_count

        # Determine winner
        thread_ids = poll_data["mission_thread_ids"]
        if not vote_counts or all(v == 0 for v in vote_counts.values()):
            # Zero votes — random pick
            winner_idx = random.randint(0, len(thread_ids) - 1)
            logger.info(f"Poll #{poll_data['id']} had 0 votes, randomly selected index {winner_idx}")
        else:
            max_votes = max(vote_counts.values())
            tied_indices = [i for i, v in vote_counts.items() if v == max_votes]
            winner_idx = random.choice(tied_indices)
            logger.info(
                f"Poll #{poll_data['id']} winner: index {winner_idx} "
                f"with {max_votes} votes (ties: {len(tied_indices)})"
            )

        if winner_idx >= len(thread_ids):
            logger.error(f"Winner index {winner_idx} out of range for {len(thread_ids)} threads")
            await mission_poll_repository.mark_failed(poll_data["id"])
            return

        winning_thread_id = thread_ids[winner_idx]

        # ── Fetch the winning thread for author extraction ──
        briefing_channel_id = await self._get_briefing_channel_id(guild.id)
        winning_thread = None
        if briefing_channel_id:
            forum_channel = guild.get_channel(briefing_channel_id)
            if forum_channel:
                try:
                    winning_thread = forum_channel.get_thread(winning_thread_id)
                    if not winning_thread:
                        winning_thread = await guild.fetch_channel(winning_thread_id)
                except discord.NotFound:
                    logger.warning(f"Winning thread {winning_thread_id} not found/deleted")
                    # Thread deleted — warn but don't fail, just can't link
                    dm_ok = False
                    if creator:
                        dm_ok = await send_dm_safe(
                            creator,
                            content=(
                                f"⚠️ The winning mission thread was deleted. "
                                f"Poll #{poll_data['id']} could not auto-schedule."
                            ),
                            fallback_channel=log_channel,
                        )
                    if not dm_ok and log_channel:
                        await log_channel.send(
                            f"⚠️ Winning thread for poll #{poll_data['id']} was deleted. "
                            "Cannot auto-schedule."
                        )
                    await mission_poll_repository.mark_failed(poll_data["id"])
                    return
                except Exception as e:
                    logger.warning(f"Error fetching winning thread: {e}")

        if not winning_thread:
            await mission_poll_repository.mark_failed(poll_data["id"])
            return

        # ── Extract author & auto-schedule ──
        author_name = await extract_author_from_thread(winning_thread)
        mission_name = winning_thread.name

        # Get the target event
        target_event = await event_repository.get_event_by_id(poll_data["target_event_id"])
        if not target_event:
            logger.warning(f"Target event {poll_data['target_event_id']} not found")
            await mission_poll_repository.mark_failed(poll_data["id"])
            return

        # Check event is still unassigned
        if target_event.name.strip():
            logger.warning(
                f"Event {target_event.id} already has mission '{target_event.name}', skipping auto-schedule"
            )
            if log_channel:
                await log_channel.send(
                    f"⚠️ Poll #{poll_data['id']} winner was **{mission_name}**, but event "
                    f"**{format_event_date(target_event.date)}** already has *{target_event.name}* assigned."
                )
            await mission_poll_repository.mark_completed(poll_data["id"], winning_thread_id)
            return

        # Auto-schedule the event
        # Use creator_id=0 to indicate system/poll, creator_name = extracted author
        success = await event_repository.update_event(
            target_event.id,
            name=mission_name,
            creator_id=0,
            creator_name=author_name,
        )

        if success:
            await mission_poll_repository.mark_completed(poll_data["id"], winning_thread_id)
            logger.info(
                f"Auto-scheduled '{mission_name}' by {author_name} for "
                f"{format_event_date(target_event.date)}"
            )

            # ── Cleanup: delete poll + links messages ──
            try:
                await poll_message.delete()
                logger.info(f"Deleted poll message {poll_message.id}")
            except Exception as e:
                logger.warning(f"Failed to delete poll message: {e}")

            links_msg_id = poll_data.get("links_message_id")
            if links_msg_id and channel:
                try:
                    links_msg = await channel.fetch_message(links_msg_id)
                    await links_msg.delete()
                    logger.info(f"Deleted links embed message {links_msg_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete links embed message: {e}")

            # ── Find the Raid-Helper event post in the events channel ──
            event_post_link = await self._find_event_post_link(
                guild, target_event.date
            )

            # ── Build announcement ──
            # Mention the mission thread owner so they know to update the event
            owner_mention = ""
            if winning_thread and winning_thread.owner_id:
                owner_mention = f"<@{winning_thread.owner_id}>"

            announcement = (
                f"✅ Poll ended — **{mission_name}** has been scheduled for "
                f"**{format_event_date(target_event.date)}**"
            )

            if owner_mention:
                if event_post_link:
                    announcement += (
                        f"\n\n{owner_mention} Please update the "
                        f"[scheduled event]({event_post_link}) with the `/edit` command."
                    )
                else:
                    announcement += (
                        f"\n\n{owner_mention} Please update the scheduled event "
                        f"in the events channel with the `/edit` command."
                    )

            # ── Update the schedule embed + send announcement ──
            try:
                config = await schedule_config_repository.get_config(guild.id)
                if config:
                    sched_channel = guild.get_channel(config["channel_id"])
                    if sched_channel:
                        from services.schedule_embed_service import build_schedule_embed

                        msg = await sched_channel.fetch_message(config["message_id"])
                        embed = await build_schedule_embed(guild)
                        await msg.edit(embed=embed)
                        logger.info("Schedule embed updated after poll auto-schedule")

                        # Send visible announcement in the schedule channel
                        try:
                            await sched_channel.send(announcement)
                        except Exception as e:
                            logger.warning(f"Failed to send announcement to schedule channel: {e}")
            except Exception as e:
                logger.warning(f"Failed to update schedule embed after poll: {e}")

            # Also notify poll creator via DM (fall back to log channel)
            dm_ok = False
            if creator:
                dm_ok = await send_dm_safe(creator, content=announcement, fallback_channel=log_channel)
            if not dm_ok and log_channel:
                try:
                    await log_channel.send(announcement)
                except Exception:
                    pass
        else:
            logger.error(f"Failed to update event {target_event.id}")
            await mission_poll_repository.mark_failed(poll_data["id"])
            if log_channel:
                await log_channel.send(
                    f"❌ Failed to auto-schedule poll #{poll_data['id']} winner "
                    f"**{mission_name}** for {format_event_date(target_event.date)}."
                )


async def setup(bot):
    """Setup function to add the cog."""
    await bot.add_cog(MissionPollCommands(bot))
    logger.info("MissionPollCommands cog loaded")
