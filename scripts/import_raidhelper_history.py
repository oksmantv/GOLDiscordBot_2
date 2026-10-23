#!/usr/bin/env python3
"""Create a human-review CSV from a Raid-Helper history export.

Delivery 2 safety-first flow:
1) parse (implemented here): produce review rows from source CSV
2) backup (future)
3) apply (future)
"""

from __future__ import annotations

import argparse
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

BLOCK_START = "-- start --"
BLOCK_END = "-- end --"
WEEKDAY_SLOT = {3: "Thursday", 6: "Sunday"}
SKIP_KEYWORDS = (
    "nco meeting",
    "poll",
    "strawpoll",
    "wargame",
    "editing meetup",
    "hangout",
)


def normalized_title(title: str) -> str:
    return " ".join(title.lower().split())


def is_in_scope_title(title: str) -> tuple[bool, str]:
    """Keep only Thursday Operation/Training titles and Sunday Operation titles."""
    lowered = normalized_title(title)

    if lowered.startswith("thursday"):
        if "operation" in lowered or "training" in lowered:
            return True, ""
        return False, "Thursday title lacks Operation/Training marker"

    if lowered.startswith("sunday"):
        if "operation" in lowered:
            return True, ""
        return False, "Sunday title lacks Operation marker"

    return False, "Title is outside strict Thursday/Sunday operation scope"


@dataclass
class SourceEvent:
    title: str
    source_date: str
    time: str
    description: str
    creator: str
    link: str


@dataclass
class ReviewRow:
    source_title: str
    source_date: str
    source_creator: str
    source_link: str
    source_description_preview: str
    proposed_mission_name: str
    proposed_event_type: str
    proposed_weekday_slot: str
    confidence: str
    rule_fired: str
    skip_reason_or_notes: str
    user_decision: str
    corrected_name: str


MISSION_NAME_RE = re.compile(
    r"^\s*(?:\*\*\s*)?Mission\s*Name\s*:?\s*(?:\*\*\s*)?(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MISSION_NAME_ANYWHERE_RE = re.compile(
    r"Mission\s*Name\s*:\s*([^\n\r]+)",
    re.IGNORECASE,
)
NAME_RE = re.compile(
    r"^\s*(?:\*\*\s*)?Name\s*:\s*(?:\*\*\s*)?(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MISSION_RE = re.compile(
    r"^\s*(?:\*\*\s*)?Mission\s*(?::|-)+\s*(?:\*\*\s*)?(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(https?://(?:discord(?:app)?\.com)/channels/[^\)]+\)", re.IGNORECASE)
MARKDOWN_EMOJI_RE = re.compile(r"!\[:[^\]]+\]\([^\)]+\)", re.IGNORECASE)
DISCORD_EMOJI_TAG_RE = re.compile(r"<a?:[^:>]+:\d+>", re.IGNORECASE)
DISCORD_URL_RE = re.compile(r"https?://(?:discord(?:app)?\.com)/channels/\d+/\d+/\d+", re.IGNORECASE)

CANCELLED_MARKERS = (
    "event cancelled",
    "cancelled",
)

NON_MISSION_HEADING_PREFIXES = (
    "terrain:",
    "created by:",
    "author:",
    "faction:",
    "enemy:",
    "composition:",
    "time:",
    "daytime:",
    "weather:",
    "weapons:",
    "logistics:",
    "day:",
    "session:",
    "required players:",
    "notes:",
    "situation report",
    "objectives",
    "operational threats",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Raid-Helper history helper")
    parser.add_argument("--mode", choices=["parse", "backup", "apply"], default="parse")
    parser.add_argument("--input", required=True, help="Path to Raid-Helper export CSV")
    parser.add_argument("--output", help="Path for generated review CSV")
    parser.add_argument("--human-output", help="Path for human-only review CSV (review rows only)")
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD)")
    return parser.parse_args()


