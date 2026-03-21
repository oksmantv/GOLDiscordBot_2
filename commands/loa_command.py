import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional
from datetime import datetime, date
from zoneinfo import ZoneInfo
import logging

from config import Config
from services.loa_repository import loa_repository
from services.loa_config_repository import loa_config_repository
from services.loa_service import (
    MEMBER_ROLE_ID,
    ACTIVE_ROLE_ID,
    UK_TZ,
    build_loa_announcement_embed,
    build_loa_summary_embed,
    update_summary_message,
    remove_active_role,
    restore_active_role,
    send_expiry_dm,
    delete_loa_announcement,
)

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────

def _parse_date(value: str) -> Optional[date]:
    """Parse a date string in DD-MM-YYYY format."""
    try:
        return datetime.strptime(value.strip(), "%d-%m-%Y").date()
    except ValueError:
        return None


# ── Cog ────────────────────────────────────────────────────────────────

class LOACommands(commands.Cog):
    """Cog for Leave of Absence slash commands and background polling loop."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self._loa_check_loop.start()
        logger.info("LOA check background task started")

    async def cog_unload(self):
        self._loa_check_loop.cancel()

    # ─── /loa ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="loa",
        description="Request a Leave of Absence",
    )
    @app_commands.describe(
        start_date="Start date of your leave (format: DD-MM-YYYY, e.g. 01-03-2026)",
        end_date="End date of your leave (format: DD-MM-YYYY, e.g. 15-03-2026)",
        reason="Optional reason for your leave",
    )
    @app_commands.guilds(discord.Object(id=Config.GUILD_ID))
    async def loa_command(
        self,
        interaction: discord.Interaction,
        start_date: str,
        end_date: str,
        reason: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # ── Permission check: @Member role required ──
        member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
        if not member_role or member_role not in interaction.user.roles:
            await interaction.followup.send(
                "❌ You need the **@Member** role to use this command.",
                ephemeral=True,
            )
            return

        # ── Parse dates ──
        parsed_start = _parse_date(start_date)
        parsed_end = _parse_date(end_date)

        if not parsed_start:
            await interaction.followup.send(
                f"❌ Invalid start date: `{start_date}`.\n"
                "Please use the format **DD-MM-YYYY** (e.g. `01-03-2026`).",
                ephemeral=True,
            )
            return

        if not parsed_end:
            await interaction.followup.send(
                f"❌ Invalid end date: `{end_date}`.\n"
                "Please use the format **DD-MM-YYYY** (e.g. `15-03-2026`).",
                ephemeral=True,
            )
            return

        # ── Date validation ──
        today = datetime.now(UK_TZ).date()

        if parsed_start < today:
            await interaction.followup.send(
                "❌ Start date cannot be in the past.", ephemeral=True
            )
            return

        if parsed_end <= parsed_start:
            await interaction.followup.send(
                "❌ End date must be after the start date.", ephemeral=True
            )
            return

        # ── Overlap check ──
        overlap = await loa_repository.check_overlap(
            interaction.guild_id, interaction.user.id, parsed_start, parsed_end
        )
        if overlap:
            o_start = overlap["start_date"].strftime("%d-%m-%Y")
            o_end = overlap["end_date"].strftime("%d-%m-%Y")
            await interaction.followup.send(
                f"❌ This LOA overlaps with your existing leave: "
                f"**{o_start} → {o_end}**.\n"
                "Please cancel the existing LOA first or choose different dates.",
                ephemeral=True,
            )
            return

        # ── Config check ──
        config = await loa_config_repository.get_config(interaction.guild_id)
        if not config:
            await interaction.followup.send(
                "❌ The LOA system has not been configured yet. "
                "An admin needs to run `/configureloa` first.",
                ephemeral=True,
            )
            return

        # ── Create DB record ──
        loa = await loa_repository.create_loa(
            interaction.guild_id,
            interaction.user.id,
            parsed_start,
            parsed_end,
            reason,
        )

        # ── Post announcement embed ──
        loa_channel = interaction.guild.get_channel(config["channel_id"])
        if loa_channel:
            embed = build_loa_announcement_embed(
                interaction.user, parsed_start, parsed_end, reason
            )
            announcement_msg = await loa_channel.send(
                content=interaction.user.mention,
                embed=embed,
            )
            await loa_repository.update_message_info(
                loa["id"], announcement_msg.id, loa_channel.id
            )

        # ── Remove @Active role if LOA starts today ──
        if parsed_start <= today:
            await remove_active_role(interaction.guild, interaction.user.id)

        # ── Update summary message ──
        await update_summary_message(self.bot, interaction.guild_id)

        # ── Ephemeral confirmation ──
        confirm = (
            f"✅ Your Leave of Absence has been registered!\n"
            f"📅 **{parsed_start.strftime('%d-%m-%Y')}** → "
            f"**{parsed_end.strftime('%d-%m-%Y')}**"
        )
        if reason:
            confirm += f"\n💬 {reason}"
        await interaction.followup.send(confirm, ephemeral=True)

    # ─── /cancelloa ────────────────────────────────────────────────────

    @app_commands.command(
        name="cancelloa",
        description="Cancel one of your active Leaves of Absence",
    )
    @app_commands.describe(
        loa="Select the leave of absence to cancel",
    )
    @app_commands.guilds(discord.Object(id=Config.GUILD_ID))
    async def cancel_loa_command(
        self,
        interaction: discord.Interaction,
        loa: int,
    ):
        await interaction.response.defer(ephemeral=True)

        # ── Fetch & validate ──
        loa_record = await loa_repository.get_loa_by_id(loa)

        if not loa_record:
            await interaction.followup.send(
                "❌ Leave of absence not found.", ephemeral=True
            )
            return

        if loa_record["user_id"] != interaction.user.id:
            await interaction.followup.send(
                "❌ That LOA does not belong to you.",
                ephemeral=True,
            )
            return

        if loa_record["expired"]:
            await interaction.followup.send(
                "❌ This leave of absence has already expired.", ephemeral=True
            )
            return

        today = datetime.now(UK_TZ).date()

        # ── Mark expired (no DM needed for cancellation) ──
        await loa_repository.mark_expired(loa_record["id"])
        await loa_repository.mark_notified(loa_record["id"])

        # ── Restore @Active only if the LOA had actually started
        #    AND the user has no other currently-active LOA ──
        if loa_record["start_date"] <= today:
            remaining = await loa_repository.get_active_loas_by_user(
                interaction.guild_id, interaction.user.id
            )
            still_on_leave = any(l["start_date"] <= today for l in remaining)
            if not still_on_leave:
                await restore_active_role(interaction.guild, interaction.user.id)

        # ── Delete announcement embed ──
        await delete_loa_announcement(interaction.guild, loa_record)

        # ── Update summary ──
        await update_summary_message(self.bot, interaction.guild_id)

        start_str = loa_record["start_date"].strftime("%d-%m-%Y")
        end_str = loa_record["end_date"].strftime("%d-%m-%Y")
        await interaction.followup.send(
            f"✅ Your leave of absence (`{start_str}` → `{end_str}`) "
            "has been cancelled.\nWelcome back to duty! 💪",
            ephemeral=True,
        )

    @cancel_loa_command.autocomplete("loa")
    async def _cancel_loa_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[int]]:
        active_loas = await loa_repository.get_active_loas_by_user(
            interaction.guild_id, interaction.user.id
        )

        choices: list[app_commands.Choice[int]] = []
        for entry in active_loas:
            start_str = entry["start_date"].strftime("%d-%m-%Y")
            end_str = entry["end_date"].strftime("%d-%m-%Y")
            label = f"{start_str} → {end_str}"
            if entry.get("reason"):
                label += f": {entry['reason']}"
            label = label[:100]  # Discord max 100 chars

            if not current or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label, value=entry["id"]))

        return choices[:25]  # Discord max 25 choices

    # ─── /admincancelloa ───────────────────────────────────────────────

    @app_commands.command(
        name="admincancelloa",
        description="Cancel another member's Leave of Absence (Admin/Mod only)",
    )
    @app_commands.describe(
        user="The member whose LOA you want to cancel",
        loa="Select the leave of absence to cancel",
    )
    @app_commands.guilds(discord.Object(id=Config.GUILD_ID))
    async def admin_cancel_loa_command(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        loa: int,
    ):
        await interaction.response.defer(ephemeral=True)

        # ── Permission check: administrator or moderate_members ──
        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.moderate_members):
            await interaction.followup.send(
                "❌ You need **Administrator** or **Moderate Members** "
                "permission to use this command.",
                ephemeral=True,
            )
            return

        # ── Fetch & validate ──
        loa_record = await loa_repository.get_loa_by_id(loa)

        if not loa_record:
            await interaction.followup.send(
                "❌ Leave of absence not found.", ephemeral=True
            )
            return

        if loa_record["user_id"] != user.id:
            await interaction.followup.send(
                "❌ The selected LOA does not belong to that user.",
                ephemeral=True,
            )
            return

        if loa_record["expired"]:
            await interaction.followup.send(
                "❌ This leave of absence has already expired.", ephemeral=True
            )
            return

        today = datetime.now(UK_TZ).date()

        # ── Mark expired (no DM needed for cancellation) ──
        await loa_repository.mark_expired(loa_record["id"])
        await loa_repository.mark_notified(loa_record["id"])

        # ── Restore @Active only if the LOA had actually started
        #    AND the user has no other currently-active LOA ──
        if loa_record["start_date"] <= today:
            remaining = await loa_repository.get_active_loas_by_user(
                interaction.guild_id, user.id
            )
            still_on_leave = any(l["start_date"] <= today for l in remaining)
            if not still_on_leave:
                await restore_active_role(interaction.guild, user.id)

        # ── Delete announcement embed ──
        await delete_loa_announcement(interaction.guild, loa_record)

        # ── Update summary ──
        await update_summary_message(self.bot, interaction.guild_id)

        start_str = loa_record["start_date"].strftime("%d-%m-%Y")
        end_str = loa_record["end_date"].strftime("%d-%m-%Y")
        await interaction.followup.send(
            f"✅ Leave of absence for {user.mention} "
            f"(`{start_str}` → `{end_str}`) has been cancelled.",
            ephemeral=True,
        )

    @admin_cancel_loa_command.autocomplete("loa")
    async def _admin_cancel_loa_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[int]]:
        # Get the user from the namespace (filled in before loa field)
        namespace = interaction.namespace
        selected_user = getattr(namespace, "user", None)

        if selected_user is None:
            return []

        # selected_user may be a Member object or a raw ID (snowflake)
        if isinstance(selected_user, discord.Member):
            target_user_id = selected_user.id
        elif isinstance(selected_user, int):
            target_user_id = selected_user
        else:
            return []

        active_loas = await loa_repository.get_active_loas_by_user(
            interaction.guild_id, target_user_id
        )

        choices: list[app_commands.Choice[int]] = []
        for entry in active_loas:
            start_str = entry["start_date"].strftime("%d-%m-%Y")
            end_str = entry["end_date"].strftime("%d-%m-%Y")
            label = f"{start_str} → {end_str}"
            if entry.get("reason"):
                label += f": {entry['reason']}"
            label = label[:100]  # Discord max 100 chars

            if not current or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label, value=entry["id"]))

        return choices[:25]  # Discord max 25 choices

    # ─── /configureloa ─────────────────────────────────────────────────

    @app_commands.command(
        name="configureloa",
        description="Configure the LOA channel (Admin only)",
    )
    @app_commands.describe(channel="The channel to use for Leave of Absence posts")
    @app_commands.guilds(discord.Object(id=Config.GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def configure_loa_command(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        # ── Clean up old config if it exists ──
        old_config = await loa_config_repository.get_config(guild_id)
        if old_config:
            old_channel = interaction.guild.get_channel(old_config["channel_id"])
            if old_channel:
                # Delete old summary message
                try:
                    old_msg = await old_channel.fetch_message(old_config["message_id"])
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

                # Delete all active LOA announcement embeds from old channel
                active_loas = await loa_repository.get_active_loas_by_guild(guild_id)
                for loa_entry in active_loas:
                    await delete_loa_announcement(interaction.guild, loa_entry)

        # ── Post new summary message ──
        active_loas = await loa_repository.get_active_loas_by_guild(guild_id)
        summary_embed = build_loa_summary_embed(active_loas, interaction.guild)
        summary_msg = await channel.send(embed=summary_embed)

        # ── Save config ──
        await loa_config_repository.set_config(guild_id, channel.id, summary_msg.id)

        # ── Re-post announcement embeds for all active LOAs ──
        for loa_entry in active_loas:
            try:
                member = await interaction.guild.fetch_member(loa_entry["user_id"])
                embed = build_loa_announcement_embed(
                    member,
                    loa_entry["start_date"],
                    loa_entry["end_date"],
                    loa_entry.get("reason"),
                )
                ann_msg = await channel.send(
                    content=f"<@{loa_entry['user_id']}>", embed=embed
                )
                await loa_repository.update_message_info(
                    loa_entry["id"], ann_msg.id, channel.id
                )
            except (discord.NotFound, discord.HTTPException) as e:
                logger.warning(
                    f"Failed to re-post LOA announcement for user "
                    f"{loa_entry['user_id']}: {e}"
                )

        await interaction.followup.send(
            f"✅ LOA system configured! Summary message posted in {channel.mention}.",
            ephemeral=True,
        )

    # ─── Background Loop ──────────────────────────────────────────────

    @tasks.loop(hours=1)
    async def _loa_check_loop(self):
        """Hourly check: expire LOAs, manage roles, send DMs during UK daytime."""
        try:
            now_uk = datetime.now(UK_TZ)
            today = now_uk.date()
            is_notification_hours = 8 <= now_uk.hour <= 16

            for guild in self.bot.guilds:
                guild_id = guild.id
                summary_needs_update = False

                active_loas = await loa_repository.get_active_loas_by_guild(guild_id)
                logger.info(f"[LOA LOOP] Guild {guild.name}: {len(active_loas)} active LOAs, today={today}")

                for loa_entry in active_loas:
                    try:
                        # Ensure date comparison works even if DB returns datetime
                        end_date = loa_entry["end_date"]
                        start_date = loa_entry["start_date"]
                        if hasattr(end_date, 'date'):
                            end_date = end_date.date()
                        if hasattr(start_date, 'date'):
                            start_date = start_date.date()

                        # 1. Remove @Active for LOAs that have started
                        if start_date <= today:
                            await remove_active_role(guild, loa_entry["user_id"])

                        # 2. Expire LOAs whose end date has passed
                        if end_date < today:
                            logger.info(
                                f"[LOA LOOP] Expiring LOA #{loa_entry['id']} "
                                f"user={loa_entry['user_id']} end={end_date}"
                            )
                            await loa_repository.mark_expired(loa_entry["id"])
                            summary_needs_update = True

                            # Delete announcement embed
                            try:
                                await delete_loa_announcement(guild, loa_entry)
                            except Exception as e:
                                logger.warning(f"[LOA LOOP] Failed to delete announcement for LOA #{loa_entry['id']}: {e}")

                            # Check for other active LOAs before restoring role
                            remaining = await loa_repository.get_active_loas_by_user(
                                guild_id, loa_entry["user_id"]
                            )
                            still_on_leave = any(
                                (l["start_date"].date() if hasattr(l["start_date"], 'date') else l["start_date"]) <= today
                                for l in remaining
                            )

                            role_restored = False
                            if not still_on_leave:
                                role_restored = await restore_active_role(
                                    guild, loa_entry["user_id"]
                                )

                            # DM notification — only during UK 08:00-16:00
                            if is_notification_hours:
                                try:
                                    await send_expiry_dm(
                                        guild, loa_entry, role_restored=role_restored
                                    )
                                except Exception as e:
                                    logger.warning(f"[LOA LOOP] Failed to send expiry DM for LOA #{loa_entry['id']}: {e}")
                                await loa_repository.mark_notified(loa_entry["id"])
                            else:
                                # If user left the server, mark notified anyway
                                try:
                                    await guild.fetch_member(loa_entry["user_id"])
                                except (discord.NotFound, discord.HTTPException):
                                    await loa_repository.mark_notified(loa_entry["id"])
                    except Exception as e:
                        logger.error(f"[LOA LOOP] Error processing LOA #{loa_entry.get('id', '?')}: {e}", exc_info=True)

                # 3. Send pending DM notifications for previously expired LOAs
                if is_notification_hours:
                    unnotified = await loa_repository.get_expired_unnotified(guild_id)
                    for loa_entry in unnotified:
                        try:
                            member = await guild.fetch_member(loa_entry["user_id"])
                            active_role = guild.get_role(ACTIVE_ROLE_ID)
                            has_active = (
                                active_role in member.roles if active_role else False
                            )
                        except (discord.NotFound, discord.HTTPException):
                            has_active = False

                        try:
                            await send_expiry_dm(
                                guild, loa_entry, role_restored=has_active
                            )
                        except Exception as e:
                            logger.warning(f"[LOA LOOP] Failed to send expiry DM for unnotified LOA #{loa_entry['id']}: {e}")
                        await loa_repository.mark_notified(loa_entry["id"])

                # 4. Update summary if anything changed
                if summary_needs_update:
                    await update_summary_message(self.bot, guild_id)

        except Exception as e:
            logger.error(f"LOA check loop error: {e}", exc_info=True)

    @_loa_check_loop.before_loop
    async def _before_loa_check_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(LOACommands(bot))
