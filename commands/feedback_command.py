import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import date, timedelta
import logging

from config import Config
from services.feedback_service import (
    check_and_create_feedback,
    create_feedback_thread,
    is_event_day,
)
from services.schedule_config_repository import schedule_config_repository
from services.raid_helper_service import raid_helper_service
from services.schedule_embed_service import find_briefing_post_link

logger = logging.getLogger(__name__)


class FeedbackCommands(commands.Cog):
    """Cog for automatic post-event feedback forum threads and a manual /feedback command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Start the background feedback loop when the cog loads."""
        self._feedback_loop.start()
        logger.info("Feedback background loop started")

    async def cog_unload(self):
        """Stop the background loop when the cog unloads."""
        self._feedback_loop.cancel()

    # ─── Background task: check every 15 minutes ──────────────────────
    @tasks.loop(minutes=15)
    async def _feedback_loop(self):
        """Periodically check if an event just ended and create a feedback thread."""
        try:
            for guild in self.bot.guilds:
                if guild.id != Config.GUILD_ID:
                    continue

                # Check config exists with feedback channel
                config = await schedule_config_repository.get_config(guild.id)
                if not config or not config.get("feedback_channel_id"):
                    continue

                thread = await check_and_create_feedback(guild)
                if thread:
                    logger.info(
                        f"Auto-created feedback thread '{thread.name}' in guild {guild.name}"
                    )
        except Exception as e:
            logger.error(f"Feedback loop error: {e}", exc_info=True)

    @_feedback_loop.before_loop
    async def _before_feedback_loop(self):
        await self.bot.wait_until_ready()

    # ─── Manual /feedback command ─────────────────────────────────────
    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="feedback",
        description="Manually create a feedback forum thread for an event date",
    )
    @app_commands.describe(
        event_date="The event date (DD-MM-YYYY). Defaults to today.",
        force="Re-create even if a feedback post already exists for this date",
    )
    async def feedback_command(
        self,
        interaction: discord.Interaction,
        event_date: str = None,
        force: bool = False,
    ):
        """Handle the /feedback command."""
        # Permission check: admin or @Editor
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", ephemeral=True
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)

        is_admin = any(
            getattr(r.permissions, "administrator", False) for r in member.roles
        )
        has_editor = any(r.name.strip().lower() == "editor" for r in member.roles)
        if not (is_admin or has_editor):
            await interaction.response.send_message(
                "❌ You must be an admin or have the @Editor role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Parse date
        target_date: date
        if event_date:
            try:
                parts = event_date.strip().split("-")
                target_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                await interaction.followup.send(
                    "❌ Invalid date format. Use `DD-MM-YYYY` (e.g. `01-03-2026`).",
                    ephemeral=True,
                )
                return
        else:
            target_date = date.today()

        # Validate it's an event day
        if not is_event_day(target_date):
            await interaction.followup.send(
                f"❌ {target_date.strftime('%A %d-%m-%Y')} is not a Thursday or Sunday (event day).",
                ephemeral=True,
            )
            return

        # Check config
        config = await schedule_config_repository.get_config(guild.id)
        if not config or not config.get("feedback_channel_id"):
            await interaction.followup.send(
                "❌ No feedback forum channel configured. Run `/configurefeedback` first.",
                ephemeral=True,
            )
            return

        # Create the feedback thread
        thread = await create_feedback_thread(guild, target_date, force=force)

        if thread:
            await interaction.followup.send(
                f"✅ Feedback thread created: {thread.mention}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"⚠️ A feedback post already exists for {target_date.strftime('%d-%m-%Y')}. "
                "Use `force: True` to re-create it.",
                ephemeral=True,
            )

    @feedback_command.autocomplete("event_date")
    async def event_date_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Suggest recent and upcoming event dates."""
        today = date.today()
        suggestions = []

        # Look 2 weeks back and 1 week forward for event days
        for delta in range(-14, 8):
            d = today + timedelta(days=delta)
            if is_event_day(d):
                label = d.strftime("%A %d-%m-%Y")
                value = d.strftime("%d-%m-%Y")
                if current.lower() in label.lower() or not current:
                    suggestions.append(app_commands.Choice(name=label, value=value))

        return suggestions[:25]

    # ─── /configurefeedback — Admin-only separate configure command ───
    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="configurefeedback",
        description="Configure the forum channel for post-event feedback threads (admin only)",
    )
    @app_commands.describe(
        feedback_channel_id="Select the forum channel for feedback threads",
    )
    async def configurefeedback_command(
        self,
        interaction: discord.Interaction,
        feedback_channel_id: str,
    ):
        """Admin-only command to set the feedback forum channel."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", ephemeral=True
            )
            return

        # Admin-only
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only server admins can use this command.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            channel_id_int = int(feedback_channel_id)
        except (ValueError, TypeError):
            await interaction.followup.send("❌ Invalid channel ID.", ephemeral=True)
            return

        channel = guild.get_channel(channel_id_int)
        if not channel or channel.type != discord.ChannelType.forum:
            await interaction.followup.send(
                "❌ The selected channel must be a forum channel.", ephemeral=True
            )
            return

        # Ensure base config exists before updating
        config = await schedule_config_repository.get_config(guild.id)
        if not config:
            await interaction.followup.send(
                "❌ Base configuration not found. Run `/configure` first to set up "
                "the schedule channel, then run this command.",
                ephemeral=True,
            )
            return

        await schedule_config_repository.update_feedback_channel(guild.id, channel_id_int)
        await interaction.followup.send(
            f"✅ Feedback forum channel set to {channel.mention}. "
            "Post-event feedback threads will be created here automatically.",
            ephemeral=True,
        )

    @configurefeedback_command.autocomplete("feedback_channel_id")
    async def configurefeedback_channel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for forum channels."""
        guild = interaction.guild
        if not guild:
            return []
        choices = []
        for channel in guild.channels:
            if channel.type == discord.ChannelType.forum and current.lower() in channel.name.lower():
                choices.append(
                    app_commands.Choice(name=f"# {channel.name}", value=str(channel.id))
                )
        return choices[:25]

    # ─── /updateevent — Manual Raid-Helper event update from briefing ─
    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="updateevent",
        description="Update a Raid-Helper event with content from its briefing post",
    )
    @app_commands.describe(
        event_date="The event date (DD-MM-YYYY).",
    )
    async def updateevent_command(
        self,
        interaction: discord.Interaction,
        event_date: str,
    ):
        """Manually update a Raid-Helper event's description and image from the briefing post."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", ephemeral=True
            )
            return

        # Permission check: admin or @Editor
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)

        is_admin = any(
            getattr(r.permissions, "administrator", False) for r in member.roles
        )
        has_editor = any(r.name.strip().lower() == "editor" for r in member.roles)
        if not (is_admin or has_editor):
            await interaction.response.send_message(
                "❌ You must be an admin or have the @Editor role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Parse date
        target_date: date
        try:
            parts = event_date.strip().split("-")
            target_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            await interaction.followup.send(
                "❌ Invalid date format. Use `DD-MM-YYYY` (e.g. `06-03-2026`).",
                ephemeral=True,
            )
            return

        if not is_event_day(target_date):
            await interaction.followup.send(
                f"❌ {target_date.strftime('%A %d-%m-%Y')} is not a Thursday or Sunday.",
                ephemeral=True,
            )
            return

        # Find the briefing channel
        config = await schedule_config_repository.get_config(guild.id)
        if not config or not config.get("briefing_channel_id"):
            await interaction.followup.send(
                "❌ No briefing channel configured. Run `/configure` first.",
                ephemeral=True,
            )
            return

        briefing_channel_id = config["briefing_channel_id"]
        forum_channel = guild.get_channel(briefing_channel_id)
        if not forum_channel or forum_channel.type != discord.ChannelType.forum:
            await interaction.followup.send(
                "❌ Briefing channel not found or is not a forum channel.",
                ephemeral=True,
            )
            return

        # Get the scheduled event(s) for this date to find the mission name
        from services.event_repository import event_repository

        events = await event_repository.get_events_by_guild_and_date_range(
            guild.id, target_date, target_date
        )

        # Find the mission event
        mission_event = None
        for ev in events:
            if ev.type == "Mission" and ev.name and ev.name.strip():
                mission_event = ev
                break

        if not mission_event:
            await interaction.followup.send(
                f"❌ No mission scheduled for {target_date.strftime('%A %d-%m-%Y')}. "
                "Schedule a mission first or wait for the poll to complete.",
                ephemeral=True,
            )
            return

        # ── Handle cancelled events ──
        if mission_event.name.strip().upper() == "EVENT CANCELLED":
            event_id = await raid_helper_service.find_event_id_by_date(guild.id, target_date)
            if not event_id:
                await interaction.followup.send(
                    f"❌ No Raid-Helper event found for {target_date.strftime('%A %d-%m-%Y')}.",
                    ephemeral=True,
                )
                return

            # Build cancellation description, preserving Training info on Thursdays
            cancelled_text = ":no_entry: **Cancelled**"
            if target_date.weekday() == 3:  # Thursday — keep Training section
                training_name = ""
                instructor_name = ""
                from services.event_repository import event_repository as ev_repo
                training_event = await ev_repo.get_event_by_guild_date_type(
                    guild.id, target_date, "Training"
                )
                if training_event:
                    training_cancelled = (training_event.name or "").strip().upper() == "EVENT CANCELLED"
                    if training_cancelled:
                        training_name = ""
                        instructor_name = ""
                    else:
                        training_name = training_event.name or ""
                        instructor_name = training_event.creator_name or ""

                # If training is also cancelled, build manually to show cancelled for both
                if not training_name and not instructor_name:
                    description = (
                        f"## Training <:Training:1173686838926512199>\n{cancelled_text}\n"
                        f"## Mission <:Mission:1173686836451885076>\n{cancelled_text}"
                    )
                else:
                    description = raid_helper_service.build_event_description(
                        cancelled_text,
                        is_thursday=True,
                        training_name=training_name,
                        instructor_name=instructor_name,
                    )
            else:
                description = cancelled_text

            cancelled_image = (
                "https://cdn.discordapp.com/attachments/862603286091923466/"
                "1479159129997049856/event-cancelled-rubber-stamp-seal-vector_140916-29949.png"
            )
            success = await raid_helper_service.update_event(
                event_id,
                description=description,
                image=cancelled_image,
                attendance="none",
            )
            if success:
                await interaction.followup.send(
                    f"✅ Raid-Helper event for **{target_date.strftime('%A %d-%m-%Y')}** "
                    f"updated to **EVENT CANCELLED**.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ Failed to update Raid-Helper event for {target_date.strftime('%A %d-%m-%Y')}.",
                    ephemeral=True,
                )
            return

        # Find matching briefing thread by name
        import asyncio

        try:
            briefing_link = await asyncio.wait_for(
                find_briefing_post_link(
                    guild, briefing_channel_id, mission_event.name, min_ratio=0.6
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            briefing_link = None

        # We need the actual thread, not just the link — find it directly
        briefing_thread = None
        threads = list(forum_channel.threads or [])
        try:
            async for thread in forum_channel.archived_threads(limit=100):
                threads.append(thread)
        except Exception:
            pass

        # Match by name (fuzzy)
        import difflib

        best_match = None
        best_ratio = 0.0
        for thread in threads:
            ratio = difflib.SequenceMatcher(
                None, thread.name.lower(), mission_event.name.lower()
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = thread

        if best_match and best_ratio >= 0.6:
            briefing_thread = best_match
        else:
            await interaction.followup.send(
                f"❌ Could not find a briefing post matching **{mission_event.name}** "
                f"in the briefing forum.",
                ephemeral=True,
            )
            return

        # Ensure starter message is fetched
        if not briefing_thread.starter_message:
            try:
                await briefing_thread.fetch_message(briefing_thread.id)
            except Exception as e:
                logger.warning(f"Could not fetch starter message: {e}")

        # Look up training info for Thursdays
        training_name = ""
        instructor_name = ""
        if target_date.weekday() == 3:  # Thursday
            from services.event_repository import event_repository as ev_repo
            training_event = await ev_repo.get_event_by_guild_date_type(
                guild.id, target_date, "Training"
            )
            if training_event:
                training_name = training_event.name or ""
                instructor_name = training_event.creator_name or ""

        # Update Raid-Helper event
        error = await raid_helper_service.update_event_from_briefing(
            server_id=guild.id,
            event_date=target_date,
            briefing_thread=briefing_thread,
            training_name=training_name,
            instructor_name=instructor_name,
        )

        if not error:
            await interaction.followup.send(
                f"✅ Updated Raid-Helper event for **{target_date.strftime('%A %d-%m-%Y')}** "
                f"with briefing from **{briefing_thread.name}**.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ Failed to update Raid-Helper event: {error}",
                ephemeral=True,
            )

    @updateevent_command.autocomplete("event_date")
    async def updateevent_date_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Suggest upcoming event dates."""
        today = date.today()
        suggestions = []
        for delta in range(-7, 15):
            d = today + timedelta(days=delta)
            if is_event_day(d):
                label = d.strftime("%A %d-%m-%Y")
                value = d.strftime("%d-%m-%Y")
                if current.lower() in label.lower() or not current:
                    suggestions.append(app_commands.Choice(name=label, value=value))
        return suggestions[:25]


async def setup(bot):
    """Setup function to add the cog."""
    await bot.add_cog(FeedbackCommands(bot))
    logger.info("FeedbackCommands cog loaded")
