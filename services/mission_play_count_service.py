import logging
import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Optional

from .event_repository import event_repository

logger = logging.getLogger(__name__)

_HISTORY_EXCLUDE_PATTERN = re.compile(
    r"\b(training|poll|strawpoll|meeting|hangout|wargame|editing meetup)\b",
    re.IGNORECASE,
)

_CANCELLED_VARIANT_PATTERN = re.compile(
    r"\b(cancelled|canceled)\b",
    re.IGNORECASE,
)

_REPLAY_PREFIX_PATTERN = re.compile(
    r"^\s*replay\s*[-:]\s*",
    re.IGNORECASE,
)

_UNPLAYED_SUFFIX_PATTERN = re.compile(
    r"\s*\[\s*unplayed\s*\]\s*$",
    re.IGNORECASE,
)

_TBA_VARIANT_PATTERN = re.compile(
    r"^\s*tb[ad]\s*$",
    re.IGNORECASE,
)

_DAY_TRAINING_WRAPPER_PREFIX_PATTERN = re.compile(
    r"^\s*(?:thursday|sunday)\s+(?:training\s*&\s*mission|training\s+and\s+mission)\s*-\s*",
    re.IGNORECASE,
)


@dataclass
class MissionHistoryEntry:
    name: str
    played_on: date


@dataclass
class HistoryOnlyMission:
    name: str
    play_count: int
    last_played: Optional[date]


@dataclass
class MissionPlayData:
    thread_play_counts: dict[int, int]
    thread_last_played: dict[int, Optional[date]]
    history_only: list[HistoryOnlyMission]


def _strip_rank_emoji_prefix(value: str) -> str:
    # Remove leading custom Discord emoji tokens and surrounding whitespace.
    cleaned = re.sub(r"^(?:\s*<a?:\w+:\d+>\s*)+", "", value)
    return cleaned.strip()


def _strip_event_wrapper(value: str) -> str:
    wrappers = [
        r"^(?:thursday|sunday)\s+operation\s*-\s*",
        r"^(?:thursday|sunday)\s+training\s*&\s*mission\s*-\s*",
        r"^(?:thursday|sunday)\s+training\s+and\s+mission\s*-\s*",
    ]
    result = value
    for wrapper in wrappers:
        result = re.sub(wrapper, "", result, flags=re.IGNORECASE)
    return result


