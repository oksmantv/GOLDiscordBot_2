from .database_connection import db_connection

async def initialize_database():
    """Initialize database tables if they don't exist."""
    create_events_table_query = """
    CREATE TABLE IF NOT EXISTS events (
        id SERIAL PRIMARY KEY,
        guild_id BIGINT NOT NULL,
        date DATE NOT NULL,
        type VARCHAR(50) NOT NULL,
        name VARCHAR(255) DEFAULT '',
        creator_id BIGINT DEFAULT 0,
        creator_name VARCHAR(100) DEFAULT '',
        UNIQUE(guild_id, date, type)
    );
    """
    
    create_index_query = """
    CREATE INDEX IF NOT EXISTS idx_events_guild_date 
    ON events (guild_id, date);
    """

    create_schedule_config_table_query = """
    CREATE TABLE IF NOT EXISTS schedule_config (
        guild_id BIGINT PRIMARY KEY,
        channel_id BIGINT NOT NULL,
        message_id BIGINT NOT NULL,
        briefing_channel_id BIGINT
    );
    """

    ensure_schedule_config_columns_query = """
    ALTER TABLE schedule_config
        ADD COLUMN IF NOT EXISTS briefing_channel_id BIGINT;
    """

    ensure_log_channel_id_query = """
    ALTER TABLE schedule_config
        ADD COLUMN IF NOT EXISTS log_channel_id BIGINT;
    """

    create_mission_polls_table_query = """
    CREATE TABLE IF NOT EXISTS mission_polls (
        id SERIAL PRIMARY KEY,
        guild_id BIGINT NOT NULL,
        poll_message_id BIGINT NOT NULL,
        channel_id BIGINT NOT NULL,
        target_event_id INTEGER NOT NULL REFERENCES events(id),
        framework_filter VARCHAR(50) NOT NULL,
        composition_filter VARCHAR(50) DEFAULT 'All',
        mission_thread_ids JSONB NOT NULL DEFAULT '[]',
        poll_end_time TIMESTAMPTZ NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        winning_thread_id BIGINT,
        created_by BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    ensure_links_message_id_query = """
    ALTER TABLE mission_polls
        ADD COLUMN IF NOT EXISTS links_message_id BIGINT;
    """

    create_mission_polls_index_query = """
    CREATE INDEX IF NOT EXISTS idx_mission_polls_guild_status
        ON mission_polls (guild_id, status);
    """

    create_mission_polls_end_time_index_query = """
    CREATE INDEX IF NOT EXISTS idx_mission_polls_end_time
        ON mission_polls (poll_end_time) WHERE status = 'active';
    """

    try:
        await db_connection.execute_command(create_events_table_query)
        await db_connection.execute_command(create_index_query)
        await db_connection.execute_command(create_schedule_config_table_query)
        await db_connection.execute_command(ensure_schedule_config_columns_query)
        await db_connection.execute_command(ensure_log_channel_id_query)
        await db_connection.execute_command(create_mission_polls_table_query)
        await db_connection.execute_command(ensure_links_message_id_query)
        await db_connection.execute_command(create_mission_polls_index_query)
        await db_connection.execute_command(create_mission_polls_end_time_index_query)
        print("Database tables initialized successfully")
        return True
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return False