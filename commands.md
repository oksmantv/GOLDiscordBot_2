# GOL Discord Bot — Command Reference

## Introduction

The GOL Discord Bot is an all-in-one management tool for a military simulation (milsim) community Discord server. It automates the full lifecycle of weekly events — from scheduling and mission selection through attendance tracking to post-event feedback. The bot operates around a **Thursday/Sunday event schedule** and integrates with **Raid-Helper** for event sign-ups and attendance.

**Core capabilities:**

- **Schedule Management** — Maintains a persistent, auto-updating schedule embed that shows the next several weeks of Thursday training + mission nights and Sunday mission nights. Events are pre-populated and can be assigned mission names by editors.
- **Mission Polling** — Pulls mission briefings from a Discord forum channel, filters by framework and composition, de-duplicates against recently played missions, and creates Discord polls so the community can vote on the next mission. Polls are also created automatically on event nights.
- **Leave of Absence (LOA)** — Members can request leave with date ranges. The bot tracks active/planned LOAs, manages the `@Active` role automatically, posts announcements, and sends welcome-back DMs when leave expires.
- **Roster Management** — Automatically scans guild members, extracts ranks from roles, and maintains a formatted roster embed showing the full unit structure with rank hierarchy, subgroups, and LOA status.
- **Feedback Collection** — After each event, the bot automatically creates a feedback forum thread, mentions attendees (pulled from Raid-Helper sign-ups), and provides a structured template for training/editing/execution feedback.
- **Raid-Helper Integration** — Syncs mission briefing content to Raid-Helper events and reads sign-up data for feedback mentions.

**Event schedule (UK timezone):**

| Day | Time | Events |
|-----|------|--------|
| Thursday | 18:50 – 21:50 | Training + Mission |
| Sunday | 16:50 – 19:50 | Mission only |

---

## Command Overview

| Command | Parameters | Permission | Category |
|---------|-----------|------------|----------|
| `/ping` | — | Everyone | Diagnostic |
| `/schedule` | `event` · `name` · `author`? | Admin or @Editor | Schedule |
| `/clearschedule` | `event` | Admin or @Editor | Schedule |
| `/cancelscheduledevent` | `event` | Admin or @Editor | Schedule |
| `/populate` | `weeks` | Admin or @Editor | Schedule |
| `/configure` | `channel_id` · `message_id` · `briefing_channel_id` · `log_channel_id`? | Administrator | Setup |
| `/configureevents` | `events_channel_id` | Administrator | Setup |
| `/configurefeedback` | `feedback_channel_id` | Administrator | Setup |
| `/configureloa` | `channel` | Administrator | Setup |
| `/configureroster` | `channel` | Administrator | Setup |
| `/missionpoll` | `framework` · `event` · `duration`? · `options`? · `composition`? · `exclusion_weeks`? | Admin or @Editor | Mission Polls |
| `/cancelpoll` | `poll` | Admin or @Editor | Mission Polls |
| `/loa` | `start_date` · `end_date` · `reason`? | @Member | LOA |
| `/cancelloa` | `loa` | @Member | LOA |
| `/admincancelloa` | `user` · `loa` | Administrator or Moderate Members | LOA |
| `/updateroster` | — | Administrator | Roster |
| `/feedback` | `event_date`? · `force`? | Admin or @Editor | Feedback |
| `/updateevent` | `event_date` | Admin or @Editor | Raid-Helper |

---

## Command Details

---

### `/ping`

**Category:** Diagnostic
**Permission:** Everyone

**Parameters:** None

**What it does:**
Returns a "Pong! 🏓" response with the bot's current version string. Also silently refreshes the schedule embed message if one is configured, which makes it a quick way to force an embed update.

**Response:** Ephemeral (only visible to the caller).

---

### `/schedule`

