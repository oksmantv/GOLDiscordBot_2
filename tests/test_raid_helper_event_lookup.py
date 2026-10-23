from datetime import date, datetime, timezone
import unittest

from services.raid_helper_service import RaidHelperService


class RaidHelperEventLookupTests(unittest.IsolatedAsyncioTestCase):
    event_date = date(2026, 10, 25)

    @staticmethod
    def _event(event_id: int, channel_id: int) -> dict:
        return {
            "id": event_id,
            "channelId": channel_id,
            "startTime": int(datetime(2026, 10, 25, 19, tzinfo=timezone.utc).timestamp()),
            "title": f"Event {event_id}",
        }

    async def test_uses_configured_channel_when_events_share_a_date(self):
        service = RaidHelperService()

        async def get_server_events(_server_id):
            return [self._event(1001, 11), self._event(1002, 22)]

        service.get_server_events = get_server_events

        event_id = await service.find_event_id_by_date(
            123, self.event_date, channel_id=22
        )

        self.assertEqual(event_id, 1002)

    async def test_rejects_ambiguous_matches_in_the_configured_channel(self):
        service = RaidHelperService()

        async def get_server_events(_server_id):
            return [self._event(1001, 22), self._event(1002, 22)]

        service.get_server_events = get_server_events

        event_id = await service.find_event_id_by_date(
            123, self.event_date, channel_id=22
        )

        self.assertIsNone(event_id)

    async def test_rejects_ambiguous_date_when_channel_is_not_provided(self):
        service = RaidHelperService()

        async def get_server_events(_server_id):
            return [self._event(1001, 11), self._event(1002, 22)]

        service.get_server_events = get_server_events

        event_id = await service.find_event_id_by_date(123, self.event_date)

        self.assertIsNone(event_id)


if __name__ == "__main__":
    unittest.main()