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
    
    try:
        await db_connection.execute_command(create_events_table_query)
        await db_connection.execute_command(create_index_query)
        await db_connection.execute_command(create_schedule_config_table_query)
        await db_connection.execute_command(ensure_schedule_config_columns_query)
        print("Database tables initialized successfully")
        return True
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return False