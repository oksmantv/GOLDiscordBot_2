import discord
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from urllib.parse import quote
import logging

from .roster_repository import roster_repository
from .roster_config_repository import roster_config_repository
from .loa_repository import loa_repository

logger = logging.getLogger(__name__)

# ── Timezone ───────────────────────────────────────────────────────────
UK_TZ = ZoneInfo("Europe/London")

# ── Role IDs ───────────────────────────────────────────────────────────
MEMBER_ROLE_ID    = 437981035641176064
ACTIVE_ROLE_ID    = 898283677056925756
RESERVE_ROLE_ID   = 600744732104327169
HELLFISH_ROLE_ID  = 437981613926776832
AAC_ROLE_ID       = 437981886510530569

# ── Rank definitions (prefix, full name, role ID, sort order, emoji) ──
# Lower sort order = higher rank.  Order follows a standard military
# hierarchy so the embed reads top (highest rank) to bottom (lowest).
RANKS = [
    ("1Lt.", "1st Lieutenant",      772212456298512414,   1, "<:1Lt:1477456471892561972>"),
    ("2Lt.", "2nd Lieutenant",      1214686469642391632,  2, "<:2Lt:1477456472802725999>"),
    ("Sgt.", "Sergeant",            437982506713874433,   3, "<:SGT:1477456482260750396>"),
    ("Cpl.", "Corporal",            437983493864030219,   4, "<:CPL:1477456474174259350>"),
    ("LCpl.", "Lance Corporal",     437983720583069698,   5, "<:LCPL:1477456475193475305>"),
    ("Spc.", "Specialist",          1271423656249004116,  6, "<:SPC:1477456483343143097>"),
    ("1CA.", "First Class Airman",  437984886150791188,   7, None),
    ("Pfc.", "Private 1st Class",   437983988477460500,   8, "<:PFC:1477456478033154221>"),
    ("Psc.", "Private 2nd Class",   1271423463395033140,  9, "<:PSC:1477456479320670248>"),
    ("Am.",  "Airman",              437985055613124618,  10, None),
    ("Pvt.", "Private",             437984103220903949,  11, "<:PVT:1477456476757823571>"),
    ("Rct.", "Recruit",             437985345129152520,  12, "<:RCT:1477456480767840276>"),
]

# Quick lookup sets
RANK_ROLE_IDS = {r[2] for r in RANKS}
RANK_BY_ROLE_ID = {r[2]: (r[0], r[1], r[3], r[4]) for r in RANKS}  # id -> (prefix, name, order, emoji)
RANK_PREFIXES = [r[0] for r in RANKS]  # used for stripping from nicknames
# Emoji lookup by rank prefix
RANK_EMOJI_BY_PREFIX = {r[0]: r[4] for r in RANKS if r[4]}  # prefix -> emoji string


# ── Helpers ────────────────────────────────────────────────────────────

def _extract_name_and_rank(member: discord.Member) -> tuple[str, Optional[str], Optional[str], int]:
    """Determine the player's display name (without rank) and their rank info.

    Returns ``(clean_name, rank_prefix, rank_full_name, rank_order)``.
    If no rank role is found, ``rank_prefix`` and ``rank_full_name`` are None
    and ``rank_order`` is 999.
    """
    # 1. Find the highest rank role the member has
    rank_prefix: Optional[str] = None
    rank_name: Optional[str] = None
    rank_order: int = 999

    for role in member.roles:
        if role.id in RANK_BY_ROLE_ID:
            prefix, name, order, _emoji = RANK_BY_ROLE_ID[role.id]
            if order < rank_order:
                rank_prefix = prefix
                rank_name = name
                rank_order = order

    # 2. Strip rank prefix from display name to get the "clean" name
    display = member.display_name.strip()

    if rank_prefix:
        # Check if the display name starts with the rank prefix
        for pfx in RANK_PREFIXES:
            if display.lower().startswith(pfx.lower()):
                display = display[len(pfx):].strip().lstrip(".-_ ")
                break

    # Fallback: if stripping left an empty string, use the original
    if not display:
        display = member.display_name.strip()

    return display, rank_prefix, rank_name, rank_order


