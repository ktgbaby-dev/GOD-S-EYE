-- GOD'S EYE schema. Portable between SQLite and PostgreSQL: {PK} is replaced per dialect,
-- timestamps are ISO-8601 UTC text, JSON is stored as text.

CREATE TABLE IF NOT EXISTS leads (
    id {PK},
    name TEXT NOT NULL,
    handle TEXT NOT NULL,
    handle_norm TEXT NOT NULL,
    platform TEXT NOT NULL,
    profile_url TEXT NOT NULL DEFAULT '',
    genre TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    followers BIGINT,
    bio TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    score_breakdown TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    provenance TEXT NOT NULL DEFAULT 'manual',
    source TEXT NOT NULL DEFAULT 'manual',
    source_url TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    discovered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    last_activity_at TEXT,
    last_release_at TEXT,
    uploads_30d INTEGER,
    last_contacted_at TEXT,
    follow_up_at TEXT,
    status_changed_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    is_demo INTEGER NOT NULL DEFAULT 0,
    batch_id BIGINT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, handle_norm)
);
CREATE INDEX IF NOT EXISTS idx_leads_handle ON leads (handle_norm);
CREATE INDEX IF NOT EXISTS idx_leads_platform ON leads (platform);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads (score);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_discovered ON leads (discovered_at);
CREATE INDEX IF NOT EXISTS idx_leads_last_seen ON leads (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_leads_follow_up ON leads (follow_up_at);

-- Every public handle known for a lead (the primary one plus handles the artist links on their own profiles).
-- The unique key is what stops the same artist being added twice from different sources.
CREATE TABLE IF NOT EXISTS lead_handles (
    id {PK},
    lead_id BIGINT NOT NULL,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    handle_norm TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    provenance TEXT NOT NULL DEFAULT 'source',
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (platform, handle_norm)
);
CREATE INDEX IF NOT EXISTS idx_handles_lead ON lead_handles (lead_id);

CREATE TABLE IF NOT EXISTS activities (
    id {PK},
    lead_id BIGINT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_lead ON activities (lead_id);

-- One row per discovery run (daily drop, manual scan, import).
CREATE TABLE IF NOT EXISTS batches (
    id {PK},
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    stats TEXT NOT NULL DEFAULT '{}',
    errors TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '[]',
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_batches_started ON batches (started_at);

-- Every candidate a run returned, including the ones filtered out, so a filtered prospect can still be kept.
CREATE TABLE IF NOT EXISTS candidates (
    id {PK},
    batch_id BIGINT NOT NULL,
    provider TEXT NOT NULL,
    platform TEXT NOT NULL,
    handle_norm TEXT NOT NULL,
    payload TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    lead_id BIGINT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_batch ON candidates (batch_id);
CREATE INDEX IF NOT EXISTS idx_candidates_lead ON candidates (lead_id);

-- Query rotation: which provider queries ran when, and where to resume (page token / offset).
CREATE TABLE IF NOT EXISTS query_log (
    id {PK},
    provider TEXT NOT NULL,
    query_key TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '{}',
    runs INTEGER NOT NULL DEFAULT 0,
    last_run_at TEXT,
    cursor TEXT NOT NULL DEFAULT '',
    last_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (provider, query_key)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id {PK},
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id {PK},
    ip_hash TEXT NOT NULL,
    ok INTEGER NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (ip_hash, at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
