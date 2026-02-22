-- Migration: Create leave_of_absence and loa_config tables
-- Date: 2026-02-22

CREATE TABLE IF NOT EXISTS leave_of_absence (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT,
    expired BOOLEAN NOT NULL DEFAULT FALSE,
    notified BOOLEAN NOT NULL DEFAULT FALSE,
    message_id BIGINT,
    channel_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loa_guild_active
    ON leave_of_absence (guild_id) WHERE expired = FALSE;

CREATE INDEX IF NOT EXISTS idx_loa_user_active
    ON leave_of_absence (guild_id, user_id) WHERE expired = FALSE;

CREATE TABLE IF NOT EXISTS loa_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL
);
