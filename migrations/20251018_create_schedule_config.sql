-- Migration: Create schedule_config table for storing schedule message/channel per guild
CREATE TABLE IF NOT EXISTS schedule_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    briefing_channel_id BIGINT
);
