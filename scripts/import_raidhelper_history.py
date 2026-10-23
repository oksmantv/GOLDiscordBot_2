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
MISSION_RE = re.compile(
    r"^\s*(?:\*\*\s*)?Mission\s*(?::|-)+\s*(?:\*\*\s*)?(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Raid-Helper history helper")
    parser.add_argument("--mode", choices=["parse", "backup", "apply"], default="parse")
    parser.add_argument("--input", required=True, help="Path to Raid-Helper export CSV")
    parser.add_argument("--output", help="Path for generated review CSV")
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

    legacy_match = MISSION_RE.search(description)
    if not legacy_match:
        return ""

    candidate = clean_candidate(legacy_match.group(1))
    if not candidate:
        return ""

    # Avoid false positives like "Mission settings will test:".
    lowered = candidate.lower()
    if lowered.startswith("settings"):
        return ""

    # Common old format: "Threading Needle by Oksman" -> keep mission name only.
    candidate = re.sub(r"\s+by\s+.+$", "", candidate, flags=re.IGNORECASE).strip()
    return candidate


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
    value = value.strip().strip("*").strip()
    value = re.sub(r"^DCO(?:@\d+)?\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value


def to_review_row(event: SourceEvent, today: date) -> ReviewRow:
    parsed_date = parse_source_date(event.source_date)
    if not parsed_date:
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=event.link,
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
            source_link=event.link,
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
            source_link=event.link,
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
            source_link=event.link,
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
            source_link=event.link,
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
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=event.link,
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
        return ReviewRow(
            source_title=event.title,
            source_date=event.source_date,
            source_creator=event.creator,
            source_link=event.link,
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
        source_link=event.link,
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


def write_review_csv(output_path: Path, rows: list[ReviewRow]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_title",
        "source_date",
        "source_creator",
        "source_link",
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


def run_parse_mode(input_path: Path, output_path: Path, today: date) -> int:
    raw = input_path.read_text(encoding="utf-8")
    blocks = extract_blocks(raw)

    events: list[SourceEvent] = []
    for block in blocks:
        parsed = parse_event_block(block)
        if parsed:
            events.append(parsed)

    rows = review_rows_from_events(events, today)
    clean_rows = filter_rows_for_clean_review(rows)
    write_review_csv(output_path, clean_rows)

    by_confidence: dict[str, int] = {"high": 0, "review": 0, "skip": 0}
    for row in rows:
        by_confidence[row.confidence] = by_confidence.get(row.confidence, 0) + 1

    print(f"Parsed blocks: {len(blocks)}")
    print(f"Parsed events: {len(events)}")
    print(f"Review rows written (clean, in-scope): {len(clean_rows)}")
    print(f"Discarded rows: {len(rows) - len(clean_rows)}")
    print(
        "Confidence counts: "
        f"high={by_confidence.get('high', 0)}, "
        f"review={by_confidence.get('review', 0)}, "
        f"skip={by_confidence.get('skip', 0)}"
    )
    print(f"Review CSV: {output_path}")
    return 0


def main() -> int:
    args = parse_args()
    if args.mode != "parse":
        print(f"Mode '{args.mode}' is not implemented yet. Use --mode parse.")
        return 2

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else default_output_path()

    if args.today:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today = date.today()

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    return run_parse_mode(input_path=input_path, output_path=output_path, today=today)


if __name__ == "__main__":
    raise SystemExit(main())
