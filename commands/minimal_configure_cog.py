print('[DEBUG] minimal_configure_cog.py imported')
import discord
from discord.ext import commands
from discord import app_commands

class MinimalConfigureCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            tree = getattr(bot, 'tree', None)
            if tree:
                print(f"[DEBUG] Commands in MinimalConfigureCog: {[cmd.name for cmd in tree.get_commands()]}")
        except Exception as e:
            print(f"[DEBUG] Error printing commands in MinimalConfigureCog: {e}")

    @app_commands.command(name="configure_test", description="Minimal test: configure command only.")
    @app_commands.describe(
        channel_id="Test channel ID"
        # message_id="Test message ID",
        # briefing_channel_id="Test briefing channel ID"
    )
    @app_commands.guilds(discord.Object(id=437979456196444161))
    async def configure(
        self,
        interaction: discord.Interaction,
        channel_id: str
        # , message_id: str, briefing_channel_id: str
    ):
        # Convert to int if needed
        try:
            channel_id_int = int(channel_id)
        except Exception:
            channel_id_int = channel_id
        # try:
        #     briefing_channel_id_int = int(briefing_channel_id)
        # except Exception:
        #     briefing_channel_id_int = briefing_channel_id
        # await interaction.response.send_message(f"Minimal configure: {channel_id_int}, {message_id}, {briefing_channel_id_int}", ephemeral=True)
        await interaction.response.send_message(f"Minimal configure: {channel_id_int}", ephemeral=True)

async def setup(bot):
    print('[DEBUG] setup() called in minimal_configure_cog.py')
    await bot.add_cog(MinimalConfigureCog(bot))