**Category:** Schedule Management
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event` | string | ✅ | Select a scheduled event slot (autocomplete-enabled) |
| `name` | string | ✅ | Mission or training name to assign to the event |
| `author` | string | ❌ | Name of the event organizer. Defaults to the caller's display name |

**What it does:**
Assigns a name and creator to a specific event slot on the schedule. The `event` parameter uses Discord autocomplete — as you type, the bot searches events within ±1 year by partial date or name match.

**Logic:**
1. Looks up the selected event in the database.
2. Updates the event's `name`, `creator_id` (Discord user ID), and `creator_name`.
3. Refreshes the schedule embed so the change is immediately visible.

**Schedule embed behavior:** The schedule embed shows approximately 6 weeks of events (2 weeks back, 4 weeks forward). Named events display as a clickable link to the matching forum briefing thread (if one is found). The link matching uses a 9-level fuzzy matching strategy, from exact match down to 60% similarity threshold.

---

### `/clearschedule`

**Category:** Schedule Management
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event` | string | ✅ | Select a scheduled event slot (autocomplete-enabled) |

**What it does:**
Clears the name and organizer from an event slot, resetting it to an empty/unscheduled state.

**Logic:**
Sets `name=""`, `creator_id=0`, `creator_name=""` in the database and refreshes the schedule embed.

---

### `/cancelscheduledevent`

