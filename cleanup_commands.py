#!/usr/bin/env python3
"""
One-time cleanup script to remove all duplicate Discord slash commands.
Run this script once to completely clean up any duplicate commands.
"""

import asyncio
import discord
from discord.ext import commands
from config import Config

async def cleanup_commands():
    """Clean up all commands globally and in the guild."""
    
    # Validate configuration
    Config.validate_config()
    
    # Create a minimal bot instance for cleanup
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix='!', intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"Cleanup bot logged in as {bot.user}")
        
        try:
            # Step 1: Clear ALL global commands
            print("Clearing all global commands...")
            bot.tree.clear_commands(guild=None)
            global_cleared = await bot.tree.sync()
            print(f"Cleared {len(global_cleared)} global commands")
            
            # Step 2: Clear ALL guild commands  
            print(f"Clearing all commands from guild {Config.GUILD_ID}...")
            guild_obj = discord.Object(id=Config.GUILD_ID)
            bot.tree.clear_commands(guild=guild_obj)
            guild_cleared = await bot.tree.sync(guild=guild_obj)
            print(f"Cleared {len(guild_cleared)} guild commands")
            
            print("✅ Command cleanup completed successfully!")
            print("Now restart your main bot to register the commands properly.")
            
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")
        finally:
            await bot.close()
    
    # Start the cleanup bot
    await bot.start(Config.DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    print("🧹 Starting Discord command cleanup...")
    print("This will remove ALL slash commands from your bot.")
    print("After this completes, restart your main bot.")
    print("")
    
    try:
        asyncio.run(cleanup_commands())
    except KeyboardInterrupt:
        print("Cleanup cancelled by user")
    except Exception as e:
        print(f"Cleanup failed: {e}")