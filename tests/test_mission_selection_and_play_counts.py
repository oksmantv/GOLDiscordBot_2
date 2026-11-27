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
    find_best_matching_thread_for_history_name,
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

    def test_combined_framework_filter_matches_either_tag(self):
        threads = [
            _Thread(1, "A", ["Framework 3.0", "Infantry"], self.now),
            _Thread(2, "B", ["Framework 4.0"], self.now),
            _Thread(3, "C", ["Framework 2.0"], self.now),
        ]
        filtered = mission_poll_service.filter_threads_by_tags(
            threads, "Framework 3.0 + Framework 4.0"
        )
        self.assertEqual([t.id for t in filtered], [1, 2])

        single = mission_poll_service.filter_threads_by_tags(threads, "Framework 4.0")
        self.assertEqual([t.id for t in single], [2])

    def test_abbreviate_combined_framework(self):
        self.assertEqual(mission_poll_service.abbreviate_framework("Framework 3.0"), "FW 3.0")
        self.assertEqual(
            mission_poll_service.abbreviate_framework("Framework 3.0 + Framework 4.0"),
            "FW 3.0/4.0",
        )

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

    def test_equal_play_counts_prefer_new_briefing(self):
        older = _Thread(1, "Operation Older", ["Thursday"], self.now - timedelta(days=90))
        newer = _Thread(2, "Operation Newer", ["Thursday"], self.now - timedelta(days=2))
        selected, _ = select_with_day_priority(
            [older, newer],
            count=1,
            day_tag="Thursday",
            play_counts={1: 0, 2: 0},
        )
        self.assertEqual(selected[0].id, 2)

    def test_distinct_timestamps_still_randomize(self):
        threads = [
            _Thread(i, f"Operation {i}", ["Thursday"], self.now - timedelta(days=60 + i, seconds=i))
            for i in range(1, 9)
        ]
        observed = set()
        for seed in range(20):
            random.seed(seed)
            selected, _ = select_with_day_priority(threads, count=3, day_tag="Thursday")
            observed.add(tuple(sorted(t.id for t in selected)))
        self.assertGreater(len(observed), 1)

    def test_recent_poll_appearances_push_mission_down(self):
        loser = _Thread(1, "Operation Loser", ["Thursday"], self.now - timedelta(days=60))
        fresh = _Thread(2, "Operation Fresh", ["Thursday"], self.now - timedelta(days=60))
        for seed in range(10):
            random.seed(seed)
            selected, _ = select_with_day_priority(
                [loser, fresh],
                count=1,
                day_tag="Thursday",
                play_counts={1: 0, 2: 0},
                poll_appearances={1: 3},
            )
            self.assertEqual(selected[0].id, 2)

    def test_explain_candidate_reasons(self):
        old = self.now - timedelta(days=90)
        threads = [
            _Thread(1, "Op Tagged", ["Thursday"], old),
            _Thread(2, "Op Low", [], old),
            _Thread(3, "Op High", [], old),
            _Thread(4, "Op TieA", [], old),
            _Thread(5, "Op TieB", [], old),
        ]
        ranked = mission_poll_service.rank_candidates(
            threads,
            count=3,
            day_tag="Thursday",
            play_counts={2: 0, 3: 5, 4: 1, 5: 1},
        )
        by_id = {c.thread.id: c for c in ranked}

        def reason(thread_id):
            return mission_poll_service.explain_candidate(by_id[thread_id], ranked, 3, "Thursday")

        self.assertEqual([c.thread.id for c in ranked[:2]], [1, 2])
        self.assertIn("Thursday-tagged", reason(1))
        self.assertIn("Lower exposure", reason(2))
        self.assertIn("random draw", reason(4))
        self.assertIn("random draw", reason(5))
        self.assertIn("Higher exposure", reason(3))
        self.assertFalse(by_id[3].selected)
        self.assertEqual(by_id[4].tie_group_size, 2)
        self.assertEqual(by_id[4].tie_group_selected, 1)

    def test_poll_appearances_and_plays_combine_into_exposure(self):
        polled = _Thread(1, "Operation Polled", ["Thursday"], self.now - timedelta(days=60))
        played = _Thread(2, "Operation Played", ["Thursday"], self.now - timedelta(days=60))
        selected, _ = select_with_day_priority(
            [polled, played],
            count=1,
            day_tag="Thursday",
            play_counts={1: 0, 2: 1},
            poll_appearances={1: 2},
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

    def test_exclusion_weeks_gate_is_normalized_not_fuzzy(self):
        exact_thread = _Thread(10, "Operation Iron Dawn", ["Sunday"], self.now)
        fuzzy_thread = _Thread(11, "Sunday Operation - Iron Dawn", ["Sunday"], self.now)
        short_thread = _Thread(12, "Op Steel Rain", ["Sunday"], self.now)
        similar_thread = _Thread(13, "Operation Iron Dusk", ["Sunday"], self.now)

        class _Event(SimpleNamespace):
            pass

        async def _run_check():
            original = mission_poll_service.event_repository.get_events_by_guild_and_date_range
            mission_poll_service.event_repository.get_events_by_guild_and_date_range = _fake_fetch
            try:
                excluded, _ = await mission_poll_service.get_excluded_thread_ids(
                    1,
                    [exact_thread, fuzzy_thread, short_thread, similar_thread],
                    weeks=8,
                )
                return excluded
            finally:
                mission_poll_service.event_repository.get_events_by_guild_and_date_range = original

        async def _fake_fetch(guild_id, start, end):
            return [
                _Event(name="Operation Iron Dawn"),
                _Event(name="Sunday Operation - Steel Rain"),
            ]

        import asyncio

        excluded = asyncio.run(_run_check())
        self.assertIn(10, excluded)
        self.assertNotIn(11, excluded)
        self.assertIn(12, excluded)
        self.assertNotIn(13, excluded)

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

    def test_link_hint_fuzzy_match_catches_typo(self):
        thread = _Thread(1, "Operation Tugowar", ["Thursday"], self.now)
        matched, score = find_best_matching_thread_for_history_name(
            "Opeartion Tugowar",
            [thread],
            min_score=0.90,
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched.id, 1)
        self.assertGreaterEqual(score, 0.90)

    def test_link_hint_fuzzy_match_rejects_weak_candidate(self):
        thread = _Thread(1, "Operation Brockendome", ["Sunday"], self.now)
        matched, score = find_best_matching_thread_for_history_name(
            "Malden Brocken Dome",
            [thread],
            min_score=0.90,
        )
        self.assertIsNone(matched)
        self.assertLess(score, 0.90)


if __name__ == "__main__":
    unittest.main()
