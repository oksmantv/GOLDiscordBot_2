# Mission Selection and History — Agent Handoff Plan

Status: design locked 2026-10-23. Do not reopen the decisions below unless the user changes them.

This plan is for a later implementation agent. Delivery 1 is the Discord bot work. Delivery 2 is the historical CSV import. Do not mix them in one pull request.

---

## Locked decisions

| Topic | Decision |
|---|---|
| Work split | Two deliveries. Bot features first. CSV import second. |
| Unplayed missions | Same pool as played missions. Play count `0` ranks first. No reserved slots. |
| Day tags | Keep current day-priority fill. Play count ranks **inside** the priority pool, then inside the rest pool. |
| Tie-break | After day pool and play count: day tag, then random. See the exact order below. |
| Briefing age | Newer `thread.created_at` ranks ahead of older posts when the earlier keys tie. |
| What counts | Past `events` rows with `type = 'Mission'`, a real non-empty name, and `date < today`. |
| What does not count | Empty names, `EVENT CANCELLED` (case-insensitive, stripped), Training rows, future scheduled names, hangouts, polls, meetings. |
| Name matching | Fuzzy match against forum thread titles, with a review threshold. Do not silently accept medium matches into counts used by the poll. |
| Replay number | Show **total plays only**. Do not also show `plays - 1`. |
| `/missionplayedcount` | Public channel post. Admin or `@Editor` only. Same framework and composition filters as the poll. **No exclusion-weeks filter.** List every match, not a random subset. |
| Command columns | Link, play count, last played date, briefing post date, tags. Also list historical mission names that have no current forum thread. |
| CSV target | Only past Thursday and Sunday operations that yield a mission name. Skip polls, NCO meetings, hangouts, wargames, editing meetups. |
| CSV conflicts | Dry-run first. Later insert fills **empty names only**. Never overwrite an existing name. |
| Unsure CSV rows | Auto-extract a candidate. User must personally review rows that do not fit before anything is written. |
| Safety | Take a restorable table backup before any historical write. Do not publish low-confidence rows. |

### Ranking order for poll slots

Apply this after framework, composition, and exclusion-weeks filtering.

1. Split remaining threads into the **day-priority pool** and the **rest pool**, same as today (`Thursday` / `Sunday` tag).
2. Fill requested slots from the day-priority pool first.
3. Inside a pool, sort by play count ascending (`0` first).
4. Inside the same play count, prefer threads that also carry the target day tag. This only matters in the rest pool, because the priority pool already has the tag.
5. Inside that tie, prefer the **newer** briefing post (`thread.created_at` descending).
6. If still tied, shuffle those threads at random and take what is needed.
7. If the day-priority pool cannot fill every slot, repeat steps 3–6 on the rest pool for the remaining slots.

Manual `/missionpoll` and the auto-poll both use this order. The auto-poll keeps its current hardcoded filters: Framework 3.0, composition All, 5 options, 8-week exclusion, day tag derived from the target date.

`/missionlist` is unchanged. It stays a random backup list and still applies exclusion weeks.

---

## Current system the agent must not break

Relevant files:

- `commands/mission_poll_command.py` — `/missionpoll`, `/missionlist`, auto-poll, poll completion
- `services/mission_poll_service.py` — `filter_threads_by_tags`, `select_with_day_priority`, `get_excluded_thread_ids`
- `services/event_repository.py` — events CRUD, unique on `(guild_id, date, type)`
- `services/database_service.py` — `events` schema
- `models/event.py` — `id, guild_id, date, type, name, creator_id, creator_name`
- `docs/MISSION_POLL_DEEP_DIVE.md` and `commands.md` — must be updated when behavior changes

Current dedup is an exact, case-insensitive match of `thread.name` to `events.name` over the last N weeks, including today. That exclusion gate stays exact for Delivery 1. Fuzzy matching is for lifetime play counts and for the CSV review file, not for the 8-week exclusion gate, unless a later user request says otherwise.

