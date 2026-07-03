# Mission Poll System — Deep Dive

This document describes the end-to-end lifecycle of mission polls: how they are created, how missions are selected (including day-priority), how votes are resolved, and how the result is applied to the schedule.

---

## 1. What a Mission Poll Is

A mission poll is a **Discord native poll** sent to a channel, allowing server members to vote on which briefing thread should be scheduled as the next mission event.

Each poll is tied to a single unassigned `Mission` event in the database. When the poll ends, the winning thread's name is written back to that event as its mission name, the schedule embed is refreshed, and the Raid-Helper event description is updated.

---

## 2. Database Schema (`mission_polls`)

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `guild_id` | BIGINT | |
| `poll_message_id` | BIGINT | Discord message ID of the poll |
| `channel_id` | BIGINT | Channel the poll was sent to |
| `target_event_id` | BIGINT | FK → `events.id` |
| `framework_filter` | VARCHAR | Framework tag used when filtering |
| `composition_filter` | VARCHAR | Composition tag used (or "All") |
| `mission_thread_ids` | JSONB | Array of forum thread IDs in poll order |
| `poll_end_time` | TIMESTAMPTZ | When the poll expires |
| `status` | VARCHAR | `active` / `completed` / `failed` |
| `winning_thread_id` | BIGINT | Set on completion |
| `created_by` | BIGINT | Discord user ID |
| `created_at` | TIMESTAMPTZ | |
| `links_message_id` | BIGINT | Discord message ID of the briefings embed |

**Indexes:** `(guild_id, status)`, `poll_end_time`

---

## 3. Commands

### `/missionpoll` (admin or @Editor)

Manually creates a poll.

| Parameter | Default | Notes |
|---|---|---|
| `framework` | — (required) | Autocomplete from forum tag cache |
| `event` | — (required) | Autocomplete: unassigned Mission events, 2-week lookahead |
| `duration` | 36 h | Choices: 12 / 24 / 36 / 48 / 60 / 72 |
| `options` | 5 | Range 3–10 |
| `composition` | All | Autocomplete from forum tag cache |
| `exclusion_weeks` | 8 | Choices: 2 / 4 / 6 / 8 |
| `day` | Auto | See §5 — Day-Priority Selection |

### `/missionlist` (admin or @Editor)

Same filtering/deduplication logic as `/missionpoll`, but posts a numbered embed instead of a live poll. Maximum 15 missions. Day-priority is not applied (fully random).

### `/completepoll` (admin or @Editor)

Manual completion fallback for `active` or `failed` polls. Useful when auto-completion fails (e.g. the poll message was deleted). Autocomplete shows status badges: 🟢 active, ⚠️ failed.

---

## 4. Filtering Pipeline

```
All Forum Threads (active + archived, deduped by thread ID)
         │
         ▼
[Framework tag filter]  ← REQUIRED, case-insensitive
         │
         ▼
[Composition tag filter]  ← Skipped if "All"
         │
         ▼
Filtered threads
         │
         ▼
[Deduplication]  ← Exclude threads matching event names from the past N weeks
         │
         ▼
Remaining threads
         │
         ▼
[Validate count ≥ 2]  ← Send DM on failure
         │
         ▼
[Day-priority selection]  ← See §5
         │
         ▼
Final poll options
```

### Tag Categories

Forum tags are split into two categories using a regex match against `^Framework\s+\d+\.\d+$` (case-insensitive):

- **Framework tags** — e.g. "Framework 3.0", "Framework 2.0"
- **Composition tags** — everything else (Infantry, Motorised, Mechanized, Air Assault, Amphibious, Armored, Battlebus, Special Forces)
- **Day tags** — "Thursday", "Sunday" — used for day-priority selection (see §5)

### Deduplication

`get_excluded_thread_ids()` looks back N weeks (default 8) in the guild's `events` table. Any event with a non-empty `name` in that window is considered "recently played". Threads whose title matches a recent event name (case-insensitive exact match) are excluded from the pool.

---

## 5. Day-Priority Selection

`select_with_day_priority(threads, count, day_tag)` is called after deduplication whenever the pool is larger than the requested option count.

### How it works

1. Threads are partitioned into two groups:
   - **Priority pool** — threads whose tag list contains `day_tag` (case-insensitive)
   - **Rest pool** — all other threads
2. Both pools are independently shuffled.
3. Slots are filled from the priority pool first (up to `count`).
4. Any remaining slots are filled from the rest pool.

