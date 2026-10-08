-- +goose Up
-- +goose StatementBegin
-- The CA that signs zoo-node certificates and the API's own gRPC certificate. One row; the key is encrypted like
-- other secrets (server/security.py).
CREATE TABLE node_authority (
    id INTEGER PRIMARY KEY NOT NULL CHECK (id = 1),
    certificate TEXT NOT NULL,
    key_ciphertext TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One-time join tokens from the dashboard. server_id is set when the token converts an existing SSH server.
CREATE TABLE node_tokens (
    id TEXT PRIMARY KEY NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A zoo-node and what it last reported. One per server; joining again replaces it (and its certificate).
CREATE TABLE nodes (
    id TEXT PRIMARY KEY NOT NULL,
    server_id TEXT NOT NULL UNIQUE REFERENCES servers(id) ON DELETE CASCADE,
    serial TEXT NOT NULL,
    cert_expires_at DATETIME NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT '',
    arch TEXT NOT NULL DEFAULT '',
    hostname TEXT NOT NULL DEFAULT '',
    drivers TEXT NOT NULL DEFAULT '[]',
    targets TEXT NOT NULL DEFAULT '[]',
    cpus INTEGER,
    memory_total INTEGER,
    memory_available INTEGER,
    disk_total INTEGER,
    disk_free INTEGER,
    load REAL,
    sandboxes TEXT NOT NULL DEFAULT '[]',
    checks TEXT NOT NULL DEFAULT '[]',
    seen_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Home disk snapshots, kept on the sandbox's host next to its disk.
CREATE TABLE snapshots (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    server_id TEXT REFERENCES servers(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'creating' CHECK (state IN ('creating', 'ready', 'failed')),
    error TEXT,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX snapshots_sandbox ON snapshots (sandbox_id, created_at);

-- snapshots are taken and restored as jobs, so they queue behind (and block) boots, stops and moves
CREATE TABLE jobs_rebuilt (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('boot', 'stop', 'delete', 'move', 'snapshot', 'restore')),
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    args TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deadline DATETIME,
    last_error TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME
);
INSERT INTO jobs_rebuilt SELECT id, sandbox_id, kind, state, args, attempts, max_attempts, run_after, deadline, last_error,
    created_at, updated_at, finished_at FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_rebuilt RENAME TO jobs;
CREATE INDEX idx_jobs_state ON jobs(state, run_after);
CREATE INDEX idx_jobs_sandbox ON jobs(sandbox_id, created_at);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DELETE FROM jobs WHERE kind IN ('snapshot', 'restore');
CREATE TABLE jobs_rebuilt (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('boot', 'stop', 'delete', 'move')),
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    args TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deadline DATETIME,
    last_error TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME
);
INSERT INTO jobs_rebuilt SELECT id, sandbox_id, kind, state, args, attempts, max_attempts, run_after, deadline, last_error,
    created_at, updated_at, finished_at FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_rebuilt RENAME TO jobs;
CREATE INDEX idx_jobs_state ON jobs(state, run_after);
CREATE INDEX idx_jobs_sandbox ON jobs(sandbox_id, created_at);
DROP INDEX snapshots_sandbox;
DROP TABLE snapshots;
DROP TABLE nodes;
DROP TABLE node_tokens;
DROP TABLE node_authority;
-- +goose StatementEnd
