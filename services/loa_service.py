import discord
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Optional
import logging

from .loa_repository import loa_repository
from .loa_config_repository import loa_config_repository

logger = logging.getLogger(__name__)

# ── Hardcoded Role IDs ─────────────────────────────────────────────────
MEMBER_ROLE_ID = 437981035641176064
ACTIVE_ROLE_ID = 898283677056925756

# ── Timezone ───────────────────────────────────────────────────────────
UK_TZ = ZoneInfo("Europe/London")


# ── Embed Builders ─────────────────────────────────────────────────────

def build_loa_announcement_embed(
    member: discord.Member,
    start_date: date,
    end_date: date,
    reason: Optional[str],
) -> discord.Embed:
    """Build the green announcement embed posted when a new LOA is created."""
    embed = discord.Embed(
        title="🏖️ Leave of Absence",
        color=0x2ECC71,
        timestamp=datetime.now(UK_TZ),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.description = f"**{member.mention}** is on leave of absence."
    embed.add_field(
        name="📅 Start Date",
        value=f"`{start_date.strftime('%d-%m-%Y')}`",
        inline=True,
    )
    embed.add_field(
        name="📅 End Date",
        value=f"`{end_date.strftime('%d-%m-%Y')}`",
        inline=True,
    )
    if reason:
        embed.add_field(name="💬 Reason", value=reason, inline=False)
    embed.set_footer(text=f"LOA submitted by {member.display_name}")
    return embed


def build_loa_summary_embed(
    active_loas: list[dict],
    guild: discord.Guild,
) -> discord.Embed:
    """Build the blue summary embed for the bot-owned overview message."""
    now_uk = datetime.now(UK_TZ)

    embed = discord.Embed(
        title="📋 Leave of Absence — Overview",
        color=0x3498DB,
    )

    # ── How-to guide ──
    guide = (
        "**📝 How to Request Leave**\n"
        "Use `/loa` to submit a leave of absence request.\n"
        "• **start_date** — When your leave begins (format: `DD-MM-YYYY`)\n"
        "• **end_date** — When your leave ends (format: `DD-MM-YYYY`)\n"
        "• **reason** — *(Optional)* Why you'll be away\n\n"
        "**❌ Cancel Leave Early**\n"
        "Use `/cancelloa` to cancel an active leave and return to duty.\n\n"
        "**ℹ️ What Happens When You Go On Leave**\n"
        "• Your **@Active** role is removed for the duration of your leave\n"
        "• An announcement is posted in this channel\n"
        "• When your leave expires, you'll receive a DM welcome-back message\n"
        "• Your **@Active** role is automatically restored\n"
    )

    # ── Active LOAs list ──
    guide += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if active_loas:
        guide += f"**🏖️ Active Leaves ({len(active_loas)})**\n\n"

        for loa in active_loas:
            user_mention = f"<@{loa['user_id']}>"
            start_str = loa["start_date"].strftime("%d-%m-%Y")
            end_str = loa["end_date"].strftime("%d-%m-%Y")

            entry = f"👤 {user_mention}\n📅 `{start_str}` → `{end_str}`"
            if loa.get("reason"):
                entry += f"\n💬 {loa['reason']}"
            guide += entry + "\n\n"

            # Safety check — Discord embed description limit is 4096 chars
            if len(guide) > 3800:
                remaining = len(active_loas) - active_loas.index(loa) - 1
                if remaining > 0:
                    guide += f"*... and {remaining} more*\n"
                break
    else:
        guide += "*No active leaves of absence. All personnel are on duty! 🫡*\n"

    embed.description = guide
    embed.set_footer(text=f"Last updated: {now_uk.strftime('%d-%m-%Y %H:%M')} UK")
    return embed


def build_expiry_dm_embed(
    member: discord.Member,
    loa: dict,
    event_link: Optional[str],
    events_channel_mention: Optional[str],
    loa_channel_mention: Optional[str],
    role_restored: bool,
) -> discord.Embed:
    """Build the DM embed sent when an LOA expires."""
    embed = discord.Embed(
        title="🎉 Welcome Back!",
        color=0x2ECC71,
        timestamp=datetime.now(UK_TZ),
    )

    start_str = loa["start_date"].strftime("%d-%m-%Y")
    end_str = loa["end_date"].strftime("%d-%m-%Y")

    description = f"Hey **{member.display_name}**! 👋\n\n"
    description += f"Your leave of absence (`{start_str}` → `{end_str}`) has ended.\n"

    if role_restored:
        description += "Your **@Active** role has been restored — welcome back to duty! 💪\n"
    else:
        description += "Welcome back to duty! 💪\n"

    if event_link:
        description += f"\n🗳️ **Check out the next event:** [Click here]({event_link})\n"
    elif events_channel_mention:
        description += f"\n🗳️ **Check out upcoming events:** {events_channel_mention}\n"

    if loa_channel_mention:
        description += (
            f"\n🏖️ **Need to extend your leave?** "
            f"Head to {loa_channel_mention} and use `/loa` again.\n"
        )

    embed.description = description
    embed.set_footer(text="GOL Leave of Absence System")
    return embed


# ── Raid-Helper Event Finder ───────────────────────────────────────────

async def find_next_raidhelper_event(
    guild: discord.Guild,
) -> tuple[Optional[str], Optional[discord.TextChannel]]:
    """Find the next Raid-Helper event post in the #events channel.

    Returns ``(message_jump_url | None, events_channel | None)``.
    Falls back to just returning the channel if no event post is found.
    """
    events_channel: Optional[discord.TextChannel] = None
    for ch in guild.text_channels:
        if "events" in ch.name.lower():
            events_channel = ch
            break

    if not events_channel:
        return None, None

    try:
        async for msg in events_channel.history(limit=30, oldest_first=False):
            # Raid-Helper posts are from bots and contain embeds
            if msg.author.bot and msg.embeds:
                return msg.jump_url, events_channel
    except Exception as e:
        logger.warning(f"Failed to search events channel for Raid-Helper posts: {e}")

    return None, events_channel


# ── Role Management ────────────────────────────────────────────────────

async def remove_active_role(guild: discord.Guild, user_id: int) -> bool:
    """Remove the @Active role from a member.  Returns True if removed."""
    try:
        member = await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return False

    active_role = guild.get_role(ACTIVE_ROLE_ID)
    if not active_role:
        return False

    if active_role in member.roles:
        try:
            await member.remove_roles(active_role, reason="Leave of Absence started")
            return True
        except discord.HTTPException as e:
            logger.warning(f"Failed to remove @Active role from {user_id}: {e}")

    return False


async def restore_active_role(guild: discord.Guild, user_id: int) -> bool:
    """Restore the @Active role to a member.  Returns True if added."""
    try:
        member = await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return False

    active_role = guild.get_role(ACTIVE_ROLE_ID)
    member_role = guild.get_role(MEMBER_ROLE_ID)
    if not active_role:
        return False

    # Only restore if user still has the @Member role
    if member_role and member_role not in member.roles:
        return False

    if active_role not in member.roles:
        try:
            await member.add_roles(active_role, reason="Leave of Absence expired")
            return True
        except discord.HTTPException as e:
            logger.warning(f"Failed to restore @Active role to {user_id}: {e}")

    return False


# ── Summary Message Update ─────────────────────────────────────────────

async def update_summary_message(bot: discord.Client, guild_id: int) -> None:
    """Re-build and edit the bot-owned LOA summary message."""
    config = await loa_config_repository.get_config(guild_id)
    if not config:
        return

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    channel = guild.get_channel(config["channel_id"])
    if not channel:
        return

    active_loas = await loa_repository.get_active_loas_by_guild(guild_id)
    embed = build_loa_summary_embed(active_loas, guild)

    try:
        msg = await channel.fetch_message(config["message_id"])
        await msg.edit(embed=embed)
    except discord.NotFound:
        # Message was deleted — recreate it
        msg = await channel.send(embed=embed)
        await loa_config_repository.set_config(guild_id, config["channel_id"], msg.id)
    except Exception as e:
        logger.error(f"Failed to update LOA summary message: {e}")


# ── DM Sender ──────────────────────────────────────────────────────────

async def send_expiry_dm(guild: discord.Guild, loa: dict, role_restored: bool) -> bool:
    """Send an expiry notification DM.  Returns True on success."""
    try:
        member = await guild.fetch_member(loa["user_id"])
    except (discord.NotFound, discord.HTTPException):
        return False

    # Find events link
    event_link, events_channel = await find_next_raidhelper_event(guild)
    events_channel_mention = events_channel.mention if events_channel else None

    # Find LOA channel
    config = await loa_config_repository.get_config(guild.id)
    loa_channel_mention = None
    if config:
        loa_channel = guild.get_channel(config["channel_id"])
        if loa_channel:
            loa_channel_mention = loa_channel.mention

    embed = build_expiry_dm_embed(
        member, loa, event_link, events_channel_mention, loa_channel_mention, role_restored
    )

    try:
        await member.send(embed=embed)
        return True
    except discord.HTTPException as e:
        logger.warning(f"Failed to DM user {loa['user_id']} about LOA expiry: {e}")
        return False


# ── Announcement Deletion ──────────────────────────────────────────────

async def delete_loa_announcement(guild: discord.Guild, loa: dict) -> bool:
    """Delete the announcement embed for an LOA.  Returns True on success."""
    if not loa.get("message_id") or not loa.get("channel_id"):
        return False

    try:
        channel = guild.get_channel(loa["channel_id"])
        if channel:
            msg = await channel.fetch_message(loa["message_id"])
            await msg.delete()
            return True
    except (discord.NotFound, discord.HTTPException):
        pass

    return False
