import discord
from discord.ext import commands
from discord import app_commands
from config import Config

class PingCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(name="ping", description="Test if the bot is responsive and show version.")
    async def ping(self, interaction: discord.Interaction):
        # IMMEDIATELY defer the response to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        from config import Config
        version = getattr(Config, "BOT_VERSION", "unknown")
        
        # Update schedule message embed
        from services.schedule_config_repository import schedule_config_repository
        from services.schedule_embed_service import build_schedule_embed
        
        try:
            config = await schedule_config_repository.get_config(interaction.guild.id)
            updated = False
            
            if config:
                channel = interaction.guild.get_channel(config["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(config["message_id"])
                        embed = await build_schedule_embed(interaction.guild)
                        await msg.edit(embed=embed)
                        updated = True
                    except Exception as e:
                        await interaction.followup.send(f"Pong! 🏓\nVersion: {version}\nFailed to update schedule message: {e}", ephemeral=True)
                        return
            
            # Send the response using followup since we deferred
            await interaction.followup.send(
                f"Pong! 🏓\nVersion: {version}" + ("\nSchedule message updated." if updated else ""),
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.followup.send(
                f"Pong! 🏓\nVersion: {version}\nError: {str(e)}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(PingCommand(bot))