def normalize_mission_title(name: str, *, strip_event_wrapper: bool = False) -> str:
    value = (name or "").casefold().strip()
    value = _strip_rank_emoji_prefix(value)
    value = re.sub(r"\s+", " ", value)

    if strip_event_wrapper:
        value = _strip_event_wrapper(value)

    value = re.sub(r"^(?:operation|op)\s+", "", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def should_count_history_name(name: str) -> bool:
    stripped = (name or "").strip()
    if not stripped:
        return False

    upper = stripped.upper()
    if upper == "EVENT CANCELLED":
        return False

    if _TBA_VARIANT_PATTERN.match(stripped):
        return False

    if _CANCELLED_VARIANT_PATTERN.search(stripped):
        return False

    if _HISTORY_EXCLUDE_PATTERN.search(stripped):
        return False

    return True


def canonicalize_history_name(name: str) -> str:
    value = (name or "").strip()
    value = _REPLAY_PREFIX_PATTERN.sub("", value)
    value = _UNPLAYED_SUFFIX_PATTERN.sub("", value)
    value = _DAY_TRAINING_WRAPPER_PREFIX_PATTERN.sub("", value)
    return value.strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(a=a, b=b).ratio()


def compute_play_data_for_threads(
    threads: list,
    history_entries: list[MissionHistoryEntry],
    *,
    high_fuzzy_threshold: float = 0.92,
    medium_fuzzy_threshold: float = 0.80,
) -> MissionPlayData:
    thread_play_counts: dict[int, int] = {thread.id: 0 for thread in threads}
    thread_last_played: dict[int, Optional[date]] = {thread.id: None for thread in threads}

    if not threads:
        return MissionPlayData(thread_play_counts, thread_last_played, [])

    thread_exact_names: dict[int, str] = {
        thread.id: (thread.name or "").strip().casefold() for thread in threads
    }
    thread_normalized_names: dict[int, str] = {
        thread.id: normalize_mission_title(thread.name or "") for thread in threads
    }

    history_only_aggregate: dict[str, HistoryOnlyMission] = {}

    for entry in history_entries:
        if entry.played_on >= date.today():
            continue

        raw_name = canonicalize_history_name(entry.name)
        if not should_count_history_name(raw_name):
            continue

        history_exact = raw_name.casefold()
        history_normalized = normalize_mission_title(raw_name, strip_event_wrapper=True)

        exact_candidates = [
            thread.id
            for thread in threads
            if thread_exact_names[thread.id] == history_exact
        ]
        if exact_candidates:
            thread_id = exact_candidates[0]
            thread_play_counts[thread_id] += 1
            last_played = thread_last_played[thread_id]
            if last_played is None or entry.played_on > last_played:
                thread_last_played[thread_id] = entry.played_on
            continue

        normalized_candidates = [
            thread.id
            for thread in threads
            if thread_normalized_names[thread.id] == history_normalized
        ]
        if normalized_candidates:
            thread_id = normalized_candidates[0]
            thread_play_counts[thread_id] += 1
            last_played = thread_last_played[thread_id]
            if last_played is None or entry.played_on > last_played:
                thread_last_played[thread_id] = entry.played_on
            continue

        best_thread_id = None
        best_score = 0.0
        for thread in threads:
            candidate = thread_normalized_names[thread.id]
            score = _similarity(history_normalized, candidate)
            if score > best_score:
                best_score = score
                best_thread_id = thread.id

        if best_thread_id is not None and best_score >= high_fuzzy_threshold:
            logger.info(
                "Accepted high-fuzzy mission history match '%s' -> '%s' (%.3f)",
                raw_name,
                next((t.name for t in threads if t.id == best_thread_id), "unknown"),
                best_score,
            )
            thread_play_counts[best_thread_id] += 1
            last_played = thread_last_played[best_thread_id]
            if last_played is None or entry.played_on > last_played:
                thread_last_played[best_thread_id] = entry.played_on
            continue

        if best_thread_id is not None and best_score >= medium_fuzzy_threshold:
            logger.info(
                "Ignored medium-fuzzy mission history match '%s' (best %.3f) to avoid unsafe attach",
                raw_name,
                best_score,
            )

        existing = history_only_aggregate.get(raw_name)
        if existing:
            existing.play_count += 1
            if existing.last_played is None or entry.played_on > existing.last_played:
                existing.last_played = entry.played_on
        else:
            history_only_aggregate[raw_name] = HistoryOnlyMission(
                name=raw_name,
                play_count=1,
                last_played=entry.played_on,
            )

    history_only = sorted(
        history_only_aggregate.values(),
        key=lambda row: (
            -row.play_count,
            -(row.last_played.toordinal() if row.last_played else 0),
            row.name.casefold(),
        ),
    )
    return MissionPlayData(thread_play_counts, thread_last_played, history_only)


class MissionPlayCountService:
    async def _fetch_past_mission_rows(self, guild_id: int) -> list[dict]:
        history_fetcher = getattr(event_repository, "get_past_mission_history", None)
        if callable(history_fetcher):
            rows = await history_fetcher(guild_id)
            return [{"name": row["name"], "date": row["date"]} for row in rows]

        # Backward-compatible fallback for deployments where the repository method
        # is not yet present. This keeps /missionplayedcount functional.
        events = await event_repository.get_all_events_by_guild(guild_id)
        today = date.today()
        rows = []
        for event in events:
            if event.type != "Mission":
                continue
            if not event.date or event.date >= today:
                continue
            if not (event.name or "").strip():
                continue
            if (event.name or "").strip().upper() == "EVENT CANCELLED":
                continue
            rows.append({"name": event.name, "date": event.date})
        return rows

    async def get_play_data_for_threads(self, guild_id: int, threads: list) -> MissionPlayData:
        rows = await self._fetch_past_mission_rows(guild_id)
        history_entries = [
            MissionHistoryEntry(name=row["name"], played_on=row["date"])
            for row in rows
        ]
        return compute_play_data_for_threads(threads, history_entries)


mission_play_count_service = MissionPlayCountService()