import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging

from config import Config
from services.roster_config_repository import roster_config_repository
from services.roster_service import (
    scan_roster,
    build_roster_embeds,
    update_roster_message,
)
from services.log_channel_service import report_failure

logger = logging.getLogger(__name__)


class RosterCommands(commands.Cog):
    """Cog for Platoon Roster slash commands and hourly background refresh."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self._roster_refresh_loop.start()
        logger.info("Roster refresh background task started")

    async def cog_unload(self):
        self._roster_refresh_loop.cancel()

    # ─── /configureroster ──────────────────────────────────────────────

    @app_commands.command(
        name="configureroster",
        description="Configure the Platoon Roster channel (Admin only)",
    )
    @app_commands.describe(channel="The channel to post the Platoon Roster embed in")
    @app_commands.guilds(discord.Object(id=Config.GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def configure_roster_command(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # ── Clean up old config if it exists ──
        old_config = await roster_config_repository.get_config(guild.id)
        if old_config:
            old_channel = guild.get_channel(old_config["channel_id"])
            if old_channel:
                try:
                    old_msg = await old_channel.fetch_message(old_config["message_id"])
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

        # ── Perform initial roster scan ──
        await interaction.followup.send(
            "⏳ Scanning guild members… this may take a moment.",
            ephemeral=True,
        )
        summary = await scan_roster(guild)

        # ── Post the roster embeds ──
        embeds = await build_roster_embeds(guild.id)
        msg = await channel.send(embeds=embeds)

        # ── Save config ──
        await roster_config_repository.set_config(guild.id, channel.id, msg.id)

        await interaction.followup.send(
            f"✅ Platoon Roster configured in {channel.mention}!\n"
            f"👥 **{summary['total']}** members scanned — "
            f"**{summary['active']}** active, **{summary['reserve']}** reserves.\n"
            f"The roster will refresh automatically every hour.",
            ephemeral=True,
        )

    # ─── /updateroster ─────────────────────────────────────────────────

    @app_commands.command(
        name="updateroster",
        description="Force a fresh scan of the Platoon Roster",
    )
    @app_commands.guilds(discord.Object(id=Config.GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def update_roster_command(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(ephemeral=True)

        config = await roster_config_repository.get_config(interaction.guild_id)
        if not config:
            await interaction.followup.send(
                "❌ The roster has not been configured yet. "
                "An admin needs to run `/configureroster` first.",
                ephemeral=True,
            )
            return

        # ── Scan and update ──
        summary = await scan_roster(interaction.guild)
        await update_roster_message(self.bot, interaction.guild_id)

        await interaction.followup.send(
            f"✅ Roster refreshed!\n"
            f"👥 **{summary['total']}** members — "
            f"**{summary['active']}** active, **{summary['reserve']}** reserves.\n"
            f"🔄 **{summary['updated']}** updated, **{summary['removed']}** removed.",
            ephemeral=True,
        )

    # ─── Hourly Background Loop ───────────────────────────────────────

    @tasks.loop(hours=1)
    async def _roster_refresh_loop(self):
        """Hourly: re-scan members and update the roster embed."""
        try:
            for guild in self.bot.guilds:
                config = await roster_config_repository.get_config(guild.id)
                if not config:
                    continue

                await scan_roster(guild)
                await update_roster_message(self.bot, guild.id)
                logger.info(f"Hourly roster refresh complete for {guild.name}")

        except Exception as e:
            logger.error(f"Roster refresh loop error: {e}", exc_info=True)
            for guild in self.bot.guilds:
                if guild.id == Config.GUILD_ID:
                    await report_failure(
                        guild,
                        "Roster Loop",
                        "Hourly roster refresh loop crashed.",
                        e,
                    )
                    break

    @_roster_refresh_loop.before_loop
    async def _before_roster_refresh(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(RosterCommands(bot))
