-- Create mission_polls table for tracking active and completed polls
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
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, completed, failed
    winning_thread_id BIGINT,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mission_polls_guild_status
    ON mission_polls (guild_id, status);

CREATE INDEX IF NOT EXISTS idx_mission_polls_end_time
    ON mission_polls (poll_end_time) WHERE status = 'active';

-- Add log_channel_id to schedule_config
ALTER TABLE schedule_config
    ADD COLUMN IF NOT EXISTS log_channel_id BIGINT;
