import discord
from discord.ext import commands, tasks
import asyncio
import logging
from config import Config
from services import db_connection, initialize_database, event_population_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GOLBot(commands.Bot):
    """Guild Operations Logistics Discord Bot."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        super().__init__(
            command_prefix=Config.BOT_PREFIX,
            intents=intents,
            help_command=None
        )

        self._background_tasks_started = False

    @tasks.loop(hours=12)
    async def _event_population_maintenance_loop(self):
        try:
            summary = await event_population_service.maintain_event_population()
            created = summary.get('created', 0) if isinstance(summary, dict) else 0
            if created:
                logger.info(
                    f"Event maintenance populated events: Created={summary.get('created')}, "
                    f"Skipped={summary.get('skipped')}, Failed={summary.get('failed')}, Total={summary.get('total')}"
                )
                await self.update_schedule_message_on_startup()
        except Exception as e:
            logger.warning(f"Event maintenance loop failed: {e}")

    @_event_population_maintenance_loop.before_loop
    async def _before_event_population_maintenance_loop(self):
        await self.wait_until_ready()

    async def setup_hook(self):
        """Called when the bot is starting up."""
        logger.info("Setting up bot...")

        try:
            # Validate configuration
            Config.validate_config()
            logger.info("Configuration validated successfully")

            # Initialize database connection
            await db_connection.create_pool()
            logger.info("Database connection established")

            # Initialize database tables
            await initialize_database()
            logger.info("Database tables initialized")

            # Populate initial events
            population_summary = await event_population_service.populate_8_week_range()
            logger.info(
                f"Event population summary: Created={population_summary['created']}, "
                f"Skipped={population_summary['skipped']}, Failed={population_summary['failed']}, "
                f"Total={population_summary['total']}"
            )

            # Start background maintenance tasks once
            if not self._background_tasks_started:
                self._event_population_maintenance_loop.start()
                self._background_tasks_started = True
                logger.info("Started background event population maintenance loop")

            # Load command extensions
            await self.load_extension('commands.schedule_commands')
            logger.info("Loaded schedule_commands Cog")
            await self.load_extension('commands.ping_command')
            logger.info("Loaded ping_command Cog")
            await self.load_extension('commands.configure_command')
            logger.info("Commands loaded successfully")
            await self.load_extension('commands.populate_command')
            logger.info("Loaded populate_command Cog")
            await self.load_extension('commands.mission_poll_command')
            logger.info("Loaded mission_poll_command Cog")
            await self.load_extension('commands.cancel_poll_command')
            logger.info("Loaded cancel_poll_command Cog")
            await self.load_extension('commands.loa_command')
            logger.info("Loaded loa_command Cog")

            # Print all app commands before syncing
            logger.info(f"App commands before sync: {[cmd.name for cmd in self.tree.get_commands()]} (total: {len(self.tree.get_commands())})")

            # Sync commands to guild - commands should auto-register from the @app_commands.guilds decorators
            test_guild_id = int(Config.GUILD_ID)
            guild_obj = discord.Object(id=test_guild_id)
            
            # First, clear any global commands to prevent duplicates
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("Cleared global commands to prevent duplicates.")
            
            # Sync guild commands
            guild_synced = await self.tree.sync(guild=guild_obj)
            logger.info(f"Synced {len(guild_synced)} commands to guild {test_guild_id}: {[cmd.name for cmd in guild_synced]}")

        except Exception as e:
            logger.error(f"Error during setup: {e}")
            raise

    async def update_schedule_message_on_startup(self):
        from services.schedule_config_repository import schedule_config_repository
        from services.schedule_embed_service import build_schedule_embed
        for guild in self.guilds:
            config = await schedule_config_repository.get_config(guild.id)
            if config:
                channel = guild.get_channel(config["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(config["message_id"])
                        embed = await build_schedule_embed(guild)
                        await msg.edit(embed=embed)
                        logger.info(f"Updated schedule message for guild {guild.name}")
                    except Exception as e:
                        logger.warning(f"Failed to update schedule message for guild {guild.name}: {e}")

    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')

        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="the schedule 📅"
        )
        await self.change_presence(activity=activity)

        # Update schedule message on startup
        await self.update_schedule_message_on_startup()

    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild."""
        logger.info(f'Joined guild: {guild.name} (ID: {guild.id})')

        # Check if this is the configured guild
        if guild.id != Config.GUILD_ID:
            logger.warning(f'Joined unexpected guild {guild.name}. Leaving...')
            await guild.leave()

    async def on_command_error(self, ctx, error):
        """Handle command errors."""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands

        logger.error(f'Command error: {error}')

        if ctx.interaction:
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message(
                    "❌ An error occurred while processing your command.",
                    ephemeral=True
                )

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        """Handle application command errors."""
        logger.error(f'App command error: {error}')

        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ An error occurred while processing your command.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ An error occurred while processing your command.",
                ephemeral=True
            )

    async def close(self):
        """Clean up when the bot is closing."""
        logger.info("Bot is shutting down...")
        await db_connection.close_pool()
        await super().close()

async def main():
    """Main function to run the bot."""
    bot = GOLBot()

    try:
        await bot.start(Config.DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())