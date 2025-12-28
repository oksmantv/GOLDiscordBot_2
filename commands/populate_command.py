import discord
from discord.ext import commands
from discord import app_commands
from datetime import date, timedelta
from config import Config
from services import event_population_service


class PopulateCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="populate",
        description="Generate upcoming Thursday/Sunday schedule events for the next N weeks",
    )
    @app_commands.describe(
        weeks="How many weeks ahead to ensure exist (each week creates Thu Training+Mission and Sun Mission)"
    )
    async def populate(self, interaction: discord.Interaction, weeks: app_commands.Range[int, 1, 52]):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)

        is_admin = any(getattr(r.permissions, 'administrator', False) for r in member.roles)
        has_editor = any(r.name.strip().lower() == "editor" for r in member.roles)
        if not (is_admin or has_editor):
            await interaction.response.send_message(
                "❌ You must be an admin or have the @Editor role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        start_date = date.today()
        end_date = start_date + timedelta(weeks=weeks)

        try:
            summary = await event_population_service.populate_events_for_date_range(start_date, end_date)

            await interaction.followup.send(
                "✅ Population complete. "
                f"Created={summary.get('created', 0)}, "
                f"Skipped={summary.get('skipped', 0)}, "
                f"Failed={summary.get('failed', 0)}, "
                f"Total={summary.get('total', 0)}.\n"
                f"Range: {start_date.isoformat()} → {end_date.isoformat()}",
                ephemeral=True,
            )

            # Refresh schedule message if configured
            try:
                from services.schedule_config_repository import schedule_config_repository
                from services.schedule_embed_service import build_schedule_embed

                config = await schedule_config_repository.get_config(guild.id)
                if config:
                    channel = guild.get_channel(config["channel_id"])
                    if channel:
                        msg = await channel.fetch_message(config["message_id"])
                        embed = await build_schedule_embed(guild)
                        await msg.edit(embed=embed)
            except Exception:
                # Non-fatal; population succeeded even if embed refresh fails
                pass

        except Exception as e:
            await interaction.followup.send(f"❌ Population failed: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PopulateCommand(bot))
