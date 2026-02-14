import discord
from discord.ext import commands
from discord import app_commands
import logging

from config import Config
from services.mission_poll_repository import mission_poll_repository
from services.event_repository import event_repository
from services.mission_poll_service import format_event_date, abbreviate_framework, send_dm_safe, get_log_channel

logger = logging.getLogger(__name__)


class CancelPollCommand(commands.Cog):
    """Cog for the /cancelpoll command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="cancelpoll",
        description="Cancel an active mission poll (marks it failed, deletes poll & links messages)",
    )
    @app_commands.describe(poll="Select the active poll to cancel")
    async def cancelpoll_command(
        self,
        interaction: discord.Interaction,
        poll: str,
    ):
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
        is_admin = any(getattr(r.permissions, "administrator", False) for r in member.roles)
        has_editor = any(r.name.strip().lower() == "editor" for r in member.roles)
        if not (is_admin or has_editor):
            await interaction.response.send_message(
                "❌ You must be an admin or have the @Editor role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Resolve poll ID
        try:
            poll_id = int(poll)
        except ValueError:
            await interaction.followup.send("❌ Invalid poll selection.", ephemeral=True)
            return

        # Fetch the poll record
        active_polls = await mission_poll_repository.get_active_polls(guild_id=guild.id)
        poll_data = next((p for p in active_polls if p["id"] == poll_id), None)

        if not poll_data:
            await interaction.followup.send(
                "❌ Poll not found or already completed/cancelled.", ephemeral=True
            )
            return

        # Delete Discord messages (poll + links embed)
        channel = guild.get_channel(poll_data["channel_id"])
        deleted_msgs = []
        if channel:
            for msg_id_key in ("poll_message_id", "links_message_id"):
                msg_id = poll_data.get(msg_id_key)
                if msg_id:
                    try:
                        msg = await channel.fetch_message(msg_id)
                        await msg.delete()
                        deleted_msgs.append(msg_id_key)
                    except discord.NotFound:
                        pass  # Already deleted
                    except Exception as e:
                        logger.warning(f"Failed to delete {msg_id_key} {msg_id}: {e}")

        # Mark as failed in DB
        await mission_poll_repository.mark_failed(poll_id)

        # Build confirmation
        target_event = await event_repository.get_event_by_id(poll_data["target_event_id"])
        event_label = format_event_date(target_event.date) if target_event else f"event #{poll_data['target_event_id']}"
        fw = abbreviate_framework(poll_data.get("framework_filter", ""))

        confirmation = (
            f"🗑️ **Poll #{poll_id}** for **{event_label}** [{fw}] has been cancelled.\n"
            f"Deleted messages: {', '.join(deleted_msgs) if deleted_msgs else 'none (already removed)'}.\n"
            f"You can now create a new poll for this event with `/missionpoll`."
        )
        await interaction.followup.send(confirmation, ephemeral=True)

        # Notify log channel
        log_channel = await get_log_channel(guild)
        if log_channel:
            try:
                await log_channel.send(
                    f"🗑️ Poll #{poll_id} for **{event_label}** [{fw}] cancelled by {interaction.user.display_name}."
                )
            except Exception:
                pass

    @cancelpoll_command.autocomplete("poll")
    async def poll_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            guild = interaction.guild
            if not guild:
                return []

            active_polls = await mission_poll_repository.get_active_polls(guild_id=guild.id)
            choices = []
            for p in active_polls:
                target_event = await event_repository.get_event_by_id(p["target_event_id"])
                if target_event:
                    event_label = format_event_date(target_event.date)
                else:
                    event_label = f"Event #{p['target_event_id']}"
                fw = abbreviate_framework(p.get("framework_filter", ""))
                label = f"Poll #{p['id']} — {event_label} [{fw}]"

                if current.lower() in label.lower() or not current:
                    choices.append(app_commands.Choice(name=label, value=str(p["id"])))

            return choices[:25]
        except Exception as e:
            logger.error(f"Cancel poll autocomplete error: {e}")
            return []


async def setup(bot):
    await bot.add_cog(CancelPollCommand(bot))
    logger.info("CancelPollCommand cog loaded")
