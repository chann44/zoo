-- +goose Up
-- +goose StatementBegin
CREATE FUNCTION zoo_now() RETURNS TEXT LANGUAGE sql STABLE AS $$
    SELECT to_char(statement_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
$$;
-- +goose StatementEnd

CREATE TABLE users (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    password TEXT NOT NULL,
    avatar_url TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE secret_keys (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    scope TEXT NOT NULL UNIQUE,
    wrapped TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    rotated_at TEXT
);

CREATE TABLE chat_events (
    zoo_rowid BIGSERIAL,
    platform TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    PRIMARY KEY (platform, event_id)
);

CREATE TABLE leases (
    zoo_rowid BIGSERIAL,
    name TEXT PRIMARY KEY NOT NULL,
    holder TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE node_authority (
    zoo_rowid BIGSERIAL,
    id BIGINT PRIMARY KEY NOT NULL CHECK (id = 1),
    certificate TEXT NOT NULL,
    key_ciphertext TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE workspaces (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE servers (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    docker_url TEXT NOT NULL,
    bind_address TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    platform TEXT NOT NULL DEFAULT 'linux',
    capabilities TEXT NOT NULL DEFAULT ''
);

CREATE TABLE profiles (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    app TEXT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    encrypted BIGINT NOT NULL DEFAULT 0 CHECK (encrypted IN (0, 1)),
    platform TEXT NOT NULL DEFAULT 'linux'
);

CREATE TABLE domains (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    hostname TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE vault_secrets (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    ciphertext TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now(),
    last_used_at TEXT,
    expires_at TEXT,
    rotate_every_days BIGINT,
    rotated_at TEXT,
    UNIQUE (user_id, name)
);

CREATE TABLE workspace_members (
    zoo_rowid BIGSERIAL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'suspended')),
    joined_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE workspace_invitations (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    invited_by TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE sandbox_images (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    is_public BIGINT NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now(),
    UNIQUE (workspace_id, slug)
);

CREATE TABLE apps (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    install_config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE api_keys (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    expires_at TEXT,
    last_used_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE pool_settings (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    size BIGINT NOT NULL DEFAULT 0 CHECK (size >= 0),
    updated_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE pool_sandboxes (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    image TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'booting' CHECK (status IN ('booting', 'idle', 'failed')),
    runtime_id TEXT,
    runtime_host TEXT,
    access_url TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE workspace_agent_settings (
    zoo_rowid BIGSERIAL,
    workspace_id TEXT PRIMARY KEY NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key_secret_id TEXT REFERENCES vault_secrets(id) ON DELETE SET NULL,
    api_base TEXT,
    max_steps BIGINT,
    max_seconds BIGINT,
    max_tokens BIGINT,
    updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE profile_versions (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    version BIGINT NOT NULL,
    size_bytes BIGINT NOT NULL,
    encrypted BIGINT NOT NULL DEFAULT 1 CHECK (encrypted IN (0, 1)),
    sandbox_id TEXT,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    UNIQUE (profile_id, version)
);

CREATE TABLE node_tokens (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE nodes (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    server_id TEXT NOT NULL UNIQUE REFERENCES servers(id) ON DELETE CASCADE,
    serial TEXT NOT NULL,
    cert_expires_at TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT '',
    arch TEXT NOT NULL DEFAULT '',
    hostname TEXT NOT NULL DEFAULT '',
    drivers TEXT NOT NULL DEFAULT '[]',
    targets TEXT NOT NULL DEFAULT '[]',
    cpus BIGINT,
    memory_total BIGINT,
    memory_available BIGINT,
    disk_total BIGINT,
    disk_free BIGINT,
    load DOUBLE PRECISION,
    sandboxes TEXT NOT NULL DEFAULT '[]',
    checks TEXT NOT NULL DEFAULT '[]',
    seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE sandbox_image_versions (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    image_id TEXT NOT NULL REFERENCES sandbox_images(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    image_uri TEXT NOT NULL,
    image_digest TEXT,
    build_config TEXT NOT NULL DEFAULT '{}',
    default_resources TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    UNIQUE (image_id, version)
);

CREATE TABLE sandboxes (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    image_version_id TEXT NOT NULL REFERENCES sandbox_image_versions(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'provisioning', 'running', 'stopped', 'failed', 'deleting', 'deleted')),
    runtime TEXT NOT NULL DEFAULT 'docker',
    runtime_id TEXT,
    runtime_host TEXT,
    access_url TEXT,
    resources TEXT NOT NULL DEFAULT '{}',
    config TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    started_at TEXT,
    stopped_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now(),
    deleted_at TEXT,
    server_id TEXT REFERENCES servers(id),
    kind TEXT NOT NULL DEFAULT 'desktop',
    unreachable_since TEXT,
    base_version TEXT,
    boot_seconds DOUBLE PRECISION,
    recovered_at TEXT
);

CREATE TABLE sandbox_members (
    zoo_rowid BIGSERIAL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    granted_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    PRIMARY KEY (sandbox_id, user_id)
);

CREATE TABLE sandbox_app_permissions (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'deny' CHECK (effect IN ('allow', 'deny')),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    UNIQUE (sandbox_id, app_id, action)
);

CREATE TABLE sandbox_network_policies (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL UNIQUE REFERENCES sandboxes(id) ON DELETE CASCADE,
    default_action TEXT NOT NULL DEFAULT 'deny' CHECK (default_action IN ('allow', 'deny')),
    allow_dns BIGINT NOT NULL DEFAULT 1 CHECK (allow_dns IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE sandbox_permissions (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    action TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'deny' CHECK (effect IN ('allow', 'deny')),
    rules TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    UNIQUE (sandbox_id, permission, action)
);

CREATE TABLE sandbox_secrets (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    injection_config TEXT NOT NULL DEFAULT '{}',
    enabled BIGINT NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now(),
    UNIQUE (sandbox_id, name)
);

CREATE TABLE agent_sessions (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    created_by TEXT REFERENCES users(id),
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'failed', 'terminated')),
    config TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL DEFAULT zoo_now(),
    ended_at TEXT
);

CREATE TABLE audit_logs (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    actor_id TEXT REFERENCES users(id),
    sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE agent_channels (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK (platform IN ('slack', 'discord', 'whatsapp')),
    external_id TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    allowed_users TEXT NOT NULL DEFAULT '["*"]',
    UNIQUE (platform, external_id)
);

CREATE TABLE sandbox_vault_secrets (
    zoo_rowid BIGSERIAL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    secret_id TEXT NOT NULL REFERENCES vault_secrets(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    last_used_at TEXT,
    PRIMARY KEY (sandbox_id, secret_id)
);

CREATE TABLE agent_runs (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    model TEXT,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    attempts BIGINT NOT NULL DEFAULT 0,
    max_attempts BIGINT NOT NULL DEFAULT 3,
    steps BIGINT NOT NULL DEFAULT 0,
    tokens BIGINT NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_steps BIGINT NOT NULL,
    max_seconds BIGINT NOT NULL,
    max_tokens BIGINT NOT NULL,
    worker TEXT,
    heartbeat_at TEXT,
    cancel_requested BIGINT NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE snapshots (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    server_id TEXT REFERENCES servers(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'creating' CHECK (state IN ('creating', 'ready', 'failed')),
    error TEXT,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE jobs (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('boot', 'stop', 'delete', 'move', 'snapshot', 'restore')),
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    args TEXT NOT NULL DEFAULT '{}',
    attempts BIGINT NOT NULL DEFAULT 0,
    max_attempts BIGINT NOT NULL DEFAULT 3,
    run_after TEXT NOT NULL DEFAULT zoo_now(),
    deadline TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now(),
    updated_at TEXT NOT NULL DEFAULT zoo_now(),
    finished_at TEXT
);

CREATE TABLE sandbox_network_rules (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    policy_id TEXT NOT NULL REFERENCES sandbox_network_policies(id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL,
    value TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE tool_executions (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    input TEXT NOT NULL DEFAULT '{}',
    output TEXT,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE sandbox_artifacts (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    mime_type TEXT,
    size_bytes BIGINT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE TABLE agent_messages (
    zoo_rowid BIGSERIAL,
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('user', 'text', 'reasoning', 'action', 'error', 'status')),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'web',
    screenshot TEXT,
    created_at TEXT NOT NULL DEFAULT zoo_now()
);

CREATE INDEX idx_sandboxes_workspace ON sandboxes(workspace_id);
CREATE INDEX idx_sandboxes_status ON sandboxes(status);
CREATE INDEX idx_sandboxes_created_by ON sandboxes(created_by);
CREATE INDEX idx_apps_workspace ON apps(workspace_id);
CREATE INDEX idx_network_rules_policy ON sandbox_network_rules(policy_id);
CREATE INDEX idx_agent_sessions_sandbox ON agent_sessions(sandbox_id);
CREATE INDEX idx_tool_executions_session ON tool_executions(session_id, created_at);
CREATE INDEX idx_sandbox_artifacts_sandbox ON sandbox_artifacts(sandbox_id, created_at);
CREATE INDEX idx_audit_logs_workspace ON audit_logs(workspace_id, created_at);
CREATE INDEX idx_sandbox_vault_secrets_secret ON sandbox_vault_secrets(secret_id);
CREATE INDEX idx_pool_sandboxes_claim ON pool_sandboxes(kind, status, created_at);
CREATE INDEX idx_agent_runs_state ON agent_runs(state, created_at);
CREATE INDEX idx_agent_runs_sandbox ON agent_runs(sandbox_id, created_at);
CREATE UNIQUE INDEX idx_agent_runs_active ON agent_runs(sandbox_id) WHERE state IN ('queued', 'running');
CREATE INDEX idx_agent_messages_sandbox ON agent_messages(sandbox_id);
CREATE INDEX idx_agent_messages_run ON agent_messages(run_id);
CREATE INDEX snapshots_sandbox ON snapshots (sandbox_id, created_at);
CREATE INDEX idx_jobs_state ON jobs(state, run_after);
CREATE INDEX idx_jobs_sandbox ON jobs(sandbox_id, created_at);

-- +goose Down
DROP TABLE IF EXISTS agent_messages CASCADE;
DROP TABLE IF EXISTS sandbox_artifacts CASCADE;
DROP TABLE IF EXISTS tool_executions CASCADE;
DROP TABLE IF EXISTS sandbox_network_rules CASCADE;
DROP TABLE IF EXISTS jobs CASCADE;
DROP TABLE IF EXISTS snapshots CASCADE;
DROP TABLE IF EXISTS agent_runs CASCADE;
DROP TABLE IF EXISTS sandbox_vault_secrets CASCADE;
DROP TABLE IF EXISTS agent_channels CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS agent_sessions CASCADE;
DROP TABLE IF EXISTS sandbox_secrets CASCADE;
DROP TABLE IF EXISTS sandbox_permissions CASCADE;
DROP TABLE IF EXISTS sandbox_network_policies CASCADE;
DROP TABLE IF EXISTS sandbox_app_permissions CASCADE;
DROP TABLE IF EXISTS sandbox_members CASCADE;
DROP TABLE IF EXISTS sandboxes CASCADE;
DROP TABLE IF EXISTS sandbox_image_versions CASCADE;
DROP TABLE IF EXISTS nodes CASCADE;
DROP TABLE IF EXISTS node_tokens CASCADE;
DROP TABLE IF EXISTS profile_versions CASCADE;
DROP TABLE IF EXISTS workspace_agent_settings CASCADE;
DROP TABLE IF EXISTS pool_sandboxes CASCADE;
DROP TABLE IF EXISTS pool_settings CASCADE;
DROP TABLE IF EXISTS api_keys CASCADE;
DROP TABLE IF EXISTS apps CASCADE;
DROP TABLE IF EXISTS sandbox_images CASCADE;
DROP TABLE IF EXISTS workspace_invitations CASCADE;
DROP TABLE IF EXISTS workspace_members CASCADE;
DROP TABLE IF EXISTS vault_secrets CASCADE;
DROP TABLE IF EXISTS domains CASCADE;
DROP TABLE IF EXISTS profiles CASCADE;
DROP TABLE IF EXISTS servers CASCADE;
DROP TABLE IF EXISTS workspaces CASCADE;
DROP TABLE IF EXISTS node_authority CASCADE;
DROP TABLE IF EXISTS leases CASCADE;
DROP TABLE IF EXISTS chat_events CASCADE;
DROP TABLE IF EXISTS secret_keys CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP FUNCTION IF EXISTS zoo_now();
