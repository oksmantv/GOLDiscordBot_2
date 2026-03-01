-- Migration: Create feedback_posts table and add feedback_channel_id to schedule_config

-- Track which feedback forum threads have been created to avoid duplicates
CREATE TABLE IF NOT EXISTS feedback_posts (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    event_date DATE NOT NULL,
    thread_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(guild_id, event_date)
);

CREATE INDEX IF NOT EXISTS idx_feedback_posts_guild_date
    ON feedback_posts (guild_id, event_date);

-- Add feedback_channel_id column to schedule_config
ALTER TABLE schedule_config
    ADD COLUMN IF NOT EXISTS feedback_channel_id BIGINT;