**Category:** Schedule Management
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event` | string | ✅ | Select a scheduled event slot (autocomplete-enabled) |

**What it does:**
Marks an event as cancelled. The event remains on the schedule but displays as "EVENT CANCELLED" instead of a mission name. This also prevents the automated feedback system from creating a feedback thread for that date.

**Logic:**
Sets `name="EVENT CANCELLED"`, `creator_id=0`, `creator_name=""`. Refreshes the schedule embed.

---

### `/populate`

**Category:** Schedule Management
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `weeks` | integer | ✅ | Number of weeks to pre-generate (1–52) |

**What it does:**
Pre-generates empty event slots for the specified number of weeks into the future. Events follow the fixed weekly pattern:

- **Every Thursday:** Creates a "Training" slot and a "Mission" slot.
- **Every Sunday:** Creates a "Mission" slot.

Existing events are skipped (not overwritten), so this is safe to run multiple times.

**Response:** Ephemeral summary showing created, skipped, failed, and total counts. Refreshes the schedule embed after completion.

**Background automation:** The bot also runs this automatically every 12 hours, maintaining an 8-week lookahead window so the schedule always has upcoming event slots.

---

### `/configure`

**Category:** Bot Setup
**Permission:** Administrator

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `channel_id` | string | ✅ | Text channel where the schedule embed will be posted (autocomplete: lists text channels) |
| `message_id` | string | ✅ | Existing message to use for the schedule embed, or `CREATE_NEW` to create a fresh one (autocomplete: shows first 5 messages in the selected channel) |
| `briefing_channel_id` | string | ✅ | Forum channel containing mission briefing threads (autocomplete: lists forum channels) |
| `log_channel_id` | string | ❌ | Fallback text channel for log messages and warnings |

**What it does:**
Sets up the core bot configuration: where to post the persistent schedule embed and which forum channel contains mission briefings. This is the first command to run when setting up the bot.

**Logic:**
1. Validates that `channel_id` points to a text channel and `briefing_channel_id` points to a forum channel.
2. If `message_id` is `CREATE_NEW`, posts a placeholder message in the target channel.
3. Stores the configuration in the `schedule_config` database table.
4. Refreshes the forum tag cache (used by mission polling for framework/composition filtering). The tag cache has a 24-hour TTL.
5. Refreshes the schedule embed.

**Prerequisite for:** `/missionpoll`, `/feedback`, auto-poll, auto-feedback, schedule embed updates.

---

### `/configureevents`

**Category:** Bot Setup
**Permission:** Administrator

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `events_channel_id` | string | ✅ | Text channel where Raid-Helper creates event posts (autocomplete: lists text channels) |

**What it does:**
Registers the channel where Raid-Helper posts event sign-up messages. This is needed for the auto-poll feature to post announcements and for Raid-Helper event syncing.

**Logic:**
Saves the `events_channel_id` in the `schedule_config` table.

---

### `/configurefeedback`

**Category:** Bot Setup
**Permission:** Administrator

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `feedback_channel_id` | string | ✅ | Forum channel where feedback threads will be created (autocomplete: lists forum channels) |

**What it does:**
Sets which forum channel the bot uses for automated and manual feedback thread creation.

**Prerequisite:** `/configure` must be run first (the `schedule_config` row must exist).

---

### `/configureloa`

**Category:** Bot Setup
**Permission:** Administrator

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `channel` | TextChannel | ✅ | Channel for LOA announcements and summary |

**What it does:**
Sets up the Leave of Absence system. When run, it performs a full reset of the LOA display:

1. Deletes any old LOA announcement messages from the previous channel (if reconfiguring).
2. Posts a new LOA summary embed in the target channel. This summary is automatically maintained and shows all active and planned LOAs.
3. Re-posts individual announcement embeds for all currently active LOAs.
4. Saves the configuration.

**LOA summary embed structure:**
- **Currently active LOAs** — LOAs where `start_date ≤ today` (max 30 entries displayed).
- **Planned LOAs** — LOAs where `start_date > today` (max 30 entries displayed).
- Includes a "How to Request Leave" guide at the bottom.

---

### `/configureroster`

**Category:** Bot Setup
**Permission:** Administrator

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `channel` | TextChannel | ✅ | Channel where roster embeds will be posted |

**What it does:**
Sets up the automated roster. Performs an initial full scan of all guild members with the `@Member` role, extracts their rank from Discord roles, determines subgroup membership, and posts a multi-embed roster display.

**Logic:**
1. Scans all guild members (excluding bots) who have the `@Member` role.
2. For each member, extracts rank from their Discord roles using a predefined rank hierarchy (12 ranks from 1st Lieutenant down to Recruit).
3. Determines subgroup membership (`Flying Hellfish` or `AAC`) from roles.
4. Checks `@Active` and `@Reserve` role status.
5. Cross-references active LOAs to show LOA indicators.
6. Removes old roster messages from the channel.
7. Posts 4 roster embeds and saves the configuration.

**Roster embed structure (4 embeds):**
1. Header with unit stats + Leadership (officers & NCOs)
2. Senior Enlisted
3. Enlisted
4. AAC + Reserves

Members on LOA appear with ~~strikethrough~~ and a `(LOA)` suffix. Names link to the GOL clan profile page. Members are sorted by rank (highest first).

---

### `/missionpoll`

**Category:** Mission Polling
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `framework` | string | ✅ | Framework version to filter briefings by (e.g., "Framework 3.0"). Autocomplete from forum tags |
| `event` | string | ✅ | Target event slot — must be an unscheduled (empty name) mission event. Autocomplete-enabled |
| `duration` | integer | ❌ | Poll duration in hours. Allowed values: 12, 24, 36, 48, 60, 72. Default: **36** |
| `options` | integer | ❌ | Number of missions to include in the poll. Range: 3–10. Default: **5** |
| `composition` | string | ❌ | Composition type filter (e.g., "Infantry", "Motorised"). Default: **"All"** (no filter). Autocomplete from forum tags |
| `exclusion_weeks` | integer | ❌ | How many weeks back to check for recently played missions to exclude. Allowed values: 2, 4, 6, 8. Default: **8** |

**What it does:**
Creates a Discord poll where members vote on which mission to play next. The bot automatically curates the mission list from the briefing forum channel.

**Full logic flow:**

1. **Validation:**
   - Rejects if the target event already has a name assigned (must be unscheduled).
   - Rejects if an active poll already exists for that event.

2. **Thread fetching:**
   - Retrieves all threads from the configured briefing forum channel.
   - Filters threads by the selected `framework` tag.
   - Optionally filters by the selected `composition` tag (if not "All").

3. **De-duplication:**
   - Looks back `exclusion_weeks` (default 8) in the events database.
   - Any mission name that was scheduled in that window is excluded from the poll options.
   - This prevents the same mission from being played repeatedly.

4. **Selection:**
   - If more missions pass the filter than the `options` count, a random subset is selected.
   - If **0 missions** pass the filter → sends a warning DM to the caller and logs to the log channel. No poll is created.
   - If **only 1 mission** passes → sends an error DM. No poll is created (not enough for a vote).

5. **Poll creation:**
   - Creates a Discord native poll (multi-select enabled) with mission names as answers.
   - Answer text includes the composition tag and is truncated to 55 characters if needed.
   - Posts a companion embed with clickable links to each mission's forum briefing thread.
   - Saves poll metadata (message IDs, end time, thread IDs, filters) to the database.
   - Poll end time = current time + `duration` hours.

6. **Confirmation:** Sends an ephemeral reply with poll details and any warnings.

**Autocomplete throttling:** Each autocomplete field has a 2-second per-user cooldown to prevent database spam during rapid typing. Cached tag lists are returned during the cooldown.

**Caching:**
- Event list cache: 30-second TTL.
- Briefing channel cache: 5-minute TTL.
- Forum tag cache: 24-hour TTL.

---

### `/cancelpoll`

**Category:** Mission Polling
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `poll` | string | ✅ | Active poll to cancel (autocomplete: lists all active polls with target event dates) |

**What it does:**
Cancels an active mission poll. Deletes the poll message and the companion links embed from Discord, then marks the poll as `failed` in the database.

---

### `/loa`

**Category:** Leave of Absence
**Permission:** `@Member` role required

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | string | ✅ | Leave start date in `DD-MM-YYYY` format |
| `end_date` | string | ✅ | Leave end date in `DD-MM-YYYY` format |
| `reason` | string | ❌ | Reason for the leave of absence |

**What it does:**
Requests a leave of absence. The bot tracks the leave period, manages roles automatically, and posts an announcement.

**Validation:**
- `start_date` must be today or in the future.
- `end_date` must be after `start_date`.
- The date range must not overlap with any existing active LOA for the same user.

**Logic:**
1. Creates an LOA record in the database.
2. Posts an announcement embed in the configured LOA channel showing the member, dates, and reason.
3. If the LOA starts today or earlier, immediately removes the `@Active` role from the member.
4. Updates the LOA summary message (adding the LOA to the active or planned section).

**Automated expiry handling (runs on bot startup):**
- When an LOA's `end_date` has passed, the bot:
  - Marks the LOA as expired in the database.
  - Deletes the announcement embed.
  - Restores the `@Active` role **only if** the member has no other active LOAs and still has the `@Member` role.
  - Sends a welcome-back DM with a green "🎉 Welcome Back!" embed, including a link to the next Raid-Helper event.

**Role management:**
- `@Active` role (ID: `898283677056925756`) — removed when LOA starts, restored when LOA expires.
- `@Member` role (ID: `437981035641176064`) — checked before restoring `@Active` (members who left the unit won't get `@Active` back).

---

### `/cancelloa`

**Category:** Leave of Absence
**Permission:** `@Member` role (own LOAs only)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `loa` | integer | ✅ | LOA ID to cancel (autocomplete: lists your active LOAs, max 25) |

**What it does:**
Cancels one of your own active LOAs early. The bot cleans up the announcement and restores your roles if appropriate.

**Logic:**
1. Marks the LOA as expired and notified in the database.
2. Deletes the LOA announcement embed from the LOA channel.
3. If the member has no other active LOAs, restores the `@Active` role.
4. Updates the LOA summary message.

---

### `/admincancelloa`

**Category:** Leave of Absence (Admin)
**Permission:** Administrator or Moderate Members permission

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user` | Member | ✅ | The member whose LOA to cancel |
| `loa` | integer | ✅ | LOA ID to cancel (autocomplete: lists active LOAs for the selected user) |