Poll completion writes the winning **thread title** into `events.name`. New counts must therefore be able to match that stored title back to the same thread. Fuzzy matching exists because older Raid-Helper titles do not equal thread titles.

Discord limits:

- Poll answers stay within 55 characters. Do not add play counts to poll answer text.
- Embed descriptions are 4096 characters. A full mission list will need several embeds, or an attached file plus a short summary embed.

---

## Delivery 1 — Bot features

### Goal

Least-played eligible missions, especially never-played ones, should reach the poll before heavily replayed ones, without removing the Thursday/Sunday slot priority. Editors need a read-only command that shows the full play history for the current filter.

### 1. Play-count service

Add a small service, for example `services/mission_play_count_service.py`. Do not bury the matching rules inside the command file.

Inputs:

- `guild_id`
- current forum threads (already filtered by framework and composition when the caller wants that)
- optional: all historical event names, even if no thread exists

Data source:

```text
SELECT name, date
FROM events
WHERE guild_id = $1
  AND type = 'Mission'
  AND date < CURRENT_DATE
  AND btrim(name) <> ''
  AND upper(btrim(name)) <> 'EVENT CANCELLED'
```

Index `idx_events_guild_date` already exists. A new index is optional, not required for this table size.

Output per mission:

- `thread_id` or `None` if history-only
- display name
- `play_count`
- `last_played` date or `None`
- `posted_at` or `None`
- tags
- thread URL or `None`
- match method: `exact`, `normalized`, `fuzzy-accepted`, `unmatched-history`

### 2. Matching policy

Use three bands. Suggested starting thresholds, tunable after the CSV review, not during poll runtime:

| Band | Suggested score | Poll and command behavior |
|---|---|---|
| Exact | normalized titles equal | Count it. |
| High fuzzy | `>= 0.92` | Count it. Log the pair once at debug/info. |
| Medium fuzzy | `0.80` to `0.92` | Do **not** auto-count. Surface in logs and, for the command, mark the history row as unmatched rather than attaching it to the wrong thread. |
| Low | `< 0.80` | Ignore as a match. |

Normalization before fuzzy compare:

- casefold
- strip Discord rank emoji and extra whitespace
- strip a leading `Operation` / `Op`
- strip a leading event wrapper such as `Sunday Operation -` or `Thursday Training & Mission -` when comparing history titles
- remove punctuation except characters that distinguish a sequel (`II`, `2`)
- collapse whitespace

Do not treat `Hired Guns` and `Hired Guns II` as the same mission. Sequel markers must survive normalization.

Implementation note: stdlib `difflib.SequenceMatcher` is enough. Do not add a fuzzy dependency unless tests show it fails the sequel cases.

Cache the guild play-count map for the duration of one command or auto-poll run. Do not cache across hours. A poll completion changes the source data.

### 3. Replace random day-priority selection

Replace the shuffle-first body of `select_with_day_priority` with the locked order. Keep the same return shape: `(selected, excluded)`.

The function needs play counts and `created_at`, so change the signature rather than hiding lookups in a global. Suggested shape:

```text
select_poll_threads(threads, count, day_tag, play_counts) -> (selected, excluded)
```

`play_counts` is a dict of `thread.id -> int`. Missing id means `0`.

Auto-poll and manual poll both call this. If only one mission remains after exclusion, keep the current auto-schedule path. If zero remain, keep the current warning path.

DM text that currently says "Randomly selected" must say that selection preferred the day tag, then fewer total plays, then newer briefings, with random only for remaining ties.

### 4. `/missionplayedcount`

Add the command on the existing mission-poll cog.

Parameters:

- `framework` — required, same autocomplete as `/missionpoll`
- `composition` — default `All`, same autocomplete

No `exclusion_weeks`. No `options` cap. No `event` parameter.

Permission: admin or `@Editor`, same check as `/missionpoll`.

