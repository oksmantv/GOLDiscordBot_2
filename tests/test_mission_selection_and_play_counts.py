from __future__ import annotations

import random
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from services.mission_play_count_service import (
    MissionHistoryEntry,
    compute_play_data_for_threads,
    MissionPlayCountService,
    canonicalize_history_name,
    should_count_history_name,
)
from services.mission_poll_service import select_with_day_priority
from services import mission_poll_service


class _Tag:
    def __init__(self, name: str):
        self.name = name


class _Thread(SimpleNamespace):
    def __init__(self, thread_id: int, name: str, tags: list[str], created_at: datetime):
        super().__init__(
            id=thread_id,
            name=name,
            applied_tags=[_Tag(tag) for tag in tags],
            created_at=created_at,
        )


class MissionSelectionAndPlayCountTests(unittest.TestCase):
    def setUp(self):
        random.seed(42)
        self.now = datetime.now(timezone.utc)

    def test_unplayed_ranked_before_played_inside_day_pool(self):
        a = _Thread(1, "Operation Alpha", ["Thursday"], self.now - timedelta(days=3))
        b = _Thread(2, "Operation Bravo", ["Thursday"], self.now - timedelta(days=2))
        selected, _ = select_with_day_priority(
            [a, b],
            count=1,
            day_tag="Thursday",
            play_counts={1: 3, 2: 0},
        )
        self.assertEqual(selected[0].id, 2)

    def test_day_tag_pool_fills_before_untagged_even_if_more_played(self):
        tagged = _Thread(1, "Operation Tagged", ["Thursday"], self.now - timedelta(days=5))
        untagged = _Thread(2, "Operation Untagged", ["Infantry"], self.now - timedelta(days=1))
        selected, _ = select_with_day_priority(
            [tagged, untagged],
            count=1,
            day_tag="Thursday",
            play_counts={1: 8, 2: 0},
        )
        self.assertEqual(selected[0].id, 1)

    def test_equal_play_counts_prefer_newer_briefing(self):
        older = _Thread(1, "Operation Older", ["Thursday"], self.now - timedelta(days=9))
        newer = _Thread(2, "Operation Newer", ["Thursday"], self.now - timedelta(days=2))
        selected, _ = select_with_day_priority(
            [older, newer],
            count=1,
            day_tag="Thursday",
            play_counts={1: 0, 2: 0},
        )
        self.assertEqual(selected[0].id, 2)

    def test_exact_tie_is_not_fixed_order(self):
        threads = [
            _Thread(1, "Operation One", ["Thursday"], self.now - timedelta(days=2)),
            _Thread(2, "Operation Two", ["Thursday"], self.now - timedelta(days=2)),
        ]

        observed = set()
        for seed in (1, 2, 3, 4, 5, 6):
            random.seed(seed)
            selected, _ = select_with_day_priority(
                threads,
                count=1,
                day_tag="Thursday",
                play_counts={1: 0, 2: 0},
            )
            observed.add(selected[0].id)

        self.assertEqual(observed, {1, 2})

    def test_cancelled_blank_training_future_not_counted(self):
        t = _Thread(1, "Sunday Operation - Iron Dawn", ["Sunday"], self.now)
        future_day = date.today() + timedelta(days=10)
        history = [
            MissionHistoryEntry(name="", played_on=date(2025, 1, 1)),
            MissionHistoryEntry(name="EVENT CANCELLED", played_on=date(2025, 1, 2)),
            MissionHistoryEntry(name="Thursday Training - CQB", played_on=date(2025, 1, 3)),
            MissionHistoryEntry(name="Sunday Operation - Iron Dawn", played_on=date(2025, 1, 4)),
            MissionHistoryEntry(name="Sunday Operation - Iron Dawn", played_on=future_day),
        ]
        data = compute_play_data_for_threads([t], history)
        self.assertEqual(data.thread_play_counts[1], 1)

    def test_hired_guns_does_not_absorb_hired_guns_two(self):
        t = _Thread(1, "Hired Guns", ["Sunday"], self.now)
        history = [
            MissionHistoryEntry(name="Hired Guns", played_on=date(2025, 1, 1)),
            MissionHistoryEntry(name="Hired Guns II", played_on=date(2025, 1, 2)),
        ]
        data = compute_play_data_for_threads([t], history)
        self.assertEqual(data.thread_play_counts[1], 1)
        self.assertEqual(len(data.history_only), 1)
        self.assertEqual(data.history_only[0].name, "Hired Guns II")

    def test_medium_fuzzy_not_attached(self):
        t = _Thread(1, "Operation Jungle Storm", ["Sunday"], self.now)
        history = [MissionHistoryEntry(name="Operation Jungle Wind", played_on=date(2025, 2, 1))]
        data = compute_play_data_for_threads([t], history)
        self.assertEqual(data.thread_play_counts[1], 0)
        self.assertEqual(len(data.history_only), 1)
        self.assertEqual(data.history_only[0].name, "Operation Jungle Wind")

    def test_cancelled_and_tba_variants_are_not_counted(self):
        self.assertFalse(should_count_history_name("Cancelled"))
        self.assertFalse(should_count_history_name("Cancelled Mission"))
        self.assertFalse(should_count_history_name("Mission canceled"))
        self.assertFalse(should_count_history_name("TBA"))

    def test_replay_prefix_and_unplayed_suffix_are_normalized(self):
        self.assertEqual(canonicalize_history_name("Replay - Tiny Steel"), "Tiny Steel")
        self.assertEqual(
            canonicalize_history_name("Operation Petrakivskyi [UNPLAYED]"),
            "Operation Petrakivskyi",
        )

    def test_exclusion_weeks_gate_stays_exact_match(self):
        exact_thread = _Thread(10, "Operation Iron Dawn", ["Sunday"], self.now)
        fuzzy_thread = _Thread(11, "Sunday Operation - Iron Dawn", ["Sunday"], self.now)

        class _Event(SimpleNamespace):
            pass

        async def _run_check():
            original = mission_poll_service.event_repository.get_events_by_guild_and_date_range
            mission_poll_service.event_repository.get_events_by_guild_and_date_range = _fake_fetch
            try:
                excluded, _ = await mission_poll_service.get_excluded_thread_ids(
                    1,
                    [exact_thread, fuzzy_thread],
                    weeks=8,
                )
                return excluded
            finally:
                mission_poll_service.event_repository.get_events_by_guild_and_date_range = original

        async def _fake_fetch(guild_id, start, end):
            return [_Event(name="Operation Iron Dawn")]

        import asyncio

        excluded = asyncio.run(_run_check())
        self.assertIn(10, excluded)
        self.assertNotIn(11, excluded)

    def test_play_count_service_fallback_without_repo_helper(self):
        thread = _Thread(1, "Operation Dawn", ["Sunday"], self.now)

        class _Event(SimpleNamespace):
            pass

        async def _run_check():
            import services.mission_play_count_service as mpcs

            original_helper = getattr(mpcs.event_repository, "get_past_mission_history", None)
            original_get_all = mpcs.event_repository.get_all_events_by_guild
            mpcs.event_repository.get_past_mission_history = None

            async def _fake_get_all(guild_id):
                return [
                    _Event(type="Mission", date=date(2025, 1, 1), name="Operation Dawn"),
                    _Event(type="Mission", date=date(2025, 1, 2), name="EVENT CANCELLED"),
                    _Event(type="Training", date=date(2025, 1, 3), name="CQB"),
                ]

            mpcs.event_repository.get_all_events_by_guild = _fake_get_all

            try:
                service = MissionPlayCountService()
                data = await service.get_play_data_for_threads(123, [thread])
                return data
            finally:
                mpcs.event_repository.get_all_events_by_guild = original_get_all
                mpcs.event_repository.get_past_mission_history = original_helper

        import asyncio

        data = asyncio.run(_run_check())
        self.assertEqual(data.thread_play_counts[1], 1)


if __name__ == "__main__":
    unittest.main()
