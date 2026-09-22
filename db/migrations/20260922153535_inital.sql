-- +goose Up
-- +goose StatementBegin

PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id TEXT PRIMARY KEY NOT NULL,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    avatar_url TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workspaces (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workspace_members (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'suspended')),
    joined_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE workspace_invitations (
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    invited_by TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    accepted_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sandbox_images (
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, slug)
);

CREATE TABLE sandbox_image_versions (
    id TEXT PRIMARY KEY NOT NULL,
    image_id TEXT NOT NULL REFERENCES sandbox_images(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    image_uri TEXT NOT NULL,
    image_digest TEXT,
    build_config TEXT NOT NULL DEFAULT '{}',
    default_resources TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (image_id, version)
);

CREATE TABLE sandboxes (
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
    started_at DATETIME,
    stopped_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME
);

CREATE INDEX idx_sandboxes_workspace ON sandboxes(workspace_id);
CREATE INDEX idx_sandboxes_status ON sandboxes(status);
CREATE INDEX idx_sandboxes_created_by ON sandboxes(created_by);

CREATE TABLE sandbox_members (
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    granted_by TEXT REFERENCES users(id),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sandbox_id, user_id)
);

CREATE TABLE apps (
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    install_config TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_apps_workspace ON apps(workspace_id);

CREATE TABLE sandbox_app_permissions (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'deny' CHECK (effect IN ('allow', 'deny')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (sandbox_id, app_id, action)
);

CREATE TABLE sandbox_network_policies (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL UNIQUE REFERENCES sandboxes(id) ON DELETE CASCADE,
    default_action TEXT NOT NULL DEFAULT 'deny' CHECK (default_action IN ('allow', 'deny')),
    allow_dns INTEGER NOT NULL DEFAULT 1 CHECK (allow_dns IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sandbox_network_rules (
    id TEXT PRIMARY KEY NOT NULL,
    policy_id TEXT NOT NULL REFERENCES sandbox_network_policies(id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL,
    value TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_network_rules_policy ON sandbox_network_rules(policy_id);

CREATE TABLE sandbox_permissions (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    action TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'deny' CHECK (effect IN ('allow', 'deny')),
    rules TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (sandbox_id, permission, action)
);

CREATE TABLE sandbox_secrets (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    injection_config TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (sandbox_id, name)
);

CREATE TABLE agent_sessions (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    created_by TEXT REFERENCES users(id),
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'failed', 'terminated')),
    config TEXT NOT NULL DEFAULT '{}',
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME
);

CREATE INDEX idx_agent_sessions_sandbox ON agent_sessions(sandbox_id);

CREATE TABLE tool_executions (
    id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    input TEXT NOT NULL DEFAULT '{}',
    output TEXT,
    error_message TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tool_executions_session ON tool_executions(session_id, created_at);

CREATE TABLE sandbox_artifacts (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sandbox_artifacts_sandbox ON sandbox_artifacts(sandbox_id, created_at);

CREATE TABLE api_keys (
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    expires_at DATETIME,
    last_used_at DATETIME,
    revoked_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    actor_id TEXT REFERENCES users(id),
    sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_workspace ON audit_logs(workspace_id, created_at);

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS api_keys;
DROP TABLE IF EXISTS sandbox_artifacts;
DROP TABLE IF EXISTS tool_executions;
DROP TABLE IF EXISTS agent_sessions;
DROP TABLE IF EXISTS sandbox_secrets;
DROP TABLE IF EXISTS sandbox_permissions;
DROP TABLE IF EXISTS sandbox_network_rules;
DROP TABLE IF EXISTS sandbox_network_policies;
DROP TABLE IF EXISTS sandbox_app_permissions;
DROP TABLE IF EXISTS apps;
DROP TABLE IF EXISTS sandbox_members;
DROP TABLE IF EXISTS sandboxes;
DROP TABLE IF EXISTS sandbox_image_versions;
DROP TABLE IF EXISTS sandbox_images;
DROP TABLE IF EXISTS workspace_invitations;
DROP TABLE IF EXISTS workspace_members;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS users;

-- +goose StatementEnd