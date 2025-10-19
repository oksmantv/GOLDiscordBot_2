# GOL Discord Bot (Guild Operations Logistics)

A Discord bot for managing weekly training and mission schedules using NeonDB backend.

## Features

- **Slash Commands**: Proper Discord application commands with dropdown menus
- **8-Week Schedule**: Maintains 4 weeks past and 4 weeks future events
- **Manual Date Input**: Support for DD-MM-YY format for specific dates
- **Auto-Population**: Automatically creates weekly events (Thu Training, Thu Mission, Sun Mission)
- **Clean Architecture**: Separated services for database, events, and commands

## Project Structure

```
GOLDiscordBot_2/
├── bot.py                          # Main bot entry point
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variables template
├── config/
│   ├── __init__.py
│   └── settings.py                 # Configuration management
├── models/
│   ├── __init__.py
│   └── event.py                    # Event data model
├── services/
│   ├── __init__.py
│   ├── database_connection.py      # NeonDB connection pool
│   ├── database_service.py         # Database initialization
│   ├── event_repository.py         # Event CRUD operations
│   ├── event_population_service.py # Auto-populate events
│   └── date_filter_service.py      # Date filtering and parsing
└── commands/
    ├── __init__.py
    └── schedule_commands.py         # /schedule slash command
```

## Database Schema

```sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    date DATE NOT NULL,
    type VARCHAR(50) NOT NULL,
    name VARCHAR(255) DEFAULT '',
    creator_id BIGINT DEFAULT 0,
    creator_name VARCHAR(100) DEFAULT '',
    UNIQUE(guild_id, date, type)
);

CREATE INDEX idx_events_guild_date ON events (guild_id, date);
```

## Setup Instructions

### 1. Environment Configuration

1. Copy `.env.example` to `.env`
2. Fill in your configuration:
   ```
   DISCORD_BOT_TOKEN=your_bot_token_here
   GUILD_ID=your_discord_server_id
   NEONDB_CONNECTION_STRING=postgresql://username:password@host:port/database?sslmode=require
   ```

### 2. Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Copy the bot token to your `.env` file
5. Enable the following bot permissions:
   - Send Messages
   - Use Slash Commands
   - Read Message History
   - Embed Links

### 3. NeonDB Setup

1. Create a [NeonDB](https://neon.tech/) account
2. Create a new database
3. Copy the connection string to your `.env` file
4. The bot will automatically create the required tables

### 4. Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

## fps.ms Deployment

### Requirements for fps.ms

- **File Size**: Project fits within 250 MB storage limit
- **Memory**: 128 MB RAM sufficient for this bot
- **Renewal**: Requires 24-hour renewal for free tier

### Deployment Steps

1. **Prepare Files**:
   - Create `.env` file with your credentials (do NOT include in git)
   - Upload all project files to fps.ms file manager

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Variables**:
   - Set environment variables in fps.ms panel or include `.env` file
   - Required variables:
     - `DISCORD_BOT_TOKEN`
     - `GUILD_ID`  
     - `NEONDB_CONNECTION_STRING`

4. **Run Command**:
   ```bash
   python bot.py
   ```

5. **Verification**:
   - Check bot appears online in Discord
   - Test `/schedule` command in your server
   - Verify events are auto-populated

### Security Notes

- Never commit `.env` file to public repository
- Use environment variables on fps.ms for sensitive data
- Regularly rotate your Discord bot token and database credentials

## Usage

### /schedule Command

The main command for updating event details:

```
/schedule event:[dropdown] name:[text] author:[optional] manual_date:[optional]
```

**Parameters**:
- `event`: Dropdown menu showing available events (format: "Thursday Training - 24/10/25")
- `name`: Event name/description (required)
- `author`: Event organizer (optional, defaults to command user)
- `manual_date`: Specific date in DD-MM-YY format (optional)

**Examples**:
- `/schedule event:"Thursday Training - 24/10/25" name:"CQB Training Session" author:"John"`
- `/schedule event:"Sunday Mission - 27/10/25" name:"Operation Thunderbolt"`
- `/schedule name:"Special Training" manual_date:"15-12-25"` (with autocomplete)

### Event Management

- **Auto-Population**: Bot automatically creates 8 weeks of events
- **Event Types**: Training (Thursdays), Mission (Thursdays & Sundays)
- **Date Range**: 4 weeks past to 4 weeks future from current date
- **Manual Dates**: Use DD-MM-YY format for specific dates outside normal range

## Architecture

### Services

- **DatabaseConnection**: Manages NeonDB connection pool
- **EventRepository**: CRUD operations for events
- **EventPopulationService**: Auto-creates weekly recurring events  
- **DateFilterService**: Handles date parsing and filtering
- **ScheduleCommands**: Discord slash command handlers

### Design Principles

- **Single Responsibility**: Each service has one clear purpose
- **Clean Code**: Small, focused methods and classes
- **Error Handling**: Comprehensive error handling and logging
- **Async/Await**: Full async support for Discord and database operations

## Troubleshooting

### Common Issues

1. **Bot Not Responding**:
   - Check bot token is correct
   - Verify bot has proper permissions in server
   - Check guild ID matches your server

2. **Database Connection**:
   - Verify NeonDB connection string format
   - Check database is accessible and running
   - Ensure SSL mode is enabled

3. **Commands Not Appearing**:
   - Bot needs "Use Slash Commands" permission
   - Commands sync to specific guild ID
   - Try restarting the bot

### Logs

The bot provides detailed logging for troubleshooting:
- Configuration validation
- Database connection status
- Command registration
- Error details

## Future Features

Planned enhancements for later versions:
- `/view-schedule` command to display current schedule
- Auto-updating schedule messages
- Event reminders and notifications
- Multi-guild support
- Web dashboard for schedule management

## License

This project is for personal use as specified by fps.ms terms of service.