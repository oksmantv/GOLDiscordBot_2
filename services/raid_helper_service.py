import aiohttp
import discord
import logging
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)

RAID_HELPER_API_V2 = "https://raid-helper.dev/api/v2"
RAID_HELPER_API_V3 = "https://raid-helper.dev/api/v3"

UK_TZ = ZoneInfo("Europe/London")


class RaidHelperService:
    """HTTP client for the Raid-Helper API.

    - GET /api/v3/servers/{serverId}/events  (requires server API token)
      Lists all events on the server with basic data including startTime.
    - GET /api/v2/events/{eventId}           (public, no auth)
      Fetches full event data including all sign-ups.

    The event ID in Raid-Helper is the Discord message ID of the event post.
    """

    @property
    def _auth_headers(self) -> dict:
        """Return authorization headers for server-level endpoints."""
        token = Config.RAID_HELPER_API_TOKEN
        if not token:
            return {}
        return {"Authorization": token}

    # ── Server event listing (v3, requires token) ─────────────────────

    async def get_server_events(self, server_id: int) -> list[dict]:
        """Fetch all events on the server.

        Returns a list of event dicts with at least:
          id, channelId, startTime, title, ...
        """
        url = f"{RAID_HELPER_API_V3}/servers/{server_id}/events"
        headers = self._auth_headers
        if not headers:
            logger.warning("No RAID_HELPER_API_TOKEN configured — cannot list server events")
            return []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # The response may be a dict with a list inside or a raw list
                        if isinstance(data, list):
                            events = data
                        elif isinstance(data, dict):
                            events = data.get("postedEvents", data.get("events", []))
                        else:
                            events = []
                        logger.info(
                            f"Fetched {len(events)} events from Raid-Helper for server {server_id}"
                        )
                        return events
                    else:
                        body = await resp.text()
                        logger.warning(
                            f"Raid-Helper server events API returned {resp.status}: {body[:200]}"
                        )
                        return []
        except Exception as e:
            logger.warning(f"Raid-Helper server events request failed: {e}")
            return []

    async def find_event_id_by_date(
        self, server_id: int, event_date: date
    ) -> Optional[int]:
        """Find the Raid-Helper event ID (message ID) for a given date.

        Queries the server events list and matches by startTime falling on
        the requested date (in UK timezone).
        Returns the event/message ID or None.
        """
        events = await self.get_server_events(server_id)
        if not events:
            return None

        for ev in events:
            start_time = ev.get("startTime")
            if not start_time:
                continue

            try:
                # startTime is a Unix timestamp (seconds)
                ev_dt = datetime.fromtimestamp(int(start_time), tz=timezone.utc)
                ev_date_uk = ev_dt.astimezone(UK_TZ).date()
            except (ValueError, TypeError, OSError):
                continue

            if ev_date_uk == event_date:
                event_id = ev.get("id")
                if event_id:
                    logger.info(
                        f"Matched Raid-Helper event {event_id} "
                        f"('{ev.get('title', '?')}') for date {event_date}"
                    )
                    return int(event_id)

        logger.info(f"No Raid-Helper event found for date {event_date}")
        return None

    # ── Single event detail (v2, public, no auth) ─────────────────────

    async def get_event(self, event_message_id: int) -> Optional[dict]:
        """Fetch full event data from Raid-Helper by message ID.

        Returns the parsed JSON dict or None on failure.
        """
        url = f"{RAID_HELPER_API_V2}/events/{event_message_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(
                            f"Fetched Raid-Helper event {event_message_id}: "
                            f"{data.get('title', '?')}"
                        )
                        return data
                    else:
                        logger.warning(
                            f"Raid-Helper API returned {resp.status} "
                            f"for event {event_message_id}"
                        )
                        return None
        except Exception as e:
            logger.warning(
                f"Raid-Helper API request failed for event {event_message_id}: {e}"
            )
            return None

    # ── Sign-up extraction ────────────────────────────────────────────

    async def get_signup_user_ids(self, event_message_id: int) -> list[int]:
        """Return a list of Discord user IDs who signed up to a Raid-Helper event.

        Filters to only include confirmed/accepted sign-ups.
        Excludes: Absence, Decline, Tentative, Bench, and any custom
        "declined" choices.  Uses a blocklist approach with broad matching
        so custom choice names like "Declined" are caught.
        """
        data = await self.get_event(event_message_id)
        if not data:
            return []

        signups = data.get("signUps", [])
        user_ids = []

        # Substrings that indicate the user did NOT accept
        DECLINE_KEYWORDS = (
            "absence", "absent", "decline", "tentative",
            "not going", "bench", "unavailable", "no",
        )

        for signup in signups:
            entry_name = (
                signup.get("entryName") or signup.get("className") or ""
            ).strip().lower()

            # Skip if the entry name contains any decline keyword
            if any(kw in entry_name for kw in DECLINE_KEYWORDS):
                logger.debug(
                    f"Skipping sign-up '{entry_name}' for user {signup.get('userId')}"
                )
                continue

            user_id = signup.get("userId") or signup.get("id")
            if user_id:
                try:
                    user_ids.append(int(user_id))
                except (ValueError, TypeError):
                    continue

        logger.info(
            f"Raid-Helper event {event_message_id}: "
            f"{len(user_ids)} confirmed sign-ups out of {len(signups)} total"
        )
        return user_ids

    async def get_signup_user_ids_by_date(
        self, server_id: int, event_date: date
    ) -> list[int]:
        """Convenience: find event by date then return sign-up user IDs."""
        event_id = await self.find_event_id_by_date(server_id, event_date)
        if not event_id:
            return []
        return await self.get_signup_user_ids(event_id)

    # ── Event update (v2, PATCH, requires server token) ───────────────

    async def update_event(
        self,
        event_message_id: int,
        *,
        description: str | None = None,
        image: str | None = None,
    ) -> bool:
        """Update a Raid-Helper event via PATCH /api/v2/events/{eventId}.

        Supported fields: description, image (URL).
        Returns True on success, False on failure.
        """
        url = f"{RAID_HELPER_API_V2}/events/{event_message_id}"
        headers = self._auth_headers
        if not headers:
            logger.warning("No RAID_HELPER_API_TOKEN configured — cannot update event")
            return False

        payload: dict = {}
        if description is not None:
            payload["description"] = description
        if image is not None:
            payload["image"] = image

        if not payload:
            logger.info("update_event called with nothing to update")
            return True

        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 204):
                        logger.info(
                            f"Updated Raid-Helper event {event_message_id}: "
                            f"fields={list(payload.keys())}"
                        )
                        return True
                    else:
                        body = await resp.text()
                        logger.warning(
                            f"Raid-Helper PATCH returned {resp.status} "
                            f"for event {event_message_id}: {body[:300]}"
                        )
                        return False
        except Exception as e:
            logger.warning(
                f"Raid-Helper PATCH request failed for event {event_message_id}: {e}"
            )
            return False

    # ── Briefing parsing ──────────────────────────────────────────────

    @staticmethod
    def parse_briefing_content(content: str, is_thursday: bool) -> str:
        """Parse a briefing post into a description for Raid-Helper.

        Expected briefing format:
            ## Training :training:
            Training Subject by XXXX

            ## Mission :mission:
            Briefing main post

        On Sundays only the ## Mission :mission: section is expected.
        Returns the parsed description preserving ## headers and emojis.
        """
        if not content or not content.strip():
            return ""

        # Split by ## headers (keep the delimiter)
        sections = re.split(r'(?=^## )', content.strip(), flags=re.MULTILINE)

        training_section = ""
        mission_section = ""

        for section in sections:
            stripped = section.strip()
            if not stripped:
                continue

            # Match ## Training (with optional emoji syntax)
            if re.match(r'^## Training\b', stripped, re.IGNORECASE):
                training_section = stripped

            # Match ## Mission (with optional emoji syntax)
            elif re.match(r'^## Mission\b', stripped, re.IGNORECASE):
                mission_section = stripped

        parts = []
        if is_thursday and training_section:
            parts.append(training_section)
        if mission_section:
            parts.append(mission_section)

        return "\n\n".join(parts)

    @staticmethod
    def extract_image_from_thread(thread: discord.Thread) -> str | None:
        """Extract the first image URL from a thread's starter message.

        Checks attachments first, then embed images/thumbnails.
        Must be called after fetching the starter_message.
        """
        starter = thread.starter_message
        if not starter:
            return None

        # Check attachments (uploaded images)
        for att in starter.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                return att.url

        # Check embeds (linked images)
        for embed in starter.embeds:
            if embed.image and embed.image.url:
                return embed.image.url
            if embed.thumbnail and embed.thumbnail.url:
                return embed.thumbnail.url

        return None

    async def update_event_from_briefing(
        self,
        server_id: int,
        event_date: date,
        briefing_thread: discord.Thread,
    ) -> bool:
        """Parse a briefing thread and update the matching Raid-Helper event.

        1. Find the Raid-Helper event for the given date.
        2. Parse the briefing thread's starter message content.
        3. Extract any attached image.
        4. PATCH the event with description + image.

        Returns True on success, False on failure.
        """
        # Find Raid-Helper event
        event_id = await self.find_event_id_by_date(server_id, event_date)
        if not event_id:
            logger.warning(
                f"Cannot update Raid-Helper event — no event found for {event_date}"
            )
            return False

        # Ensure we have the starter message
        starter = briefing_thread.starter_message
        if not starter:
            try:
                starter = await briefing_thread.fetch_message(briefing_thread.id)
            except Exception as e:
                logger.warning(f"Could not fetch starter message for thread {briefing_thread.id}: {e}")
                return False

        # Parse briefing content
        is_thursday = event_date.weekday() == 3
        description = self.parse_briefing_content(
            starter.content or "", is_thursday
        )

        if not description:
            logger.info(
                f"No parseable briefing content in thread '{briefing_thread.name}'"
            )
            return False

        # Extract image
        image_url = self.extract_image_from_thread(briefing_thread)

        # PATCH the event
        success = await self.update_event(
            event_id, description=description, image=image_url
        )

        if success:
            logger.info(
                f"Updated Raid-Helper event for {event_date} from briefing "
                f"'{briefing_thread.name}'"
            )
        return success


# Singleton
raid_helper_service = RaidHelperService()
