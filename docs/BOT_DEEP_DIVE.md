# GOLDiscordBot_2 deep dive (architecture + runtime notes)

This document is a “memory” for how this bot works end-to-end: entrypoints, DB schema, event population, commands, and the schedule embed.

## 1) What this bot is

- A **single-guild** Discord bot (hard-pinned to `Config.GUILD_ID`) using **discord.py** application (slash) commands.
- Stores schedule data in a **PostgreSQL** database (NeonDB) via **asyncpg**.
- Maintains a pool of weekly recurring events (Training + Mission on Thursdays; Mission on Sundays) that users can update with `/schedule`.
- Optionally maintains a “schedule message” in a channel (configured via `/configure`) that is edited with an embed representing the schedule.

Key modules:
- Startup + lifecycle: `start.py`, `bot.py`
- Slash commands: `commands/` (`schedule_commands.py`, `configure_command.py`, `ping_command.py`)
- DB + domain logic: `services/` + `models/event.py`

## 2) Entrypoints & lifecycle

### 2.1 Entrypoint

- `start.py` runs `asyncio.run(main())` from `bot.py`.

### 2.2 Startup flow (`GOLBot.setup_hook`)

In order:

1. `Config.validate_config()`
   - Requires env vars: `DISCORD_BOT_TOKEN`, `GUILD_ID`, `NEONDB_CONNECTION_STRING`.

2. `db_connection.create_pool()`
   - Creates an asyncpg pool.

3. `initialize_database()`
   - Ensures DB schema exists (see “Database schema”).

4. `event_population_service.populate_8_week_range()`
   - Populates weekly events for **4 weeks past + 4 weeks future** around “today”.

5. Loads command cogs:
   - `commands.schedule_commands`
   - `commands.ping_command`
   - `commands.configure_command`

6. Clears global commands and syncs guild commands.

### 2.3 Ready flow (`GOLBot.on_ready`)

- Sets presence status (“watching the schedule 📅”).
- Calls `update_schedule_message_on_startup()`:
  - Looks up `schedule_config` for each connected guild.
  - If configured, fetches the configured message and edits it with a newly-built schedule embed.

### 2.4 Background maintenance (events)

The bot maintains a rolling window of events.

- `services/event_population_service.py` contains `maintain_event_population()`.
- `bot.py` runs a background loop every 12 hours:
  - Checks whether events exist on the date `today + 4 weeks`.
  - If not, repopulates the 8-week range centered on today.
  - If it created new events, it also refreshes the schedule message embed.

This prevents the “ran out of events” failure mode where the bot only populated once at startup.

## 3) Database schema & data model

### 3.1 `events` table

Created/ensured by `services/database_service.py`.

Purpose: stores editable schedule entries.

Columns:
- `id SERIAL PRIMARY KEY`
- `guild_id BIGINT NOT NULL`
- `date DATE NOT NULL`
- `type VARCHAR(50) NOT NULL` (currently `Training` or `Mission`)
- `name VARCHAR(255) DEFAULT ''` (free-text details)
- `creator_id BIGINT DEFAULT 0`
- `creator_name VARCHAR(100) DEFAULT ''`

Constraints:
- `UNIQUE(guild_id, date, type)` prevents duplicates.

Index:
- `idx_events_guild_date` on `(guild_id, date)`.

### 3.2 `schedule_config` table

Ensured by `services/database_service.py`.

Purpose: stores where the “schedule embed message” lives, plus the forum channel used for briefing-link lookup.

Columns:
- `guild_id BIGINT PRIMARY KEY`
- `channel_id BIGINT NOT NULL`
- `message_id BIGINT NOT NULL`
- `briefing_channel_id BIGINT` (nullable)

Notes:
- The bot expects this table and column to exist; without it, `/configure` and schedule-embed building can fail.

### 3.3 Model

- `models/event.py` defines the `Event` dataclass and `from_db_row` mapping.
- CRUD is in `services/event_repository.py`.

## 4) Commands & user workflows

### 4.1 `/configure` (admin-only)

File: `commands/configure_command.py`

Goal: configure *where* the schedule embed should be posted/updated.

