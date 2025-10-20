#!/usr/bin/env python3
"""
Recovery script to force re-register slash commands.
Run this if commands disappeared after cleanup.
"""

import asyncio
import discord
from discord.ext import commands
from config import Config

async def force_register_commands():
    """Force register all commands."""
    
    # Validate configuration
    Config.validate_config()
    
    # Create a minimal bot instance
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix='!', intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"Recovery bot logged in as {bot.user}")
        
        try:
            # Load the command extensions
            await bot.load_extension('commands.schedule_commands')
            print("✅ Loaded schedule_commands")
            await bot.load_extension('commands.ping_command')
            print("✅ Loaded ping_command")
            await bot.load_extension('commands.configure_command')
            print("✅ Loaded configure_command")
            
            # Check what commands we have
            print(f"Commands to register: {[cmd.name for cmd in bot.tree.get_commands()]}")
            
            # Force sync to guild
            guild_obj = discord.Object(id=Config.GUILD_ID)
            guild_synced = await bot.tree.sync(guild=guild_obj)
            print(f"✅ Force synced {len(guild_synced)} commands to guild {Config.GUILD_ID}")
            print(f"Commands synced: {[cmd.name for cmd in guild_synced]}")
            
            print("🎉 Commands should now appear in your Discord server!")
            
        except Exception as e:
            print(f"❌ Error during recovery: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await bot.close()
    
    # Start the recovery bot
    await bot.start(Config.DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    print("🔄 Starting command recovery...")
    print("This will force re-register all slash commands.")
    print("")
    
    try:
        asyncio.run(force_register_commands())
    except KeyboardInterrupt:
        print("Recovery cancelled by user")
    except Exception as e:
        print(f"Recovery failed: {e}")
        import traceback
        traceback.print_exc()