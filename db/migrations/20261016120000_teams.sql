-- +goose Up
-- Workspaces own what users made: servers, profiles and vault secrets move from their creator to a workspace.
-- user_id / created_by stay, as who made the row.

ALTER TABLE workspace_members DROP CONSTRAINT workspace_members_role_check;
ALTER TABLE workspace_members ADD CONSTRAINT workspace_members_role_check
    CHECK (role IN ('owner', 'admin', 'member', 'viewer'));
ALTER TABLE workspace_invitations DROP CONSTRAINT workspace_invitations_role_check;
ALTER TABLE workspace_invitations ADD CONSTRAINT workspace_invitations_role_check
    CHECK (role IN ('admin', 'member', 'viewer'));
ALTER TABLE workspace_invitations ADD COLUMN revoked_at TIMESTAMPTZ;

-- rows made before this belong to their creator's personal workspace (server/auth_api.py, personal_workspace)
ALTER TABLE servers ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;
UPDATE servers SET workspace_id = (SELECT id FROM workspaces WHERE slug = 'personal-' || servers.created_by);
ALTER TABLE servers ALTER COLUMN workspace_id SET NOT NULL;
CREATE INDEX idx_servers_workspace ON servers(workspace_id);

ALTER TABLE profiles ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;
UPDATE profiles SET workspace_id = (SELECT id FROM workspaces WHERE slug = 'personal-' || profiles.user_id);
ALTER TABLE profiles ALTER COLUMN workspace_id SET NOT NULL;
CREATE INDEX idx_profiles_workspace ON profiles(workspace_id);

ALTER TABLE vault_secrets ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;
UPDATE vault_secrets SET workspace_id = (SELECT id FROM workspaces WHERE slug = 'personal-' || vault_secrets.user_id);
ALTER TABLE vault_secrets ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE vault_secrets DROP CONSTRAINT vault_secrets_user_id_name_key;
ALTER TABLE vault_secrets ADD CONSTRAINT vault_secrets_workspace_id_name_key UNIQUE (workspace_id, name);

-- a join token makes its server in the workspace it was created in
ALTER TABLE node_tokens ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;
UPDATE node_tokens SET workspace_id = (SELECT id FROM workspaces WHERE slug = 'personal-' || node_tokens.created_by);
ALTER TABLE node_tokens ALTER COLUMN workspace_id SET NOT NULL;

-- API keys: the whole workspace, or one sandbox; read-only keys only read
ALTER TABLE api_keys ADD COLUMN sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE CASCADE;
ALTER TABLE api_keys ADD COLUMN read_only BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX idx_api_keys_workspace ON api_keys(workspace_id);

DROP INDEX idx_audit_logs_workspace;
CREATE INDEX idx_audit_logs_workspace ON audit_logs(workspace_id, created_at DESC, id DESC);

-- +goose Down
DROP INDEX idx_audit_logs_workspace;
CREATE INDEX idx_audit_logs_workspace ON audit_logs(workspace_id, created_at);
DROP INDEX idx_api_keys_workspace;
ALTER TABLE api_keys DROP COLUMN read_only;
ALTER TABLE api_keys DROP COLUMN sandbox_id;
ALTER TABLE node_tokens DROP COLUMN workspace_id;
ALTER TABLE vault_secrets DROP CONSTRAINT vault_secrets_workspace_id_name_key;
ALTER TABLE vault_secrets ADD CONSTRAINT vault_secrets_user_id_name_key UNIQUE (user_id, name);
ALTER TABLE vault_secrets DROP COLUMN workspace_id;
ALTER TABLE profiles DROP COLUMN workspace_id;
ALTER TABLE servers DROP COLUMN workspace_id;
ALTER TABLE workspace_invitations DROP COLUMN revoked_at;
ALTER TABLE workspace_invitations DROP CONSTRAINT workspace_invitations_role_check;
ALTER TABLE workspace_invitations ADD CONSTRAINT workspace_invitations_role_check CHECK (role IN ('admin', 'member'));
ALTER TABLE workspace_members DROP CONSTRAINT workspace_members_role_check;
ALTER TABLE workspace_members ADD CONSTRAINT workspace_members_role_check
    CHECK (role IN ('owner', 'admin', 'member'));