def extract_blocks(raw_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_block = False

    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped == BLOCK_START:
            in_block = True
            current = []
            continue
        if stripped == BLOCK_END:
            if in_block and current:
                blocks.append("\n".join(current).strip())
            in_block = False
            current = []
            continue
        if in_block:
            current.append(line)

    return blocks


def parse_event_block(block: str) -> SourceEvent | None:
    reader = csv.reader(io.StringIO(block))
    rows = list(reader)
    if len(rows) < 2:
        return None

    header = [h.strip() for h in rows[0]]
    expected = ["Name", "Date", "Time", "Description", "Created by", "Link"]
    if len(header) < 6 or [h.lower() for h in header[:6]] != [e.lower() for e in expected]:
        return None

    values = rows[1]
    if len(values) < 6:
        values = values + [""] * (6 - len(values))

    return SourceEvent(
        title=values[0].strip(),
        source_date=values[1].strip(),
        time=values[2].strip(),
        description=values[3].strip(),
        creator=values[4].strip(),
        link=values[5].strip(),
    )


def extract_clickable_discord_url(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        match = DISCORD_URL_RE.search(text)
        if match:
            return match.group(0).replace("discordapp.com", "discord.com")
    return ""


def description_preview(description: str, max_len: int = 380) -> str:
    collapsed = " ".join(description.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 3] + "..."


def parse_source_date(raw_date: str) -> date | None:
    try:
        return datetime.strptime(raw_date, "%d-%m-%Y").date()
    except ValueError:
        return None


def is_non_operation_title(title: str) -> tuple[bool, str]:
    lowered = normalized_title(title)
    if lowered.startswith("tuesday"):
        return True, "Tuesday event is out of scope unless explicitly Thursday/Sunday operation"

    for keyword in SKIP_KEYWORDS:
        if keyword in lowered:
            return True, f"Title matched non-operation keyword: {keyword}"

    return False, ""


def extract_from_description(description: str) -> str:
    match = MISSION_NAME_RE.search(description)
    if match:
        return clean_candidate(match.group(1))

    anywhere_match = MISSION_NAME_ANYWHERE_RE.search(description)
    if anywhere_match:
        candidate = clean_candidate(anywhere_match.group(1))
        if candidate:
            return candidate

    name_match = NAME_RE.search(description)
    if name_match:
        candidate = clean_candidate(name_match.group(1))
        if candidate:
            return candidate

    legacy_match = MISSION_RE.search(description)
    if legacy_match:
        candidate = clean_candidate(legacy_match.group(1))
        if candidate:
            # Avoid false positives like "Mission settings will test:".
            lowered = candidate.lower()
            if not lowered.startswith("settings"):
                return candidate

    markdown_candidate = extract_from_markdown_link(description)
    if markdown_candidate:
        return markdown_candidate

    heading_candidate = extract_from_operation_heading(description)
    if heading_candidate:
        return heading_candidate

    terrain_candidate = extract_from_pre_terrain_heading(description)
    if terrain_candidate:
        return terrain_candidate

    return ""


def extract_from_title(title: str) -> str:
    lowered = title.lower().strip()
    if not (lowered.startswith("thursday") or lowered.startswith("sunday")):
        return ""

    if " - " not in title:
        return ""

    candidate = title.split(" - ")[-1].strip()
    candidate = re.sub(r"^dco(?:@\d+)?\s+", "", candidate, flags=re.IGNORECASE)
    return clean_candidate(candidate)


def clean_candidate(value: str) -> str:
    # Keep sequel markers; strip wrappers and accidental markdown/punctuation noise.
    value = MARKDOWN_EMOJI_RE.sub("", value)
    value = DISCORD_EMOJI_TAG_RE.sub("", value)
    value = value.strip().strip("*").strip()
    value = value.lstrip("#").strip()
    value = re.sub(r"^DCO(?:@\d+)?\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^Mission\s*[:\-]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+by\s+.+$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value


def contains_cancelled_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in CANCELLED_MARKERS)


def extract_from_markdown_link(description: str) -> str:
    for raw in MARKDOWN_LINK_RE.findall(description):
        candidate = clean_candidate(raw)
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in {"mission", "whiteboard_ca"}:
            continue
        return candidate
    return ""


def extract_from_operation_heading(description: str) -> str:
    for line in description.splitlines():
        cleaned = MARKDOWN_EMOJI_RE.sub("", line)
        cleaned = DISCORD_EMOJI_TAG_RE.sub("", cleaned)
        cleaned = cleaned.replace("*", "")
        cleaned = cleaned.lstrip("#").strip()
        if not cleaned:
            continue

        match = re.search(r"\bOperation\s+.+$", cleaned, flags=re.IGNORECASE)
        if match:
            return clean_candidate(match.group(0))

        mission_match = re.search(r"\bMission\s*[:\-]\s*.+$", cleaned, flags=re.IGNORECASE)
        if mission_match:
            return clean_candidate(mission_match.group(0))

        if line.lstrip().startswith("#"):
            lowered = cleaned.lower()
            if lowered and not lowered.startswith(NON_MISSION_HEADING_PREFIXES):
                if "http" not in lowered and len(cleaned) >= 4:
                    return clean_candidate(cleaned)
    return ""


def extract_from_pre_terrain_heading(description: str) -> str:
    """Use the nearest heading/text line before Terrain as a fallback mission name."""
    lines = description.splitlines()
    terrain_idx = -1
    for i, line in enumerate(lines):
        cleaned = clean_candidate(line)
        if cleaned.lower().startswith("terrain:"):
            terrain_idx = i
            break

    if terrain_idx <= 0:
        return ""

    skip_prefixes = (
        "training:",
        "session:",
        "day:",
        "time:",
        "daytime:",
        "weather:",
        "weapons:",
        "logistics:",
        "composition:",
        "faction:",
        "enemy:",
        "created by:",
        "author:",
        "briefing:",
        "notes:",
    )

    for j in range(terrain_idx - 1, max(-1, terrain_idx - 6), -1):
        raw = lines[j].strip()
        if not raw or raw == "-- start --" or raw == "-- end --":
            continue

        cleaned = clean_candidate(raw)
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if lowered.startswith(skip_prefixes):
            continue
        if lowered in {"mission", "training"}:
            continue
        if lowered.startswith("#"):
            cleaned = cleaned.lstrip("#").strip()
            lowered = cleaned.lower()
        if lowered.startswith("mission:"):
            cleaned = clean_candidate(cleaned)
            lowered = cleaned.lower()
        if lowered.startswith("operation ") or len(cleaned) >= 4:
            return cleaned

    return ""


def to_review_row(event: SourceEvent, today: date) -> ReviewRow:
    parsed_date = parse_source_date(event.source_date)
    clean_link = extract_clickable_discord_url(event.link, event.description)
    preview = description_preview(event.description)
    if not parsed_date:
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name="",
            proposed_event_type="",
            proposed_weekday_slot="",
            confidence="skip",
            rule_fired="date-parse",
            skip_reason_or_notes="Could not parse date with D-M-YYYY format",
            user_decision="",
            corrected_name="",
        )

    weekday_slot = WEEKDAY_SLOT.get(parsed_date.weekday(), "")
    is_past = parsed_date < today
    title_skip, title_skip_reason = is_non_operation_title(event.title)
    in_scope_title, out_of_scope_reason = is_in_scope_title(event.title)

    description_candidate = extract_from_description(event.description)
    title_candidate = extract_from_title(event.title)

    if not in_scope_title:
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name="",
            proposed_event_type="",
            proposed_weekday_slot=weekday_slot,
            confidence="skip",
            rule_fired="scope-filter",
            skip_reason_or_notes=out_of_scope_reason,
            user_decision="",
            corrected_name="",
        )

    if title_skip:
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name="",
            proposed_event_type="",
            proposed_weekday_slot=weekday_slot,
            confidence="skip",
            rule_fired="title-filter",
            skip_reason_or_notes=title_skip_reason,
            user_decision="",
            corrected_name="",
        )

    if not is_past:
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name=description_candidate or title_candidate,
            proposed_event_type="",
            proposed_weekday_slot=weekday_slot,
            confidence="skip",
            rule_fired="date-filter",
            skip_reason_or_notes="Date is not in the past",
            user_decision="",
            corrected_name="",
        )

    if not weekday_slot:
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name=description_candidate or title_candidate,
            proposed_event_type="",
            proposed_weekday_slot="",
            confidence="skip",
            rule_fired="weekday-filter",
            skip_reason_or_notes="Date is not Thursday or Sunday",
            user_decision="",
            corrected_name="",
        )

    if description_candidate:
        if contains_cancelled_marker(description_candidate):
            return ReviewRow(
                source_title=event.title,
                source_date=event.source_date,
                source_creator=event.creator,
                source_link=clean_link,
                source_description_preview=preview,
                proposed_mission_name="",
                proposed_event_type="",
                proposed_weekday_slot=weekday_slot,
                confidence="skip",
                rule_fired="cancelled-filter",
                skip_reason_or_notes="Extracted mission indicates cancelled event",
                user_decision="",
                corrected_name="",
            )
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name=description_candidate,
            proposed_event_type="Mission",
            proposed_weekday_slot=weekday_slot,
            confidence="high",
            rule_fired="description-mission-name",
            skip_reason_or_notes="Explicit Mission Name extracted from description",
            user_decision="approve",
            corrected_name="",
        )

    if title_candidate:
        if contains_cancelled_marker(title_candidate):
            return ReviewRow(
                source_title=event.title,
                source_date=event.source_date,
                source_creator=event.creator,
                source_link=clean_link,
                source_description_preview=preview,
                proposed_mission_name="",
                proposed_event_type="",
                proposed_weekday_slot=weekday_slot,
                confidence="skip",
                rule_fired="cancelled-filter",
                skip_reason_or_notes="Title candidate indicates cancelled event",
                user_decision="",
                corrected_name="",
            )
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=clean_link,
            source_description_preview=preview,
            proposed_mission_name=title_candidate,
            proposed_event_type="Mission",
            proposed_weekday_slot=weekday_slot,
            confidence="review",
            rule_fired="title-suffix",
            skip_reason_or_notes="Candidate extracted from title suffix after last ' - '",
            user_decision="",
            corrected_name="",
        )

    return ReviewRow(
        source_title=event.title,
        source_date=event.source_date,
        source_creator=event.creator,
        source_link=clean_link,
        source_description_preview=preview,
        proposed_mission_name="",
        proposed_event_type="",
        proposed_weekday_slot=weekday_slot,
        confidence="review",
        rule_fired="no-candidate",
        skip_reason_or_notes="No Mission Name line and no title suffix candidate",
        user_decision="",
        corrected_name="",
    )


