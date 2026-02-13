print('[DEBUG] configure_command.py imported')
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from config import Config
from services.schedule_config_repository import schedule_config_repository

class ConfigureCommand(commands.Cog):
    # (Test command removed)
    def __init__(self, bot):
        self.bot = bot
        # Debug: print all app commands registered in this cog after init
        try:
            tree = getattr(bot, 'tree', None)
            if tree:
                print(f"[DEBUG] Commands in ConfigureCommand: {[cmd.name for cmd in tree.get_commands()]}")
        except Exception as e:
            print(f"[DEBUG] Error printing commands in ConfigureCommand: {e}")

    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(name="configure", description="Configure schedule channel, message, and briefing forum channel.")
    @app_commands.describe(
        channel_id="Select the channel for schedule updates",
        message_id="Select or create the schedule message in the channel",
        briefing_channel_id="Select the forum channel for mission briefings",
        log_channel_id="Select the channel for bot log/fallback messages (optional)"
    )
    async def configure(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        message_id: str,
        briefing_channel_id: str,
        log_channel_id: str = None
    ):
        print(f"[DEBUG] configure called with: channel_id={channel_id}, message_id={message_id}, briefing_channel_id={briefing_channel_id}")
        print(f"[DEBUG] interaction.guild: {getattr(interaction, 'guild', None)}")
        # Restrict to admins only
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only server admins can use this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        # Convert channel_id and briefing_channel_id to int for lookup
        try:
            channel_id_int = int(channel_id)
            briefing_channel_id_int = int(briefing_channel_id)
        except Exception:
            await interaction.followup.send(f"❌ Invalid channel ID(s).", ephemeral=True)
            return

        # Convert channel_id to TextChannel
        channel = interaction.guild.get_channel(channel_id_int)
        if not channel:
            await interaction.followup.send(f"❌ Channel not found.", ephemeral=True)
            return

        # Convert briefing_channel_id to ForumChannel
        briefing_channel = interaction.guild.get_channel(briefing_channel_id_int)
        if not briefing_channel or briefing_channel.type != discord.ChannelType.forum:
            await interaction.followup.send(f"❌ Briefing channel must be a forum channel.", ephemeral=True)
            return

        # If user chose to create a new message
        if str(message_id) == "CREATE_NEW":
            msg = await channel.send("GOL Event Schedule")
            message_id = msg.id
            await interaction.followup.send(f"✅ Created new schedule message in {channel.mention}.", ephemeral=True)
            message_id_int = msg.id
        else:
            await interaction.followup.send(f"✅ Schedule will use message ID `{message_id}` in {channel.mention}.", ephemeral=True)
            try:
                message_id_int = int(message_id)
            except Exception:
                await interaction.followup.send(f"❌ Invalid message ID.", ephemeral=True)
                return

        # Save config to database
        log_channel_id_int = None
        if log_channel_id:
            try:
                log_channel_id_int = int(log_channel_id)
                log_ch = interaction.guild.get_channel(log_channel_id_int)
                if not log_ch:
                    await interaction.followup.send(f"⚠️ Log channel not found, saving without it.", ephemeral=True)
                    log_channel_id_int = None
            except Exception:
                log_channel_id_int = None

        await schedule_config_repository.set_config(
            interaction.guild.id,
            channel_id_int,
            message_id_int,
            briefing_channel_id_int,
            log_channel_id_int
        )

        # Populate forum tag cache on configure
        try:
            from services.forum_tag_service import forum_tag_service
            await forum_tag_service.refresh_tags(interaction.guild, briefing_channel_id_int)
        except Exception as e:
            print(f"[DEBUG] Failed to refresh forum tag cache on configure: {e}")
    @configure.autocomplete('channel_id')
    async def channel_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        print(f"[DEBUG] channel_autocomplete called with current='{current}', guild={getattr(interaction, 'guild', None)}")
        guild = interaction.guild
        if not guild:
            print("[DEBUG] channel_autocomplete: No guild found.")
            return []
        choices = []
        for channel in guild.text_channels:
            if current.lower() in channel.name.lower():
                choices.append(app_commands.Choice(name=f"#{channel.name}", value=str(channel.id)))
        print(f"[DEBUG] channel_autocomplete: choices={choices}")
        return choices[:25]

    @configure.autocomplete('briefing_channel_id')
    async def briefing_channel_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        print(f"[DEBUG] briefing_channel_autocomplete called with current='{current}', guild={getattr(interaction, 'guild', None)}")
        guild = interaction.guild
        if not guild:
            print("[DEBUG] briefing_channel_autocomplete: No guild found.")
            return []
        choices = []
        for channel in guild.channels:
            if channel.type == discord.ChannelType.forum and current.lower() in channel.name.lower():
                choices.append(app_commands.Choice(name=f"# {channel.name}", value=str(channel.id)))
        print(f"[DEBUG] briefing_channel_autocomplete: choices={choices}")
        return choices[:25]

    @configure.autocomplete('log_channel_id')
    async def log_channel_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if not guild:
            return []
        choices = []
        for channel in guild.text_channels:
            if current.lower() in channel.name.lower():
                choices.append(app_commands.Choice(name=f"#{channel.name}", value=str(channel.id)))
        return choices[:25]

    @configure.autocomplete('message_id')
    async def message_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        print(f"[DEBUG] message_id_autocomplete called with current='{current}', interaction.namespace={getattr(interaction, 'namespace', None)}")
        channel_id = None
        if hasattr(interaction, 'namespace') and hasattr(interaction.namespace, 'channel_id'):
            channel_id = interaction.namespace.channel_id
        print(f"[DEBUG] message_id_autocomplete: channel_id from namespace = {channel_id}")
        if not channel_id:
            print("[DEBUG] message_id_autocomplete: No channel_id found.")
            return [app_commands.Choice(name="Select a channel above first", value="NO_CHANNEL_SELECTED")]
        guild = interaction.guild
        channel = guild.get_channel(int(channel_id)) if guild else None
        if channel:
            print(f"[DEBUG] message_id_autocomplete: Found channel: {channel} (id={channel.id})")
        else:
            print(f"[DEBUG] message_id_autocomplete: No channel found for channel_id {channel_id}.")
            return []
        # Fetch oldest 5 messages (ordered oldest first)
        messages = []
        try:
            async for msg in channel.history(limit=50, oldest_first=True):
                messages.append(msg)
                if len(messages) >= 5:
                    break
        except Exception as e:
            print(f"[DEBUG] message_id_autocomplete: Exception: {e}")
            return []
        # Sort messages by created_at (oldest first, though discord.py already does this with oldest_first=True)
        messages.sort(key=lambda m: m.created_at)
        choices = [app_commands.Choice(name="➕ Create new schedule message", value="CREATE_NEW")]
        for msg in messages:
            preview = (msg.content[:30] + "...") if len(msg.content) > 30 else msg.content
            choices.append(app_commands.Choice(name=f"{msg.id}: {preview}", value=str(msg.id)))
        print(f"[DEBUG] message_id_autocomplete: choices={choices}")
        return choices[:25]

async def setup(bot):
    print('[DEBUG] setup() called in configure_command.py')
    cog = ConfigureCommand(bot)
    await bot.add_cog(cog)
