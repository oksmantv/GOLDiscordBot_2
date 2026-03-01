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
        intents.members = True  # Required for roster member scanning

        super().__init__(
            command_prefix=Config.BOT_PREFIX,
            intents=intents,
            help_command=None
        )

        self._background_tasks_started = False
        self._on_ready_fired = False  # Guard against multiple on_ready calls

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
            await self.load_extension('commands.roster_command')
            logger.info("Loaded roster_command Cog")

            # Print all app commands before syncing
            logger.info(f"App commands before sync: {[cmd.name for cmd in self.tree.get_commands()]} (total: {len(self.tree.get_commands())})")

            # Sync commands to guild - commands should auto-register from the @app_commands.guilds decorators
            test_guild_id = int(Config.GUILD_ID)
            guild_obj = discord.Object(id=test_guild_id)
            
            # Clear global commands locally (no API call) to prevent duplicates
            self.tree.clear_commands(guild=None)
            logger.info("Cleared global command tree (local only).")
            
            # Sync guild commands (single API call)
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

    async def update_loa_message_on_startup(self):
        from services.loa_service import update_summary_message
        from services.loa_service import (
            remove_active_role, restore_active_role,
            send_expiry_dm, delete_loa_announcement,
            ACTIVE_ROLE_ID, UK_TZ,
        )
        from services.loa_repository import loa_repository
        from services.loa_config_repository import loa_config_repository
        from datetime import datetime

        for guild in self.guilds:
            try:
                # ── Run expiry logic first (catches LOAs that expired while bot was offline) ──
                now_uk = datetime.now(UK_TZ)
                today = now_uk.date()
                is_notification_hours = 8 <= now_uk.hour <= 16
                summary_needs_update = False

                active_loas = await loa_repository.get_active_loas_by_guild(guild.id)
                logger.info(f"[LOA STARTUP] Guild {guild.name}: {len(active_loas)} active LOAs found, today={today}")

                for loa_entry in active_loas:
                    try:
                        # Ensure date comparison works even if DB returns datetime
                        end_date = loa_entry["end_date"]
                        start_date = loa_entry["start_date"]
                        if hasattr(end_date, 'date'):
                            end_date = end_date.date()
                        if hasattr(start_date, 'date'):
                            start_date = start_date.date()

                        logger.info(
                            f"[LOA STARTUP] LOA #{loa_entry['id']} user={loa_entry['user_id']} "
                            f"start={start_date} end={end_date} "
                            f"expired={loa_entry['expired']} end<today={end_date < today}"
                        )

                        # Remove @Active for LOAs that have started
                        if start_date <= today:
                            await remove_active_role(guild, loa_entry["user_id"])

                        # Expire LOAs whose end date has passed
                        if end_date < today:
                            logger.info(f"[LOA STARTUP] Expiring LOA #{loa_entry['id']}")
                            await loa_repository.mark_expired(loa_entry["id"])
                            summary_needs_update = True

                            try:
                                await delete_loa_announcement(guild, loa_entry)
                            except Exception as e:
                                logger.warning(f"[LOA STARTUP] Failed to delete announcement for LOA #{loa_entry['id']}: {e}")

                            remaining = await loa_repository.get_active_loas_by_user(
                                guild.id, loa_entry["user_id"]
                            )
                            still_on_leave = any(
                                (l["start_date"].date() if hasattr(l["start_date"], 'date') else l["start_date"]) <= today
                                for l in remaining
                            )

                            role_restored = False
                            if not still_on_leave:
                                role_restored = await restore_active_role(guild, loa_entry["user_id"])

                            if is_notification_hours:
                                try:
                                    await send_expiry_dm(guild, loa_entry, role_restored=role_restored)
                                except Exception as e:
                                    logger.warning(f"[LOA STARTUP] Failed to send expiry DM for LOA #{loa_entry['id']}: {e}")
                                await loa_repository.mark_notified(loa_entry["id"])
                            logger.info(f"[LOA STARTUP] LOA #{loa_entry['id']} expired successfully")
                    except Exception as e:
                        logger.error(f"[LOA STARTUP] Error processing LOA #{loa_entry.get('id', '?')}: {e}", exc_info=True)

                if summary_needs_update:
                    logger.info(f"Expired stale LOAs on startup for guild {guild.name}")

                # ── Rebuild the summary embed ──
                await update_summary_message(self, guild.id)
                logger.info(f"Updated LOA summary message for guild {guild.name}")
            except Exception as e:
                logger.error(f"Failed to update LOA on startup for guild {guild.name}: {e}", exc_info=True)

    async def update_roster_message_on_startup(self):
        from services.roster_service import scan_roster, update_roster_message
        for guild in self.guilds:
            try:
                await scan_roster(guild)
                await update_roster_message(self, guild.id)
                logger.info(f"Updated Roster message for guild {guild.name}")
            except Exception as e:
                logger.warning(f"Failed to update Roster message for guild {guild.name}: {e}")

    async def on_ready(self):
        """Called when the bot is ready (also fires on reconnects)."""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')

        # Guard: only run expensive startup work once, not on every reconnect
        if self._on_ready_fired:
            logger.info("on_ready fired again (reconnect) — skipping startup API calls")
            return
        self._on_ready_fired = True

        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="the schedule 📅"
        )
        await self.change_presence(activity=activity)

        # Small delay between API calls to avoid burst rate limits
        await asyncio.sleep(1)

        # Update schedule message on startup
        await self.update_schedule_message_on_startup()

        await asyncio.sleep(1)

        # Update LOA summary message on startup
        await self.update_loa_message_on_startup()

        await asyncio.sleep(1)

        # Update roster message on startup
        await self.update_roster_message_on_startup()

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