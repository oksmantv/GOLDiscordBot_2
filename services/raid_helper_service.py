import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)

RAID_HELPER_API_BASE = "https://raid-helper.dev/api/v2"


class RaidHelperService:
    """HTTP client for the Raid-Helper public API.

    The GET /events/{eventId} endpoint is public and requires NO authorization.
    The event ID in Raid-Helper is the Discord message ID of the event post.
    """

    async def get_event(self, event_message_id: int) -> Optional[dict]:
        """Fetch full event data from Raid-Helper by message ID.

        Returns the parsed JSON dict or None on failure.
        """
        url = f"{RAID_HELPER_API_BASE}/events/{event_message_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"Fetched Raid-Helper event {event_message_id}: {data.get('title', '?')}")
                        return data
                    else:
                        logger.warning(
                            f"Raid-Helper API returned {resp.status} for event {event_message_id}"
                        )
                        return None
        except Exception as e:
            logger.warning(f"Raid-Helper API request failed for event {event_message_id}: {e}")
            return None

    async def get_signup_user_ids(self, event_message_id: int) -> list[int]:
        """Return a list of Discord user IDs who signed up to a Raid-Helper event.

        Filters to only include confirmed sign-ups (entryName != 'Absence'
        and entryName != 'Tentative' and entryName != 'Decline').
        """
        data = await self.get_event(event_message_id)
        if not data:
            return []

        signups = data.get("signUps", [])
        user_ids = []
        for signup in signups:
            entry_name = (signup.get("entryName") or signup.get("className") or "").lower()
            # Skip absence / decline / tentative entries
            if entry_name in ("absence", "tentative", "decline", "not going", "bench"):
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


# Singleton
raid_helper_service = RaidHelperService()
