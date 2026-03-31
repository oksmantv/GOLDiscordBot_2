-- Migration: Add events_channel_id to schedule_config for auto-poll feature
ALTER TABLE schedule_config
    ADD COLUMN IF NOT EXISTS events_channel_id BIGINT;