def review_rows_from_events(events: Iterable[SourceEvent], today: date) -> list[ReviewRow]:
    rows = [to_review_row(event, today) for event in events]
    rows.sort(key=lambda r: (r.source_date, r.source_title.lower()))
    return rows


def filter_rows_for_clean_review(rows: Iterable[ReviewRow]) -> list[ReviewRow]:
    # Clean worklist: only in-scope rows that could become DB writes.
    return [row for row in rows if row.confidence != "skip"]


def filter_rows_for_human_review(rows: Iterable[ReviewRow]) -> list[ReviewRow]:
    # Human-eye pass should only include rows that still need a decision.
    return [row for row in rows if row.confidence == "review"]


def write_review_csv(output_path: Path, rows: list[ReviewRow]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_title",
        "source_date",
        "source_creator",
        "source_link",
        "source_description_preview",
        "proposed_mission_name",
        "proposed_event_type",
        "proposed_weekday_slot",
        "confidence",
        "rule_fired",
        "skip_reason_or_notes",
        "user_decision",
        "corrected_name",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("downloads") / f"raidhelper_review_{ts}.csv"


def default_human_output_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.stem + "_human_review.csv")


def run_parse_mode(input_path: Path, output_path: Path, human_output_path: Path, today: date) -> int:
    raw = input_path.read_text(encoding="utf-8")
    blocks = extract_blocks(raw)

    events: list[SourceEvent] = []
    for block in blocks:
        parsed = parse_event_block(block)
        if parsed:
            events.append(parsed)

    rows = review_rows_from_events(events, today)
    clean_rows = filter_rows_for_clean_review(rows)
    human_rows = filter_rows_for_human_review(clean_rows)
    write_review_csv(output_path, clean_rows)
    write_review_csv(human_output_path, human_rows)

    by_confidence: dict[str, int] = {"high": 0, "review": 0, "skip": 0}
    for row in rows:
        by_confidence[row.confidence] = by_confidence.get(row.confidence, 0) + 1

    print(f"Parsed blocks: {len(blocks)}")
    print(f"Parsed events: {len(events)}")
    print(f"Review rows written (clean, in-scope): {len(clean_rows)}")
    print(f"Human-review rows written: {len(human_rows)}")
    print(f"Discarded rows: {len(rows) - len(clean_rows)}")
    print(
        "Confidence counts: "
        f"high={by_confidence.get('high', 0)}, "
        f"review={by_confidence.get('review', 0)}, "
        f"skip={by_confidence.get('skip', 0)}"
    )
    print(f"Review CSV: {output_path}")
    print(f"Human review CSV: {human_output_path}")
    return 0


def main() -> int:
    args = parse_args()
    if args.mode != "parse":
        print(f"Mode '{args.mode}' is not implemented yet. Use --mode parse.")
        return 2

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else default_output_path()
    human_output_path = Path(args.human_output) if args.human_output else default_human_output_path(output_path)

    if args.today:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today = date.today()

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    return run_parse_mode(
        input_path=input_path,
        output_path=output_path,
        human_output_path=human_output_path,
        today=today,
    )


if __name__ == "__main__":
    raise SystemExit(main())