def _profile_url(clean_name: str) -> str:
    """Build a GOL website profile URL for the given name."""
    return f"https://gol-clan.com/profile?name={quote(clean_name)}"


def _format_member_line(
    rank_prefix: Optional[str],
    clean_name: str,
    on_loa: bool,
    with_link: bool = False,
) -> str:
    """Format a single roster line.

    When *with_link* is True the name is a markdown link to the
    player's GOL profile.  The rank prefix text is omitted when a
    rank emoji is available (the emoji alone conveys the rank).
    """
    if with_link:
        display_name = f"[{clean_name}]({_profile_url(clean_name)})"
    else:
        display_name = clean_name

    if rank_prefix:
        emoji = RANK_EMOJI_BY_PREFIX.get(rank_prefix, "")
        if emoji:
            name_part = f"{emoji} {display_name}"
        else:
            name_part = f"{rank_prefix} {display_name}"
    else:
        name_part = display_name

    if on_loa:
        return f"~~{name_part}~~ (LOA)"
    return name_part


# ── Scanner ────────────────────────────────────────────────────────────

async def scan_roster(guild: discord.Guild) -> dict:
    """Scan all guild members and upsert the roster table.

    Returns a summary dict with counts.
    """
    member_role  = guild.get_role(MEMBER_ROLE_ID)
    active_role  = guild.get_role(ACTIVE_ROLE_ID)
    reserve_role = guild.get_role(RESERVE_ROLE_ID)

    if not member_role:
        logger.warning("@Member role not found in guild")
        return {"total": 0, "active": 0, "reserve": 0, "updated": 0, "removed": 0}

    # Fetch active LOA user IDs for this guild
    active_loas = await loa_repository.get_active_loas_by_guild(guild.id)
    loa_user_ids = {loa["user_id"] for loa in active_loas}

    present_user_ids: list[int] = []
    updated = 0

    for member in guild.members:
        if member.bot:
            continue
        if member_role not in member.roles:
            continue

        present_user_ids.append(member.id)

        clean_name, rank_prefix, rank_name, rank_order = _extract_name_and_rank(member)

        is_active  = active_role is not None and active_role in member.roles
        is_reserve = reserve_role is not None and reserve_role in member.roles

        # Determine subgroup — check regardless of active role because
        # LOA members lose @Active but keep their subgroup role (FH/AAC)
        subgroup: Optional[str] = None
        hellfish_role = guild.get_role(HELLFISH_ROLE_ID)
        aac_role      = guild.get_role(AAC_ROLE_ID)
        if hellfish_role and hellfish_role in member.roles:
            subgroup = "Flying Hellfish"
        elif aac_role and aac_role in member.roles:
            subgroup = "AAC"

        on_loa = member.id in loa_user_ids

        # LOA members with a subgroup should still appear in the active
        # roster (shown with strikethrough) even though they lose @Active
        effective_active = is_active or (on_loa and subgroup is not None)

        await roster_repository.upsert_member(
            guild_id=guild.id,
            user_id=member.id,
            nickname=clean_name,
            rank_prefix=rank_prefix,
            rank_name=rank_name,
            rank_order=rank_order,
            is_active=effective_active,
            is_reserve=is_reserve,
            subgroup=subgroup,
            on_loa=on_loa,
        )
        updated += 1

    # Remove members who left the server or lost the @Member role
    removed = await roster_repository.remove_absent_members(guild.id, present_user_ids)

    active_count  = sum(1 for uid in present_user_ids
                        if active_role and active_role in guild.get_member(uid).roles)
    reserve_count = sum(1 for uid in present_user_ids
                        if reserve_role and reserve_role in guild.get_member(uid).roles)

    summary = {
        "total": len(present_user_ids),
        "active": active_count,
        "reserve": reserve_count,
        "updated": updated,
        "removed": removed,
    }
    logger.info(f"Roster scan complete for {guild.name}: {summary}")
    return summary


