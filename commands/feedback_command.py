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
                "❌ No feedback forum channel configured. Run `/configure` first.",
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


async def setup(bot):
    """Setup function to add the cog."""
    await bot.add_cog(FeedbackCommands(bot))
    logger.info("FeedbackCommands cog loaded")
