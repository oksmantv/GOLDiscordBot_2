import aiohttp
import discord
import logging
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)

RAID_HELPER_API = "https://raid-helper.xyz/api/v4"

UK_TZ = ZoneInfo("Europe/London")


class RaidHelperService:
    """HTTP client for the Raid-Helper API (v4, raid-helper.xyz).

    - GET /api/v4/servers/{serverId}/events  (requires server API token)
      Lists all events on the server with basic data including startTime.
    - GET /api/v4/events/{eventId}           (public, no auth)
      Fetches full event data including all sign-ups.
    - PATCH /api/v4/events/{eventId}         (requires server API token)
      Update an event.

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
        url = f"{RAID_HELPER_API}/servers/{server_id}/events"
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
                            logger.debug(
                                f"Raid-Helper response keys: {list(data.keys())}"
                            )
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
            logger.warning(f"Raid-Helper returned no events for server {server_id}")
            return None

        logger.info(
            f"Searching {len(events)} Raid-Helper events for date {event_date}"
        )
        for ev in events:
            start_time = ev.get("startTime")
            if not start_time:
                logger.debug(f"Event {ev.get('id', '?')} has no startTime, keys: {list(ev.keys())}")
                continue

            try:
                # startTime is a Unix timestamp (seconds)
                ev_dt = datetime.fromtimestamp(int(start_time), tz=timezone.utc)
                ev_date_uk = ev_dt.astimezone(UK_TZ).date()
            except (ValueError, TypeError, OSError) as exc:
                logger.debug(f"Event {ev.get('id', '?')} startTime parse error: {exc}")
                continue

            logger.debug(
                f"Event {ev.get('id', '?')} '{ev.get('title', '?')}': "
                f"startTime={start_time} -> UK date={ev_date_uk} (looking for {event_date})"
            )

            if ev_date_uk == event_date:
                event_id = ev.get("id")
                if event_id:
                    logger.info(
                        f"Matched Raid-Helper event {event_id} "
                        f"('{ev.get('title', '?')}') for date {event_date}"
                    )
                    return int(event_id)

        logger.warning(f"No Raid-Helper event matched date {event_date} out of {len(events)} events")
        return None

    # ── Single event detail (v2, public, no auth) ─────────────────────

    async def get_event(self, event_message_id: int) -> Optional[dict]:
        """Fetch full event data from Raid-Helper by message ID.

        Returns the parsed JSON dict or None on failure.
        """
        url = f"{RAID_HELPER_API}/events/{event_message_id}"
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

        # Substrings that indicate the user did NOT accept/attend
        DECLINE_KEYWORDS = (
            "absence", "absent", "decline", "tentative",
            "not going", "bench", "unavailable",
        )

        for signup in signups:
            class_name = (signup.get("className") or "").strip().lower()

            # Skip if the class name contains any decline keyword
            if any(kw in class_name for kw in DECLINE_KEYWORDS):
                logger.debug(
                    f"Skipping sign-up class='{class_name}' for user {signup.get('userId')}"
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
        attendance: str | None = None,
    ) -> bool:
        """Update a Raid-Helper event via PATCH /api/v4/events/{eventId}.

        Supported fields: description, image (URL), attendance (advancedSettings).
        Returns True on success, False on failure.
        """
        url = f"{RAID_HELPER_API}/events/{event_message_id}"
        headers = self._auth_headers
        if not headers:
            logger.warning("No RAID_HELPER_API_TOKEN configured — cannot update event")
            return False

        payload: dict = {}
        if description is not None:
            payload["description"] = description

        # DEBUG: Fetch current event to inspect advancedSettings keys and image handling
        current = await self.get_event(event_message_id)
        if current:
            adv = current.get("advancedSettings", {})
            if isinstance(adv, dict):
                logger.info(f"DEBUG advancedSettings keys: {list(adv.keys())}")
                for k in adv:
                    if "image" in k.lower() or "img" in k.lower():
                        logger.info(f"DEBUG advancedSettings['{k}']: {adv[k]}")

        # advancedSettings is a dict in v4 — send image and attendance inside it
        adv_settings: dict = {}
        if image is not None:
            adv_settings["image"] = image
        if attendance is not None:
            adv_settings["attendance"] = attendance

        if adv_settings:
            payload["advancedSettings"] = adv_settings

        # Log the full payload for debugging
        logger.info(f"Raid-Helper PATCH payload for event {event_message_id}: {payload}")

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
                    body = await resp.text()
                    if resp.status in (200, 204):
                        logger.info(
                            f"Updated Raid-Helper event {event_message_id}: "
                            f"fields={list(payload.keys())}, response={body[:300]}"
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

    # ── Briefing composition ─────────────────────────────────────────

    @staticmethod
    def build_event_description(
        briefing_content: str,
        *,
        is_thursday: bool,
        training_name: str = "",
        instructor_name: str = "",
    ) -> str:
        """Build the Raid-Helper event description using fixed headers
        and dynamic content.

        Thursday format:
            ## Training :training:
            **{training_name} by {instructor_name}**
            ## Mission :mission:
            {briefing post content}

        Sunday format (no training):
            {briefing post content}

        The briefing_content is the raw starter message from the
        mission briefing forum thread.
        """
        if is_thursday:
            # Training line
            training_info = "**TBA**"
            if training_name and instructor_name:
                training_info = f"**{training_name} by {instructor_name}**"
            elif training_name:
                training_info = f"**{training_name}**"
            elif instructor_name:
                training_info = f"**TBA by {instructor_name}**"

            # Mission line
            mission_info = briefing_content.strip() if briefing_content else "**TBA**"

            return (
                f"## Training <:Training:1173686838926512199>\n{training_info}\n"
                f"## Mission <:Mission:1173686836451885076>\n{mission_info}"
            )
        else:
            # Sunday: just the mission briefing content
            return briefing_content.strip() if briefing_content else ""

    @staticmethod
    def extract_image_from_message(message: discord.Message) -> str | None:
        """Extract the first image URL from a Discord message.

        Checks attachments first, then embed images/thumbnails.
        """
        if not message:
            return None

        # Check attachments (uploaded images)
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                return att.url

        # Check embeds (linked images)
        for embed in message.embeds:
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
        *,
        training_name: str = "",
        instructor_name: str = "",
    ) -> str:
        """Compose and update the Raid-Helper event description from a
        briefing thread and schedule data.

        1. Find the Raid-Helper event for the given date.
        2. Read the briefing thread's starter message (= mission content).
        3. Build description with fixed headers + dynamic content.
        4. Extract any attached image.
        5. PATCH the event with description + image.

        Args:
            server_id: Discord guild/server ID.
            event_date: The event date.
            briefing_thread: The mission briefing forum thread.
            training_name: Training event name from schedule (Thursdays).
            instructor_name: Instructor name from schedule (Thursdays).

        Returns empty string on success, or a descriptive error message on failure.
        """
        # Find Raid-Helper event
        event_id = await self.find_event_id_by_date(server_id, event_date)
        if not event_id:
            msg = f"No Raid-Helper event found for {event_date}"
            logger.warning(msg)
            return msg

        # Ensure we have the starter message
        starter = briefing_thread.starter_message
        if not starter:
            try:
                starter = await briefing_thread.fetch_message(briefing_thread.id)
            except Exception as e:
                msg = f"Could not fetch starter message for thread '{briefing_thread.name}': {e}"
                logger.warning(msg)
                return msg

        briefing_content = starter.content or ""
        if not briefing_content.strip():
            msg = f"Briefing thread '{briefing_thread.name}' has no text content"
            logger.info(msg)
            return msg

        # Build description
        is_thursday = event_date.weekday() == 3
        description = self.build_event_description(
            briefing_content,
            is_thursday=is_thursday,
            training_name=training_name,
            instructor_name=instructor_name,
        )

        if not description:
            msg = f"Empty description built from thread '{briefing_thread.name}'"
            logger.info(msg)
            return msg

        # Extract image from the starter message we already fetched
        image_url = self.extract_image_from_message(starter)

        # PATCH the event
        success = await self.update_event(
            event_id, description=description, image=image_url
        )

        if success:
            logger.info(
                f"Updated Raid-Helper event for {event_date} from briefing "
                f"'{briefing_thread.name}'"
            )
            return ""

        return f"Raid-Helper API PATCH failed for event {event_id}"


# Singleton
raid_helper_service = RaidHelperService()
