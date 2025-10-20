import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from config import Config
from models import Event
from services import event_repository, date_filter_service

class ScheduleCommands(commands.Cog):
    """Discord slash commands for schedule management."""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(name="schedule", description="Update event details in the schedule")
    @app_commands.describe(
        event="Select an event to update",
        name="Set the event name/description", 
        author="Set the event organizer (optional - defaults to you)"
    )
    async def schedule_command(
        self,
        interaction: discord.Interaction,
        event: str,
        name: str,
        author: Optional[str] = None
    ):
        """Handle the /schedule command."""
        # Restrict to admins or users with the @Editor role
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        member = interaction.user
        # If not a Member object, fetch it
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)
        is_admin = any(getattr(r.permissions, 'administrator', False) for r in member.roles)
        has_editor = any(r.name.strip().lower() == "editor" for r in member.roles)
        if not (is_admin or has_editor):
            await interaction.response.send_message("❌ You must be an admin or have the @Editor role to use this command.", ephemeral=True)
            return
        await interaction.response.defer()

        try:
            # Get available events (wide search handled by autocomplete)
            available_events = await date_filter_service.get_available_events(search=event)
            
            if not available_events:
                await interaction.followup.send(
                    "❌ No events found matching your search.",
                    ephemeral=True
                )
                return
            
            # Find the selected event
            selected_event = await date_filter_service.find_event_by_formatted_string(event, available_events)
            if not selected_event:
                await interaction.followup.send(
                    "❌ Selected event not found. Please try again.", 
                    ephemeral=True
                )
                return
            
            # Prepare update data
            update_author = author if author is not None else interaction.user.display_name
            creator_id = interaction.user.id
            
            # Update the event
            success = await event_repository.update_event(
                selected_event.id,
                name=name,
                creator_id=creator_id,
                creator_name=update_author
            )
            
            if success:
                # Update the schedule message after event update
                from services.schedule_config_repository import schedule_config_repository
                from services.schedule_embed_service import build_schedule_embed
                config = await schedule_config_repository.get_config(interaction.guild.id)
                if config:
                    channel = interaction.guild.get_channel(config["channel_id"])
                    if channel:
                        try:
                            msg = await channel.fetch_message(config["message_id"])
                            embed = await build_schedule_embed(interaction.guild)
                            await msg.edit(embed=embed)
                        except Exception as e:
                            await interaction.followup.send(f"Event updated, but failed to update schedule message: {e}", ephemeral=True)
                            return
                # Create success embed
                embed = discord.Embed(
                    title="✅ Event Updated Successfully",
                    color=discord.Color.green(),
                    timestamp=interaction.created_at
                )
                event_date_str = selected_event.date.strftime('%A, %d %B %Y')
                embed.add_field(
                    name="Event",
                    value=f"{selected_event.type} - {event_date_str}",
                    inline=False
                )
                embed.add_field(
                    name="Name/Description", 
                    value=name, 
                    inline=False
                )
                embed.add_field(
                    name="Organizer", 
                    value=update_author, 
                    inline=False
                )
                embed.set_footer(text=f"Updated by {interaction.user.display_name}")
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "❌ Failed to update event. Please try again later.", 
                    ephemeral=True
                )
                
        except Exception as e:
            await interaction.followup.send(
                f"❌ An error occurred: {str(e)}", 
                ephemeral=True
            )
    
    @schedule_command.autocomplete('event')
    async def schedule_event_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for event selection, supports wide search by date/name."""
        try:
            available_events = await date_filter_service.get_available_events(search=current)

            choices = []
            for event in available_events:
                formatted = date_filter_service.format_event_for_dropdown(event)
                choices.append(app_commands.Choice(name=formatted, value=formatted))

            return choices[:25]
        except Exception as e:
            print(f"Autocomplete error: {e}")
            return []

async def setup(bot):
    """Setup function to add the cog."""
    await bot.add_cog(ScheduleCommands(bot))