**What it does:**
Same as `/cancelloa` but allows administrators or moderators to cancel any member's LOA.

---

### `/updateroster`

**Category:** Roster Management
**Permission:** Administrator

**Parameters:** None

**What it does:**
Forces an immediate roster rescan and embed update. Useful after role changes, new members joining, or rank promotions.

**Logic:**
1. Scans all guild members with the `@Member` role.
2. Upserts each member's data (rank, active/reserve status, subgroup, LOA status).
3. Removes members from the database who no longer have the `@Member` role.
4. Regenerates and updates the 4 roster embeds.

**Response:** Summary showing total members, active duty, reserve counts, and any changes detected.

---

### `/feedback`

**Category:** Feedback
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_date` | string | ❌ | Event date in `DD-MM-YYYY` format. Defaults to today. Autocomplete shows event dates ±2 weeks |
| `force` | boolean | ❌ | Re-create the feedback thread even if one already exists for this date. Default: **False** |

**What it does:**
Manually creates a feedback forum thread for a specific event date.

**Validation:**
- The date must be a Thursday or Sunday (event days only).
- Unless `force=True`, rejects if a feedback thread already exists for that date.

**Logic:**
1. Looks up events for the given date, filters out cancelled events (`name = "EVENT CANCELLED"`).
2. Attempts to fetch attendees from Raid-Helper sign-ups for that date.
   - **Fallback:** If Raid-Helper data is unavailable, mentions the `@Leadership` role instead.
3. Creates a forum thread in the configured feedback channel.
4. Thread title format:
   - **Thursday:** `DD-MM-YYYY: Training Name + Mission Name`
   - **Sunday:** `DD-MM-YYYY: Mission Name`
   - **Fallback if unnamed:** `DD-MM-YYYY: Thursday Event` / `DD-MM-YYYY: Sunday Event`
5. Posts a structured template:
   - **Thursday template** has sections for Training, Editing, and Execution feedback.
   - **Sunday template** has sections for Editing and Execution feedback only.
6. Records the feedback post in the database to prevent duplicates.

**Automated feedback:** The bot automatically creates feedback threads after each event. It checks continuously and posts if all conditions are met:
- Today is an event day (Thursday or Sunday).
- Current time is within 1 hour after the event end time (Thursday: after 21:50 UK, Sunday: after 19:50 UK).
- No feedback thread exists yet for today's date.
- At least one non-cancelled event exists for today.

---

### `/updateevent`

**Category:** Raid-Helper Integration
**Permission:** Administrator or `@Editor` role

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_date` | string | ✅ | Event date in `DD-MM-YYYY` format |

