import aiohttp
import logging
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

        Filters to only include confirmed sign-ups (excludes Absence,
        Tentative, Decline, etc.).
        """
        data = await self.get_event(event_message_id)
        if not data:
            return []

        signups = data.get("signUps", [])
        user_ids = []
        for signup in signups:
            entry_name = (
                signup.get("entryName") or signup.get("className") or ""
            ).lower()
            # Skip absence / decline / tentative entries
            if entry_name in (
                "absence", "tentative", "decline", "not going", "bench",
            ):
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


# Singleton
raid_helper_service = RaidHelperService()
