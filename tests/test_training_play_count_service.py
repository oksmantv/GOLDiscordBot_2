from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from services.training_play_count_service import (
    TrainingPlayCountService,
    canonicalize_training_name,
    should_count_training_name,
)


class TrainingPlayCountServiceTests(unittest.TestCase):
    def test_filters_cancelled_and_tba(self):
        self.assertFalse(should_count_training_name("EVENT CANCELLED"))
        self.assertFalse(should_count_training_name("Cancelled"))
        self.assertFalse(should_count_training_name("TBA"))
        self.assertTrue(should_count_training_name("CQB Basics"))

    def test_canonicalize_replay_prefix(self):
        self.assertEqual(canonicalize_training_name("Replay - CQB Basics"), "CQB Basics")

    def test_service_aggregates_with_fallback(self):
        class _Event(SimpleNamespace):
            pass

        async def _run():
            import services.training_play_count_service as tpcs

            original_fetch = getattr(tpcs.event_repository, "get_past_training_history", None)
            original_get_all = tpcs.event_repository.get_all_events_by_guild

            tpcs.event_repository.get_past_training_history = None

            async def _fake_get_all(guild_id):
                return [
                    _Event(type="Training", date=date(2026, 1, 1), name="CQB Basics"),
                    _Event(type="Training", date=date(2026, 2, 1), name="Replay - CQB Basics"),
                    _Event(type="Training", date=date(2026, 3, 1), name="Cancelled"),
                    _Event(type="Mission", date=date(2026, 4, 1), name="Operation X"),
                ]

            tpcs.event_repository.get_all_events_by_guild = _fake_get_all

            try:
                service = TrainingPlayCountService()
                return await service.get_training_rows(123)
            finally:
                tpcs.event_repository.get_all_events_by_guild = original_get_all
                tpcs.event_repository.get_past_training_history = original_fetch

        import asyncio

        rows = asyncio.run(_run())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "CQB Basics")
        self.assertEqual(rows[0].play_count, 2)


if __name__ == "__main__":
    unittest.main()