# ── Embed Builder ──────────────────────────────────────────────────────

async def build_roster_embeds(guild_id: int) -> list[discord.Embed]:
    """Build the Platoon Roster embeds from the database.

    Returns a list of embeds: the main roster (Active) and a separate
    Reserve embed.  Splitting reserves into their own embed avoids
    field-length truncation on the main roster.
    """
    now_uk = datetime.now(UK_TZ)

    active_members  = await roster_repository.get_active_members(guild_id)
    reserve_members = await roster_repository.get_reserve_members(guild_id)

    total_count   = await roster_repository.get_member_count(guild_id)
    active_count  = await roster_repository.get_active_count(guild_id)
    reserve_count = await roster_repository.get_reserve_count(guild_id)
    loa_count     = await roster_repository.get_loa_count(guild_id)

    # active_count includes LOA members; split for clarity
    active_available = active_count - loa_count

    # ── Partition active members by subgroup ──
    hellfish: list[dict] = []
    aac: list[dict] = []
    for m in active_members:
        if m["subgroup"] == "Flying Hellfish":
            hellfish.append(m)
        elif m["subgroup"] == "AAC":
            aac.append(m)

    # ── Split Hellfish into Leadership, Senior Enlisted, Enlisted ──
    LEADERSHIP_PREFIXES = {"1Lt.", "2Lt.", "Sgt.", "Cpl."}
    SENIOR_ENLISTED_PREFIXES = {"LCpl.", "Spc.", "Pfc."}
    fh_leadership: list[dict] = []
    fh_senior: list[dict] = []
    fh_enlisted: list[dict] = []
    for m in hellfish:
        if m["rank_prefix"] in LEADERSHIP_PREFIXES:
            fh_leadership.append(m)
        elif m["rank_prefix"] in SENIOR_ENLISTED_PREFIXES:
            fh_senior.append(m)
        else:
            fh_enlisted.append(m)

    # ━━━━━━━━━━━━━━━  EMBED 1: Header + FH Leadership  ━━━━━━━━━━━━━━━
    embed1 = discord.Embed(
        title="<:GOL_Logo:1477457025972568299>  GOL Platoon Roster",
        url="https://gol-clan.com/orbat",
        color=0x2D572C,
    )

    unix_ts = int(now_uk.timestamp())
    embed1.description = (
        f"👥 **Total Members:** {total_count}\n"
        f"✅ **Active Duty:** {active_available}\n"
        f"🟡 **On LOA:** {loa_count}\n"
        f"🔸 **Reserves:** {reserve_count}\n"
        "\n"
        f"🕒 Last updated: <t:{unix_ts}:f> (<t:{unix_ts}:R>)\n"
    )

    # ── FH header ──
    embed1.add_field(
        name="<:flyinghellfish:1477458331047301242>  1-1 Flying Hellfish",
        value=(
            "*Our ground force element — infantry, motorised & mechanized infantry, "
            "vehicle crews and artillery operators.*"
        ),
        inline=False,
    )

    # ── Leadership ──
    if fh_leadership:
        lines = [_format_member_line(m["rank_prefix"], m["nickname"], m["on_loa"], with_link=True) for m in fh_leadership]
        value = "*Officers and NCOs responsible for command, tactics and squad coordination.*\n\n" + "\n".join(lines)
        if len(value) > 1024:
            value = value[:1000] + "\n*… list truncated*"
    else:
        value = "*No leadership members*"
    embed1.add_field(
        name="⭐  Leadership",
        value=value,
        inline=False,
    )

    # ━━━━━━━━━━━━━━━  EMBED 2: Senior Enlisted  ━━━━━━━━━━━━━━━━━━━
    embed2 = discord.Embed(color=0x2D572C)

    if fh_senior:
        lines = [_format_member_line(m["rank_prefix"], m["nickname"], m["on_loa"], with_link=True) for m in fh_senior]
        value = "*Experienced enlisted personnel that assist in forming cohesion and order within the teams.*\n\n" + "\n".join(lines)
        if len(value) > 1024:
            value = value[:1000] + "\n*… list truncated*"
    else:
        value = "*No senior enlisted members*"
    embed2.add_field(
        name="🎖️  Senior Enlisted",
        value=value,
        inline=False,
    )

    # ━━━━━━━━━━━━━━━  EMBED 3: Enlisted  ━━━━━━━━━━━━━━━━━━━━━━━━
    embed3 = discord.Embed(color=0x2D572C)

    if fh_enlisted:
        lines = [_format_member_line(m["rank_prefix"], m["nickname"], m["on_loa"], with_link=True) for m in fh_enlisted]
        value = "*The enlisted members of the platoon, the backbone of any active combat element.*\n\n" + "\n".join(lines)
        if len(value) > 1024:
            value = value[:1000] + "\n*… list truncated*"
    else:
        value = "*No enlisted members*"
    embed3.add_field(
        name="🪖  Enlisted",
        value=value,
        inline=False,
    )

    # ━━━━━━━━━━━━━━━  EMBED 4: AAC + Reserves  ━━━━━━━━━━━━━━━━━━━
    embed4 = discord.Embed(color=0x2D572C)

    # ── AAC section ──
    if aac:
        lines = [_format_member_line(m["rank_prefix"], m["nickname"], m["on_loa"], with_link=True) for m in aac]
        value = (
            "*Support assets — rotary wing, fixed wing & drone operators, "
            "and Forward Air Controllers (FACs).*\n\n"
            + "\n".join(lines)
        )
        if len(value) > 1024:
            value = value[:1000] + "\n*… list truncated*"
    else:
        value = (
            "*Support assets — rotary wing, fixed wing & drone operators, "
            "and Forward Air Controllers (FACs).*\n\n"
            "*No active members*"
        )
    embed4.add_field(
        name="<:AAC:1477458645481554042>  Army Aircorps (AAC)",
        value=value,
        inline=False,
    )

    # ── Spacer ──
    embed4.add_field(name="", value="", inline=False)

    # ── Reserves section (no links) ──
    RESERVE_DISPLAY_LIMIT = 20
    if reserve_members:
        shown = reserve_members[:RESERVE_DISPLAY_LIMIT]
        lines = []
        for m in shown:
            name = m["nickname"]
            if m["on_loa"]:
                lines.append(f"~~{name}~~ (LOA)")
            else:
                lines.append(name)
        body = "*Personnel on reserve status — not currently active duty.*\n\n"
        body += "\n".join(lines)
        remaining = len(reserve_members) - RESERVE_DISPLAY_LIMIT
        if remaining > 0:
            body += f"\n\n*… and {remaining} more reserves*"
    else:
        body = "*No reserve members*"
    embed4.add_field(
        name=f"🔸  Reserves ({reserve_count})",
        value=body,
        inline=False,
    )

    embed4.set_footer(text=f"GOL Platoon Roster  •  Updated {now_uk.strftime('%d-%m-%Y %H:%M')} UK")

    return [embed1, embed2, embed3, embed4]


# ── Summary Message Update ─────────────────────────────────────────────

async def update_roster_message(bot: discord.Client, guild_id: int) -> None:
    """Re-build and edit the bot-owned Roster embed message."""
    config = await roster_config_repository.get_config(guild_id)
    if not config:
        return

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    channel = guild.get_channel(config["channel_id"])
    if not channel:
        return

    embeds = await build_roster_embeds(guild_id)

    try:
        msg = await channel.fetch_message(config["message_id"])
        await msg.edit(embeds=embeds)
    except discord.NotFound:
        # Message was deleted — recreate it
        msg = await channel.send(embeds=embeds)
        await roster_config_repository.set_config(guild_id, config["channel_id"], msg.id)
    except Exception as e:
        logger.error(f"Failed to update Roster embed message: {e}")
