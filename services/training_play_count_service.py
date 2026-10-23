from dataclasses import dataclass
from datetime import date
import re

from .event_repository import event_repository


_CANCELLED_PATTERN = re.compile(r"\b(cancelled|canceled)\b", re.IGNORECASE)
_TBA_PATTERN = re.compile(r"^\s*tb[ad]\s*$", re.IGNORECASE)
_REPLAY_PREFIX_PATTERN = re.compile(r"^\s*replay\s*[-:]\s*", re.IGNORECASE)


@dataclass
class TrainingPlayRow:
    name: str
    play_count: int
    last_played: date


def should_count_training_name(name: str) -> bool:
    stripped = (name or "").strip()
    if not stripped:
        return False

    upper = stripped.upper()
    if upper == "EVENT CANCELLED":
        return False

    if _TBA_PATTERN.match(stripped):
        return False

    if _CANCELLED_PATTERN.search(stripped):
        return False

    return True


def canonicalize_training_name(name: str) -> str:
    value = (name or "").strip()
    value = _REPLAY_PREFIX_PATTERN.sub("", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


class TrainingPlayCountService:
    async def get_training_rows(self, guild_id: int) -> list[TrainingPlayRow]:
        fetcher = getattr(event_repository, "get_past_training_history", None)
        if callable(fetcher):
            rows = await fetcher(guild_id)
            source = [{"name": row["name"], "date": row["date"]} for row in rows]
        else:
            events = await event_repository.get_all_events_by_guild(guild_id)
            today = date.today()
            source = []
            for event in events:
                if event.type != "Training":
                    continue
                if not event.date or event.date >= today:
                    continue
                source.append({"name": event.name, "date": event.date})

        aggregate: dict[str, TrainingPlayRow] = {}
        for row in source:
            name = canonicalize_training_name(row["name"])
            if not should_count_training_name(name):
                continue

            existing = aggregate.get(name)
            if existing:
                existing.play_count += 1
                if row["date"] > existing.last_played:
                    existing.last_played = row["date"]
            else:
                aggregate[name] = TrainingPlayRow(
                    name=name,
                    play_count=1,
                    last_played=row["date"],
                )

        return sorted(
            aggregate.values(),
            key=lambda r: (-r.play_count, -r.last_played.toordinal(), r.name.casefold()),
        )


training_play_count_service = TrainingPlayCountService()