-- Roster config: which channel/message to post the embed in
CREATE TABLE IF NOT EXISTS roster_config (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL
);

-- Roster members: snapshot of every @Member with role metadata
CREATE TABLE IF NOT EXISTS roster_members (
    id          SERIAL PRIMARY KEY,
    guild_id    BIGINT  NOT NULL,
    user_id     BIGINT  NOT NULL,
    nickname    VARCHAR(255) NOT NULL,         -- display name (rank stripped)
    rank_prefix VARCHAR(10),                   -- e.g. "Cpl."
    rank_name   VARCHAR(50),                   -- e.g. "Corporal"
    rank_order  INTEGER NOT NULL DEFAULT 999,  -- sort weight (lower = higher rank)
    is_active   BOOLEAN NOT NULL DEFAULT FALSE,
    is_reserve  BOOLEAN NOT NULL DEFAULT FALSE,
    subgroup    VARCHAR(50),                   -- "Flying Hellfish" | "AAC" | NULL
    on_loa      BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_roster_guild
    ON roster_members (guild_id);

CREATE INDEX IF NOT EXISTS idx_roster_guild_active
    ON roster_members (guild_id) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_roster_guild_reserve
    ON roster_members (guild_id) WHERE is_reserve = TRUE;
