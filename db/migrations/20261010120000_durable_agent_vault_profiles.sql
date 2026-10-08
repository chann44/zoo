-- +goose Up
-- +goose StatementBegin
-- One agent task in a sandbox. Runs are claimed by a worker process, which keeps heartbeat_at fresh; a run whose
-- worker stops heartbeating is resumed by another (or the same, restarted) worker, up to max_attempts.
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    model TEXT,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    steps INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    max_steps INTEGER NOT NULL,
    max_seconds INTEGER NOT NULL,
    max_tokens INTEGER NOT NULL,
    worker TEXT,
    heartbeat_at DATETIME,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    error TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    finished_at DATETIME
);

CREATE INDEX idx_agent_runs_state ON agent_runs(state, created_at);
CREATE INDEX idx_agent_runs_sandbox ON agent_runs(sandbox_id, created_at);
-- at most one unfinished run per sandbox
CREATE UNIQUE INDEX idx_agent_runs_active ON agent_runs(sandbox_id) WHERE state IN ('queued', 'running');

-- agent_messages gains its run, the screenshot the agent saw before an action, and 'status' notes (resumed, paused)
CREATE TABLE agent_messages_new (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('user', 'text', 'reasoning', 'action', 'error', 'status')),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'web',
    screenshot TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO agent_messages_new (id, sandbox_id, kind, content, source, created_at)
SELECT id, sandbox_id, kind, content, source, created_at FROM agent_messages ORDER BY rowid;
DROP TABLE agent_messages;
ALTER TABLE agent_messages_new RENAME TO agent_messages;
CREATE INDEX idx_agent_messages_sandbox ON agent_messages(sandbox_id);
CREATE INDEX idx_agent_messages_run ON agent_messages(run_id);

-- Agent model, provider and limits per workspace. The provider key is a vault secret.
CREATE TABLE workspace_agent_settings (
    workspace_id TEXT PRIMARY KEY NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key_secret_id TEXT REFERENCES vault_secrets(id) ON DELETE SET NULL,
    api_base TEXT,
    max_steps INTEGER,
    max_seconds INTEGER,
    max_tokens INTEGER,
    updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- move saved keys into the vault (same workspace data key, so the ciphertext carries over) and settings to workspaces
INSERT OR IGNORE INTO vault_secrets (id, user_id, name, description, ciphertext)
SELECT lower(hex(randomblob(16))), s.user_id, 'AGENT_' || upper(s.provider) || '_API_KEY', 'Agent provider key', s.api_key_ref
FROM agent_settings s
WHERE s.api_key_ref IS NOT NULL;
-- the name was taken by a secret of the user's own
INSERT OR IGNORE INTO vault_secrets (id, user_id, name, description, ciphertext)
SELECT lower(hex(randomblob(16))), s.user_id, 'AGENT_' || upper(s.provider) || '_API_KEY_SAVED', 'Agent provider key', s.api_key_ref
FROM agent_settings s
WHERE s.api_key_ref IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM vault_secrets v WHERE v.user_id = s.user_id AND v.ciphertext = s.api_key_ref);

INSERT OR IGNORE INTO workspace_agent_settings (workspace_id, provider, model, api_key_secret_id, api_base, updated_by)
SELECT w.id, s.provider, s.model,
       (SELECT v.id FROM vault_secrets v
        WHERE v.user_id = s.user_id AND v.ciphertext = s.api_key_ref LIMIT 1),
       s.api_base, s.user_id
FROM agent_settings s
JOIN workspaces w ON w.slug = 'personal-' || s.user_id;

DROP TABLE agent_settings;

-- who may command a sandbox from a linked channel: platform user IDs, or "*" for anyone in the channel
ALTER TABLE agent_channels ADD COLUMN allowed_users TEXT NOT NULL DEFAULT '["*"]';

-- platform events already handled, so retries and duplicate deliveries start nothing twice (on any replica)
CREATE TABLE chat_events (
    platform TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform, event_id)
);

-- singleton work (the Discord bot) runs in whichever worker holds its lease
CREATE TABLE leases (
    name TEXT PRIMARY KEY NOT NULL,
    holder TEXT NOT NULL,
    expires_at DATETIME NOT NULL
);

-- secret expiry and rotation reminders
ALTER TABLE vault_secrets ADD COLUMN expires_at DATETIME;
ALTER TABLE vault_secrets ADD COLUMN rotate_every_days INTEGER;
ALTER TABLE vault_secrets ADD COLUMN rotated_at DATETIME;
UPDATE vault_secrets SET rotated_at = updated_at;
-- when each sandbox last received the secret (boot or live update)
ALTER TABLE sandbox_vault_secrets ADD COLUMN last_used_at DATETIME;

-- Profile versions: saving a profile again adds a version, loading picks one. A version's file is <version id>.tar;
-- existing profiles become version 1 with the profile's own id, so their files stay where they are.
CREATE TABLE profile_versions (
    id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 1 CHECK (encrypted IN (0, 1)),
    sandbox_id TEXT,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (profile_id, version)
);
INSERT INTO profile_versions (id, profile_id, version, size_bytes, encrypted, created_by, created_at)
SELECT id, id, 1, size_bytes, encrypted, user_id, created_at FROM profiles;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE profile_versions;
ALTER TABLE sandbox_vault_secrets DROP COLUMN last_used_at;
ALTER TABLE vault_secrets DROP COLUMN rotated_at;
ALTER TABLE vault_secrets DROP COLUMN rotate_every_days;
ALTER TABLE vault_secrets DROP COLUMN expires_at;
DROP TABLE leases;
DROP TABLE chat_events;
ALTER TABLE agent_channels DROP COLUMN allowed_users;

CREATE TABLE agent_settings (
    user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key_ref TEXT,
    api_base TEXT,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO agent_settings (user_id, provider, model, api_key_ref, api_base)
SELECT w.created_by, s.provider, s.model, v.ciphertext, s.api_base
FROM workspace_agent_settings s
JOIN workspaces w ON w.id = s.workspace_id
LEFT JOIN vault_secrets v ON v.id = s.api_key_secret_id;
DROP TABLE workspace_agent_settings;

CREATE TABLE agent_messages_old (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('user', 'text', 'reasoning', 'action', 'error')),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'web',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO agent_messages_old (id, sandbox_id, kind, content, source, created_at)
SELECT id, sandbox_id, CASE kind WHEN 'status' THEN 'error' ELSE kind END, content, source, created_at
FROM agent_messages ORDER BY rowid;
DROP TABLE agent_messages;
ALTER TABLE agent_messages_old RENAME TO agent_messages;
CREATE INDEX idx_agent_messages_sandbox ON agent_messages(sandbox_id);
DROP TABLE agent_runs;
-- +goose StatementEnd
