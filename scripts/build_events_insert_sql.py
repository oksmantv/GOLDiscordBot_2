"""Build a conflict-safe SQL insert for missing events only."""

import csv
from pathlib import Path


def quote(value: str) -> str:
    return "'" + (value or "").replace("'", "''") + "'"


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "downloads" / "events_insert_missing_only.csv"
    output = root / "downloads" / "events_insert_missing_only.sql"
    rows = list(csv.DictReader(source.open(encoding="utf-8-sig", newline="")))

    values = [
        "  ({guild}, {date}::date, {event_type}, {name}, {creator_id}, {creator_name})".format(
            guild=row["guild_id"],
            date=quote(row["date"]),
            event_type=quote(row["type"]),
            name=quote(row["name"]),
            creator_id=int(row["creator_id"] or 0),
            creator_name=quote(row["creator_name"]),
        )
        for row in rows
    ]

    sql = "\n".join(
        [
            "-- Insert missing events only. Does NOT update existing rows.",
            "-- Unique key: (guild_id, date, type)",
            "-- Review the inserted count, then COMMIT or ROLLBACK.",
            "BEGIN;",
            "",
            "INSERT INTO events (guild_id, date, type, name, creator_id, creator_name)",
            "VALUES",
            ",\n".join(values),
            "ON CONFLICT (guild_id, date, type) DO NOTHING;",
            "",
            "-- If the insert count looks right, run: COMMIT;",
            "-- If not, run: ROLLBACK;",
            "",
        ]
    )
    output.write_text(sql, encoding="utf-8")
    print(f"rows={len(rows)}")
    print(f"wrote={output}")


if __name__ == "__main__":
    main()
