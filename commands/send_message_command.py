import discord
from discord.ext import commands
from discord import app_commands

from config import Config


class SendMessageCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guilds(Config.GUILD_ID)
    @app_commands.command(
        name="sendmessage",
        description="Send a bot message to a user DM or a channel (admin only).",
    )
    @app_commands.describe(
        send_to="Pick a user or a channel",
        text="Message text to send",
    )
    async def sendmessage(
        self,
        interaction: discord.Interaction,
        send_to: str,
        text: str,
    ):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only server admins can use this command.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        if send_to.startswith("user:"):
            user_id_str = send_to.split(":", 1)[1]
            try:
                user_id = int(user_id_str)
            except ValueError:
                await interaction.followup.send("❌ Invalid user selection.", ephemeral=True)
                return

            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    await interaction.followup.send("❌ User not found.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    await interaction.followup.send(
                        f"❌ Failed to fetch user: {e}", ephemeral=True
                    )
                    return

            try:
                await member.send(text)
                await interaction.followup.send(
                    f"✅ Sent DM to {member.mention}.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ Could not DM this user (DMs may be disabled).",
                    ephemeral=True,
                )
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"❌ Failed to send DM: {e}", ephemeral=True
                )
            return

        if send_to.startswith("channel:"):
            channel_id_str = send_to.split(":", 1)[1]
            try:
                channel_id = int(channel_id_str)
            except ValueError:
                await interaction.followup.send("❌ Invalid channel selection.", ephemeral=True)
                return

            channel = guild.get_channel(channel_id)
            if channel is None:
                await interaction.followup.send("❌ Channel not found.", ephemeral=True)
                return

            if not hasattr(channel, "send"):
                await interaction.followup.send(
                    "❌ This channel type does not support sending messages.",
                    ephemeral=True,
                )
                return

            me = guild.me or guild.get_member(self.bot.user.id)
            if me is None:
                await interaction.followup.send(
                    "❌ Could not validate bot permissions for that channel.",
                    ephemeral=True,
                )
                return

            perms = channel.permissions_for(me)
            can_send = perms.send_messages or perms.send_messages_in_threads
            if not can_send:
                await interaction.followup.send(
                    "❌ I do not have permission to send messages there.",
                    ephemeral=True,
                )
                return

            try:
                await channel.send(text)
                await interaction.followup.send(
                    f"✅ Message sent to {channel.mention}.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ Permission denied while sending to that channel.",
                    ephemeral=True,
                )
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"❌ Failed to send message: {e}", ephemeral=True
                )
            return

        await interaction.followup.send(
            "❌ Invalid target. Please choose from autocomplete suggestions.",
            ephemeral=True,
        )

    @sendmessage.autocomplete("send_to")
    async def send_to_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if not guild:
            return []

        needle = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []

        # Add channels first so admins can quickly target server locations.
        for channel in guild.channels:
            if needle and needle not in channel.name.lower():
                continue
            choices.append(
                app_commands.Choice(
                    name=f"# {channel.name} (channel)",
                    value=f"channel:{channel.id}",
                )
            )
            if len(choices) >= 25:
                return choices[:25]

        # Then add users (nickname/display name and username matching).
        for member in guild.members:
            name_blob = f"{member.display_name} {member.name}".lower()
            if needle and needle not in name_blob:
                continue
            choices.append(
                app_commands.Choice(
                    name=f"@ {member.display_name} (user)",
                    value=f"user:{member.id}",
                )
            )
            if len(choices) >= 25:
                return choices[:25]

        return choices[:25]


async def setup(bot):
    await bot.add_cog(SendMessageCommand(bot))
