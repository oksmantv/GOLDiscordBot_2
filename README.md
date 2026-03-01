# GOL Discord Bot (Guerrillas of Liberation)

A Discord bot for managing weekly training and mission schedules, mission polls, leave of absence tracking, and a live platoon roster for the GOL community. Backed by NeonDB (PostgreSQL).

## Features

- **Schedule Management**: 8-week rolling schedule (4 past, 4 future) with auto-populated Training (Thu) and Mission (Thu & Sun) events
- **Auto-Updating Schedule Embed**: A persistent embed message that refreshes hourly and on every change
- **Mission Polls**: Create polls from forum briefings, auto-schedule winners, with framework/composition filtering and deduplication
- **Leave of Absence (LOA)**: Members can request LOA with start/end dates; expired LOAs are auto-cleared on startup and via a background loop
- **Platoon Roster**: Live 4-embed roster showing Leadership, Senior Enlisted, Enlisted (Flying Hellfish), AAC, and Reserves — with rank emojis, LOA indicators, and hourly auto-refresh
- **Slash Commands**: Full Discord application commands with autocomplete dropdowns
- **Clean Architecture**: Cog-based commands, service layer, repository pattern, async throughout

## Project Structure

```
GOLDiscordBot_2/
├── start.py                              # Entry point
├── bot.py                                # Main bot class, startup logic, cog loading
├── requirements.txt                      # Python dependencies
├── cleanup_commands.py                   # Utility to clean stale commands
├── force_register_commands.py            # Utility to force-sync commands
├── config/
│   ├── __init__.py
│   └── settings.py                       # Configuration from env vars
├── models/
│   ├── __init__.py
│   └── event.py                          # Event data model
├── commands/
│   ├── __init__.py
│   ├── schedule_commands.py              # /schedule slash command
│   ├── configure_command.py              # /configure (set channels)
│   ├── populate_command.py               # /populate (force event creation)
│   ├── ping_command.py                   # /ping (health check)
│   ├── mission_poll_command.py           # /missionpoll + poll monitor loop
│   ├── cancel_poll_command.py            # /cancelpoll
│   ├── loa_command.py                    # /loa + expiry background loop
│   ├── roster_command.py                 # /configureroster, /updateroster + hourly loop
│   └── minimal_configure_cog.py          # Lightweight configure fallback
├── services/
│   ├── __init__.py
│   ├── database_connection.py            # NeonDB asyncpg connection pool
│   ├── database_service.py              # Table creation & migrations
│   ├── event_repository.py               # Event CRUD
│   ├── event_population_service.py       # Auto-populate weekly events
│   ├── date_filter_service.py            # Date parsing & filtering
│   ├── schedule_config_repository.py     # Schedule channel/message config
│   ├── schedule_embed_service.py         # Build the schedule embed
│   ├── schedule_update_service.py        # Update the schedule embed message
│   ├── forum_tag_service.py              # Forum tag caching for polls
│   ├── mission_poll_repository.py        # Poll CRUD
│   ├── mission_poll_service.py           # Poll helpers (filtering, formatting)
│   ├── loa_repository.py                 # LOA CRUD
│   ├── loa_config_repository.py          # LOA channel/message config
│   ├── loa_service.py                    # LOA embed builder & message updater
│   ├── roster_repository.py              # Roster member CRUD
│   ├── roster_config_repository.py       # Roster channel/message config
│   └── roster_service.py                 # Roster scan, embed builder, updater
├── migrations/
│   ├── 20251018_create_schedule_config.sql
│   ├── 20260213_create_mission_polls.sql
│   ├── 20260222_create_leave_of_absence.sql
│   └── 20260301_create_roster.sql
└── docs/
    └── BOT_DEEP_DIVE.md                  # Detailed architecture documentation
```

## Database

The bot uses **NeonDB** (PostgreSQL) via `asyncpg` with a connection pool (1–10 connections). Tables are created automatically on startup. Key tables:

- `events` — schedule events (guild, date, type, name, creator)
- `schedule_config` — which channel/message holds the schedule embed
- `mission_polls` — active/completed polls with thread IDs and results
- `loa_entries` — leave of absence records with start/end dates
- `loa_config` — LOA embed channel/message config
- `roster_members` — platoon roster (rank, subgroup, LOA status, active/reserve)
- `roster_config` — roster embed channel/message config

## Setup

### 1. Environment Variables

Create a `.env` file (see `.env.example`):

```
DISCORD_BOT_TOKEN=your_bot_token_here
GUILD_ID=your_discord_server_id
NEONDB_CONNECTION_STRING=postgresql://username:password@host:port/database?sslmode=require
```

### 2. Discord Developer Portal

1. Create an application at [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a bot and copy the token
3. Enable **Privileged Gateway Intents**:
   - **Server Members Intent** (required for roster scanning)
   - **Message Content Intent**
4. Invite the bot with these permissions:
   - Send Messages
   - Use Slash Commands
   - Read Message History
   - Embed Links
   - Manage Messages

### 3. Running

```bash
pip install -r requirements.txt
python start.py
```

The bot will automatically create database tables, load all cogs, sync slash commands, populate events, and update schedule/LOA/roster embeds on startup.

## Commands

| Command | Permission | Description |
|---------|-----------|-------------|
| `/schedule` | Admin / Editor | Assign a mission or training name to an event slot |
| `/configure` | Admin | Set the schedule channel, briefing forum, and events channel |
| `/populate` | Admin | Force re-population of weekly events |
| `/missionpoll` | Admin / Editor | Create a mission poll from forum briefings for an upcoming event |
| `/cancelpoll` | Admin / Editor | Cancel an active mission poll |
| `/loa` | Any member | Request a leave of absence (start/end date) |
| `/configureroster` | Admin | Set the roster channel and post the initial roster embed |
| `/updateroster` | Admin | Force a fresh roster scan and embed update |
| `/ping` | Anyone | Health check |

## Background Tasks

- **Schedule embed refresh** — hourly via `schedule_update_service`
- **LOA expiry check** — hourly, auto-removes expired LOAs and sends DMs
- **Mission poll monitor** — every 30 minutes, processes ended polls and auto-schedules winners
- **Roster refresh** — hourly, re-scans guild members and updates the roster embeds

## Platoon Roster

The roster displays across **4 embeds** on a single message:

1. **Embed 1** — Title (linked to [gol-clan.com/orbat](https://gol-clan.com/orbat)), member stats (Active Duty, On LOA, Reserves), Flying Hellfish header, and ⭐ Leadership (1Lt, 2Lt, Sgt, Cpl)
2. **Embed 2** — 🎖️ Senior Enlisted (LCpl, SPC, PFC)
3. **Embed 3** — 🪖 Enlisted (PSC, PVT, RCT)
4. **Embed 4** — AAC (Army Aircorps) + 🔸 Reserves (up to 20, no profile links)

Active members show rank emojis and profile links. LOA members appear with ~~strikethrough~~ (LOA). Members who lose the `@Active` role while on LOA are still shown in their subgroup.

## Dependencies

```
discord.py>=2.4.0
asyncpg==0.29.0
python-dotenv==1.0.0
tzdata>=2024.1
```

## Troubleshooting

- **Bot not responding** — verify token, guild ID, and that the bot is invited with correct permissions
- **Database errors** — check the NeonDB connection string includes `?sslmode=require`
- **Commands not appearing** — bot needs "Use Slash Commands" permission; try restarting to re-sync
- **Roster missing members** — ensure Server Members Intent is enabled in the Developer Portal
- **LOA not expiring** — check logs for date type mismatches; the bot normalizes `datetime` vs `date` on startup

## License

This project is private and for GOL community use.