Behavior:

1. Defer, then fetch all briefing-forum threads.
2. Filter by framework and composition.
3. Attach play counts with the matching policy above.
4. Also collect past Mission names that did not match any filtered thread. Show those in a separate "No current briefing" section. They are informational and are not poll candidates.
5. Sort thread rows by play count ascending, then `created_at` descending, then name.
6. Post in the channel where the command was used. Ephemeral reply only confirms that the public post was sent.
7. Each thread row includes a briefing link, total plays, last played date (`Never` if zero), post date, and tags.
8. If the list exceeds one embed, send follow-up embeds in the same channel. Cap page size so a description stays under 4096 characters. If even that is too large, attach a `.txt` or `.csv` and keep the embeds as a summary plus the first page. Prefer embeds first.

Footer example: `Framework 3.0 • Composition: All • Exclusion weeks not applied • N briefings • M history-only names`.

Update `commands.md` and `docs/MISSION_POLL_DEEP_DIVE.md`.

### 5. Tests for Delivery 1

Add unit tests around the selector and matcher. No Discord connection required.

Cover at least:

- Unplayed (`0`) is chosen before a mission with plays, inside the same day pool.
- A Thursday-tagged mission with many plays still fills a Thursday slot before an untagged never-played mission.
- Equal play count plus equal day relation prefers the newer `created_at`.
- Equal on all stable keys is not a fixed order.
- `EVENT CANCELLED`, blank names, Training rows, and future dates do not increment counts.
- `Hired Guns` does not absorb `Hired Guns II`.
- Medium fuzzy score does not attach a history row to a thread.
- Exclusion-weeks behavior of `get_excluded_thread_ids` stays exact-match and is not replaced by this matcher.

### 6. Delivery 1 done when

- Manual and auto polls use the new order.
- `/missionplayedcount` posts the full filtered list plus unmatched history names.
- Docs match the new behavior.
- Existing poll completion, Raid-Helper update, and `/missionlist` still behave as before.

---

## Delivery 2 — Historical CSV import

Do not start this until Delivery 1 is merged or the user explicitly says to start. The bot can ship with only the play history already in Postgres. Counts will be short until this import is reviewed and applied.

Source file: `c:\Users\aleok\Downloads\437979456196444161.csv`

Observed shape:

- Header says 743 events, export created 2026-10-23.
- Records are separated by `-- start --` / `-- end --`.
- Each record has a metadata line: `Name,Date,Time,Description,Created by,Link`.
- Description is a quoted multiline field. Dates look like `D-M-YYYY` (example `11-7-2021`).
- After the metadata line, sign-up rows follow. Ignore sign-ups for this import.
- Many early descriptions have **no** `Mission Name:` line. The mission is embedded in the Raid-Helper title, for example `Tuesday Hangout - DCO@17 Instant Penalty` or `Sunday Operation - DCO Pulau Raid`.
- Later descriptions use `Mission Name:`, `**Mission Name:**`, and similar. Creator lines vary the same way.
- Some titles are not operations: `NCO Meeting`, `Poll`, `Strawpoll`, `Wargame Monday`, `Editing Meetup`, `Saturday Hangout`.

### 1. Script boundary

Build a standalone script, for example `scripts/import_raidhelper_history.py`. It must not run on bot startup.

Modes:

1. `parse` — read the CSV, write a review workbook or CSV. No database connection required.
2. `backup` — dump the live `events` table for this guild to a timestamped SQL or CSV file under a local backup folder that is gitignored.
3. `apply` — only after the user has produced an approved review file. Fills empty Mission names. Refuses to run if the approved file is missing, if backup fails, or if any approved row would overwrite a non-empty name.

### 2. Review file

One row per CSV event that might be an operation. Columns:

