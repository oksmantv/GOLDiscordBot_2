import discord
from services.schedule_embed_service import build_schedule_embed
from services import event_repository
from datetime import date

# This should be replaced with persistent config storage
SCHEDULE_CONFIG_KEY = "schedule_config"

class ScheduleUpdateService:
    def __init__(self, bot, config_cog):
        self.bot = bot
        self.config_cog = config_cog  # Reference to ConfigureCommand cog

    async def update_schedule_message(self):
        config = getattr(self.config_cog, 'config', {}).get(SCHEDULE_CONFIG_KEY)
        if not config:
            return False
        channel_id = config.get('channel_id')
        message_id = config.get('message_id')
        if not channel_id or not message_id:
            return False
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return False
        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            return False
        # Update the schedule embed for this guild
        embed = await build_schedule_embed(channel.guild)
        await message.edit(embed=embed)
        return True