```
Example — 5 options requested, day_tag = "Thursday":

Priority pool (Thursday-tagged): [M1, M2, M3]   → fills 3 slots
Rest pool (untagged/other-day):  [M4, M5, M6, M7] → fills 2 slots

Result: [M1, M2, M3, M4, M5]
```

If fewer than `count` threads carry the day tag, the fallback is seamless — the rest pool fills the gap. No error is raised. If no threads have the day tag at all, the result is identical to a uniform random shuffle.

### For `/missionpoll`

The `day` parameter controls `effective_day`:

| `day` value | Behaviour |
|---|---|
| Not set (default) | Auto-derived from event date: Thursday event → `"Thursday"`, Sunday event → `"Sunday"`, other → `None` |
| `"Thursday"` | Force Thursday-priority regardless of event date |
| `"Sunday"` | Force Sunday-priority regardless of event date |
| `"None"` | Disable day-priority entirely; uniform random selection |

The user is notified via DM when random selection is applied, including a note about which day was prioritised.

### For auto-polls

The auto-poll always derives `day_tag` from the **target** event's weekday:
- Thursday target → `day_tag = "Thursday"`
- Sunday target → `day_tag = "Sunday"`

This is automatic and requires no configuration.

---

## 6. Auto-Poll Schedule

Background task `_auto_poll_loop` runs every 1 minute and fires at **21:00 Swedish time** on:

| Trigger day | Target event | Day-priority tag |
|---|---|---|
| Thursday 21:00 | Next Sunday (+3 days) | `"Sunday"` |
| Sunday 21:00 | Next Thursday (+4 days) | `"Thursday"` |

**Auto-poll settings (hardcoded):**
- Framework: `Framework 3.0`
- Composition: `All`
- Duration: 36 hours
- Options: 5
- Exclusion: 8 weeks

**Special case — 1 mission found:** If only one eligible mission remains after filtering, a poll is skipped and the mission is auto-scheduled directly (no vote needed). The Raid-Helper event is updated immediately.

**Special case — 0 missions found:** A warning is logged and a message is sent to the log channel. No poll is created.

---

## 7. Poll Completion

Background task `_poll_monitor_loop` runs every 1 minute. When a poll's `poll_end_time ≤ now`:

1. Reads Discord poll message — tallies votes per answer index.
2. **Winner determination:**
   - Zero votes → random pick from all options
   - Tied highest votes → random pick among tied options
   - Clear leader → that option wins
3. Fetches the winning forum thread → `extract_author_from_thread()` parses author name from the opening post (falls back to thread owner).
4. Updates the `events` row: `name = mission_name`, `creator_name = author_name`.
5. Deletes poll message and links embed from Discord.
6. Updates the Raid-Helper event description with briefing content.
7. Refreshes the schedule embed.
8. Sends announcement to log channel / DM to poll creator.
9. Marks poll `completed` in DB.

**Failure paths:**
- Poll message deleted before expiry → mark `failed`, DM creator.
- Winning thread deleted → mark `failed`, DM creator.
- Event already assigned by the time the poll ends → mark `completed` without rescheduling, log warning.

---

## 8. In-Memory State

The cog maintains several in-memory registries to avoid redundant DB queries and prevent duplicate fires:

| Field | Purpose |
|---|---|
| `_active_poll_end_times` | `{poll_id: end_time}` — fast check for ended polls without DB query |
| `_auto_poll_fired` | `{(guild_id, date)}` — prevents duplicate auto-polls in the same minute |
| `_rh_init_update_fired` | `{(guild_id, date)}` — prevents duplicate RH init updates |
| `_briefing_cache` | 5-minute TTL per guild for `briefing_channel_id` |
| `_event_cache` | 30-second TTL per guild for unassigned event list |
| `_autocomplete_timestamps` | 2-second per-user debounce on autocomplete DB queries |

The `_active_poll_end_times` registry is rebuilt from the DB on `cog_load` to survive bot restarts.

---

## 9. Poll Answer Formatting

Discord caps poll answers at 55 characters. `format_poll_answer()` applies a progressive strategy:

1. Full mission name + full composition tag names (e.g. `Op Ironclad [Infantry]`)
2. "Operation" → "Op" shortening
3. Abbreviated composition tags (Infantry → INF, Motorised → MOTO, etc.)
4. Truncate mission name with `…` + abbreviated tags

---

## 10. Briefing Link Matching (Links Embed)

Alongside the poll, a **briefings embed** is posted with clickable links to each thread. Thread URLs are constructed as `https://discord.com/channels/{guild_id}/{thread_id}`.

The same threads that appear in the poll are shown in the links embed in the same order, allowing voters to read the briefing before voting.