- source title
- source date
- source creator
- source link
- proposed mission name
- proposed event type (`Mission` only for apply)
- proposed weekday slot (`Thursday` or `Sunday`)
- confidence: `high`, `review`, `skip`
- skip reason or match notes
- user decision column, default blank: `approve`, `edit`, `skip`

Parser may pre-fill `approve` only for high-confidence explicit `Mission Name:` extractions on a Thursday or Sunday. Everything else stays `review` with a candidate filled in, including title-only extractions such as `Pulau Raid`.

The user will personally check rows that do not fit. The apply mode reads only rows whose decision is `approve`, or `edit` plus a non-empty corrected name column. Blank decisions are skips.

### 3. Extraction rules for the candidate

Try in order, and record which rule fired:

1. Explicit `Mission Name:` line, with or without markdown bold.
2. If the title matches `Thursday ...` or `Sunday ...` and contains ` - `, take the segment after the last ` - `, then strip a leading `DCO` / `DCO@17` token.
3. Otherwise mark `review` or `skip`. Do not guess from the first line of a freeform description.

Skip even if a mission-like string exists when the title clearly matches:

- NCO Meeting
- Poll / Strawpoll
- Wargame
- Editing Meetup
- Hangout
- Tuesday events that are not Thursday/Sunday operations

Thursday training titles may contain both a training subject and a mission. For this import, store only the mission name on the `Mission` row. Do not invent a Training name unless it is explicit and the user later asks for that. Delivery 2 does not need Training rows for play counts.

Date rule: `D-M-YYYY` with no zero padding. Store as a real date. Only propose a row when that date is a Thursday or Sunday and is before today.

Creator: store the CSV creator display name. `creator_id` stays `0` because the CSV creator field is not a reliable Discord id for the briefing author. Sign-up ids belong to attendees, not authors.

### 4. Database safety

Before `apply`:

1. Run `backup`.
2. Verify the backup file exists and the row count matches `SELECT count(*) FROM events WHERE guild_id = $guild`.
3. Open a transaction.
4. For each approved row, `INSERT` a Mission event only when no `(guild_id, date, 'Mission')` row exists.
5. If the row exists and `btrim(name) = ''`, `UPDATE` the name and creator name.
6. If the row exists and the name is already non-empty, skip and record it. Do not overwrite. This includes `EVENT CANCELLED`.
7. Commit only if every planned write matched its pre-check. On any unexpected conflict, roll back and leave the backup untouched.

Do not use `ON CONFLICT DO UPDATE`. The unique key is `(guild_id, date, type)`, so an update-on-conflict would be able to destroy a good name.

Do not delete or rebuild the `events` table.

Guild id comes from `GUILD_ID` in the environment, the same value `config/settings.py` uses. Do not hardcode it.

### 5. Apply report

Write a second file next to the backup:

- inserted
- empty names filled
- skipped because a name already existed
- skipped because the review decision was not approve/edit
- skipped because the date was not a past Thursday or Sunday

The user reviews that report before treating play counts as historically complete.

### 6. Delivery 2 done when

- A review file exists and the user has marked decisions.
- A verified `events` backup exists from immediately before apply.
- Apply filled only empty past Mission names and inserted missing past Thursday/Sunday Mission rows.
- A rerun of apply changes nothing.
- `/missionplayedcount` reflects the imported names, with unmatched history still listed separately when no briefing thread fits.

---

## Out of scope

- Changing `/missionlist` into a play-count view. That is the new command.
- Showing play counts inside the 55-character poll answers.
- Counting future scheduled missions as already played.
- Importing sign-ups, attendance, or Raid-Helper message ids into new tables.
- Overwriting live schedule names from the CSV.
- Auto-applying medium fuzzy matches.

## Suggested implementation order inside Delivery 1

1. Matcher and play-count query, with tests.
2. Selector change, with tests.
3. Wire manual poll and auto-poll.
4. Add `/missionplayedcount`.
5. Update `commands.md` and `docs/MISSION_POLL_DEEP_DIVE.md`.