**What it does:**
Syncs mission briefing content from a Discord forum thread to the corresponding Raid-Helper event.

**Logic:**
1. Finds the Raid-Helper event matching the given date.
2. Looks up the matching mission briefing thread in the forum channel.
3. Extracts the description and any image from the briefing post.
4. Updates the Raid-Helper event via the Raid-Helper API (PATCH request) with the extracted content.

**Requires:** A valid `RAID_HELPER_API_TOKEN` in the environment configuration.

---

## Background Tasks & Automation

The bot runs several automated background tasks that operate independently of user commands:

| Task | Interval | Trigger |
|------|----------|---------|
| Event population maintenance | Every 12 hours | Automatic — maintains 8-week event lookahead |
| Auto-poll | Every 1 minute (checks time) | Fires at **21:30 Swedish time** on Thursdays and Sundays only |
| Poll monitoring | Every 1 minute | Checks all active polls for expiry |
| Automated feedback | Continuous check | Posts within 1 hour after event end time |
| LOA expiry processing | On bot startup | Runs once per session; expires old LOAs, restores roles, sends DMs |
| Schedule embed refresh | On startup + after changes | Keeps the schedule message up to date |
| Roster refresh | On startup | Scans members and updates roster embeds |

### Auto-Poll Details

On **Thursdays at 21:30 Swedish time**, the bot automatically creates a mission poll targeting the **next Sunday** (today + 3 days). On **Sundays at 21:30**, it targets the **next Thursday** (today + 4 days).

Auto-poll configuration (hardcoded):
- **Framework filter:** "Framework 3.0"
- **Composition filter:** "All"
- **Duration:** 36 hours
- **Options:** 5 missions
- **Exclusion window:** 8 weeks

**Special auto-poll behavior:**
- **0 missions found:** Sends a warning to the log channel, skips poll creation.
- **1 mission found:** Skips the poll entirely and **auto-schedules** that mission directly — updates the event name, syncs to Raid-Helper, and posts an announcement.
- **2+ missions:** Creates a standard Discord poll with `@Active` role mention.

A deduplication set prevents the auto-poll from firing twice for the same (guild, event date) combination within one bot session.

### Poll Monitoring

When a poll's end time is reached:
1. Reads final vote counts from the Discord poll.
2. Determines the winner (highest votes). Ties and zero-vote polls are resolved by random selection.
3. Auto-schedules the winning mission (updates event name and creator).
4. Cleans up by deleting the poll message and links embed.
5. Syncs the mission briefing to Raid-Helper.
6. Updates the schedule embed and posts an announcement.