Inputs (via autocomplete):
- `channel_id`: a text channel
- `message_id`: either select one of the oldest messages from that channel or choose “CREATE_NEW”
- `briefing_channel_id`: a **forum** channel (used to match mission names to briefing threads)

Effects:
- Writes/updates a row in `schedule_config` via `schedule_config_repository.set_config()`.

Important behavior:
- The schedule message embed is refreshed on bot startup (`on_ready`) and after `/schedule` updates.

### 4.2 `/schedule` (admin or @Editor role)

File: `commands/schedule_commands.py`

Goal: update an existing event’s editable fields.

Inputs:
- `event`: string value chosen from autocomplete (formatted text)
- `name`: new description
- `author`: optional organizer display name (defaults to invoker’s display name)

Effects:
- Updates `events.name`, `events.creator_id`, `events.creator_name` for the selected event.
- If `schedule_config` is present, refreshes the configured schedule message embed.

Autocomplete behavior:
- Uses `services/date_filter_service.py`.
- Default: shows events for the sliding 8-week window.
- If user types text, it searches ±1 year worth of events and filters by substring match of the formatted string.

### 4.3 `/ping`

File: `commands/ping_command.py`

- Returns version.
- Also attempts to refresh the schedule embed (if configured).

### 4.4 `/populate` (admin or @Editor role)

File: `commands/populate_command.py`

Goal: manually generate upcoming events to ensure the schedule doesn’t “run out”.

Inputs:
- `weeks` (1–52): how many weeks ahead to generate

Behavior:
- Populates events for `today → today + weeks`.
- Ensures the standard pattern (Thu Training + Thu Mission + Sun Mission) within the range.
- Safe to run repeatedly (duplicates are skipped due to the DB unique constraint).
- Attempts to refresh the configured schedule message embed after population.

## 5) Schedule embed generation

File: `services/schedule_embed_service.py`

`build_schedule_embed(guild)`:
- Queries events for a window of `today - 2 weeks` through `today + 4 weeks`.
- Groups events by week and emits a week field per ISO week.
- Highlights “current week” events with a custom cutoff: **Sunday 20:00 UTC**.

Briefing-link matching:
- If `briefing_channel_id` is configured and an event has a name, the bot attempts to find a matching forum thread title.
- Matching uses multiple strategies (exact, normalized, substring, keyword overlap, fuzzy matching).
- Each matching attempt is time-limited to **5 seconds** per event to avoid hanging embed generation.

## 6) Why “we ran out of events” happens

The underlying mechanics:

- Events are not generated on-demand when users open the `/schedule` dropdown.
- If the bot only ever calls `populate_8_week_range()` once (on startup), then after enough real time passes, the DB will no longer contain events for “today + future weeks”.
- `date_filter_service.get_available_events()` uses a sliding date window relative to *today*, so it will return an empty list once the DB no longer covers that range.

Mitigation:
- Call `maintain_event_population()` periodically.
- This repo now does that with a background loop (every 12 hours) inside `GOLBot`.

## 7) Known sharp edges / extension points

- **Single guild assumption**:
  - Many services used to reference `Config.GUILD_ID` directly.
  - The embed builder now uses `guild.id` for queries/config lookup, but the broader codebase still assumes one guild.

- **Old/unused code**:
  - `services/schedule_update_service.py` is a legacy approach (in-memory config) and is not referenced by the running bot.

- **DB migrations**:
  - There is no migration runner; schema is effectively managed by `initialize_database()`.
  - Keep `services/database_service.py` in sync with any new schema needs.

## 8) Quick troubleshooting checklist

- No events appear in `/schedule` autocomplete:
  - Check bot logs for event population summary.
  - Confirm DB connectivity (`NEONDB_CONNECTION_STRING`).
  - Verify events exist in DB for upcoming weeks.

- Schedule message not updating:
  - Run `/configure` as admin.
  - Verify the bot can fetch and edit the target message.
  - Ensure `schedule_config` row exists for the guild.

- Briefing links not appearing:
  - Confirm `briefing_channel_id` points to a forum channel.
  - Ensure the mission name in the schedule resembles the forum thread title.
  - Check logs for `[BRIEFING LINK]` / timeout warnings.
