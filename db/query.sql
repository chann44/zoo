-- name: CreateUser :one
INSERT INTO users (id, email, name, avatar_url, password)
VALUES (?, ?, ?, ?, ?)
RETURNING *;

-- name: GetUser :one
SELECT * FROM users WHERE id = ? LIMIT 1;

-- name: GetUserByEmail :one
SELECT * FROM users WHERE email = ? LIMIT 1;

-- name: ListUsers :many
SELECT * FROM users ORDER BY created_at DESC;

-- name: UpdateUser :one
UPDATE users
SET name = ?, avatar_url = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: DeleteUser :exec
DELETE FROM users WHERE id = ?;

-- name: CreateWorkspace :one
INSERT INTO workspaces (id, name, slug, created_by)
VALUES (?, ?, ?, ?)
RETURNING *;

-- name: GetWorkspace :one
SELECT * FROM workspaces WHERE id = ? LIMIT 1;

-- name: GetWorkspaceBySlug :one
SELECT * FROM workspaces WHERE slug = ? LIMIT 1;

-- name: ListWorkspacesByUser :many
SELECT w.*
FROM workspaces w
JOIN workspace_members wm ON wm.workspace_id = w.id
WHERE wm.user_id = ? AND wm.status = 'active'
ORDER BY w.created_at DESC;

-- name: UpdateWorkspace :one
UPDATE workspaces
SET name = ?, slug = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: DeleteWorkspace :exec
DELETE FROM workspaces WHERE id = ?;

-- name: AddWorkspaceMember :one
INSERT INTO workspace_members (workspace_id, user_id, role, status, joined_at)
VALUES (?, ?, ?, 'active', CURRENT_TIMESTAMP)
RETURNING *;

-- name: GetWorkspaceMember :one
SELECT * FROM workspace_members
WHERE workspace_id = ? AND user_id = ? LIMIT 1;

-- name: ListWorkspaceMembers :many
SELECT wm.*, u.email, u.name, u.avatar_url
FROM workspace_members wm
JOIN users u ON u.id = wm.user_id
WHERE wm.workspace_id = ?
ORDER BY wm.created_at ASC;

-- name: UpdateWorkspaceMemberRole :one
UPDATE workspace_members
SET role = ?
WHERE workspace_id = ? AND user_id = ?
RETURNING *;

-- name: UpdateWorkspaceMemberStatus :one
UPDATE workspace_members
SET status = ?
WHERE workspace_id = ? AND user_id = ?
RETURNING *;

-- name: RemoveWorkspaceMember :exec
DELETE FROM workspace_members
WHERE workspace_id = ? AND user_id = ?;

-- name: CreateWorkspaceInvitation :one
INSERT INTO workspace_invitations (
    id, workspace_id, email, role, invited_by, token_hash, expires_at
)
VALUES (?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetWorkspaceInvitationByToken :one
SELECT * FROM workspace_invitations
WHERE token_hash = ? AND accepted_at IS NULL
AND expires_at > CURRENT_TIMESTAMP
LIMIT 1;

-- name: ListWorkspaceInvitations :many
SELECT * FROM workspace_invitations
WHERE workspace_id = ? AND accepted_at IS NULL
ORDER BY created_at DESC;

-- name: AcceptWorkspaceInvitation :one
UPDATE workspace_invitations
SET accepted_at = CURRENT_TIMESTAMP
WHERE id = ? AND accepted_at IS NULL
AND expires_at > CURRENT_TIMESTAMP
RETURNING *;

-- name: DeleteWorkspaceInvitation :exec
DELETE FROM workspace_invitations WHERE id = ?;

-- name: CreateSandboxImage :one
INSERT INTO sandbox_images (
    id, workspace_id, name, slug, description, is_public, created_by
)
VALUES (?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxImage :one
SELECT * FROM sandbox_images WHERE id = ? LIMIT 1;

-- name: ListSandboxImages :many
SELECT * FROM sandbox_images
WHERE workspace_id = ?
ORDER BY created_at DESC;

-- name: ListPublicSandboxImages :many
SELECT * FROM sandbox_images
WHERE is_public = 1
ORDER BY created_at DESC;

-- name: UpdateSandboxImage :one
UPDATE sandbox_images
SET name = ?, slug = ?, description = ?, is_public = ?,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: DeleteSandboxImage :exec
DELETE FROM sandbox_images WHERE id = ?;

-- name: CreateSandboxImageVersion :one
INSERT INTO sandbox_image_versions (
    id, image_id, version, image_uri, image_digest,
    build_config, default_resources, created_by
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxImageVersion :one
SELECT * FROM sandbox_image_versions WHERE id = ? LIMIT 1;

-- name: ListSandboxImageVersions :many
SELECT * FROM sandbox_image_versions
WHERE image_id = ?
ORDER BY created_at DESC;

-- name: GetSandboxImageVersionByTag :one
SELECT * FROM sandbox_image_versions
WHERE image_id = ? AND version = ?
LIMIT 1;

-- name: DeleteSandboxImageVersion :exec
DELETE FROM sandbox_image_versions WHERE id = ?;

-- name: CreateSandbox :one
INSERT INTO sandboxes (
    id, workspace_id, image_version_id, created_by,
    name, runtime, resources, config
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetSandbox :one
SELECT * FROM sandboxes WHERE id = ? LIMIT 1;

-- name: GetSandboxByRuntimeID :one
SELECT * FROM sandboxes WHERE runtime_id = ? LIMIT 1;

-- name: ListSandboxesByWorkspace :many
SELECT * FROM sandboxes
WHERE workspace_id = ? AND deleted_at IS NULL
ORDER BY created_at DESC;

-- name: ListSandboxesByUser :many
SELECT * FROM sandboxes
WHERE created_by = ? AND deleted_at IS NULL
ORDER BY created_at DESC;

-- name: ListSandboxesByStatus :many
SELECT * FROM sandboxes
WHERE status = ? AND deleted_at IS NULL
ORDER BY created_at ASC;

-- name: UpdateSandbox :one
UPDATE sandboxes
SET name = ?, resources = ?, config = ?,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: UpdateSandboxStatus :one
UPDATE sandboxes
SET status = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: UpdateSandboxRuntime :one
UPDATE sandboxes
SET runtime_id = ?, runtime_host = ?, access_url = ?,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: SetSandboxStarted :one
UPDATE sandboxes
SET status = 'running',
    started_at = CURRENT_TIMESTAMP,
    stopped_at = NULL,
    error_message = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: SetSandboxStopped :one
UPDATE sandboxes
SET status = 'stopped',
    stopped_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: SetSandboxFailed :one
UPDATE sandboxes
SET status = 'failed',
    error_message = ?,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: SoftDeleteSandbox :one
UPDATE sandboxes
SET status = 'deleted',
    deleted_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: DeleteSandbox :exec
DELETE FROM sandboxes WHERE id = ?;

-- name: AddSandboxMember :one
INSERT INTO sandbox_members (sandbox_id, user_id, role, granted_by)
VALUES (?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxMember :one
SELECT * FROM sandbox_members
WHERE sandbox_id = ? AND user_id = ? LIMIT 1;

-- name: ListSandboxMembers :many
SELECT sm.*, u.email, u.name, u.avatar_url
FROM sandbox_members sm
JOIN users u ON u.id = sm.user_id
WHERE sm.sandbox_id = ?
ORDER BY sm.created_at ASC;

-- name: UpdateSandboxMemberRole :one
UPDATE sandbox_members
SET role = ?
WHERE sandbox_id = ? AND user_id = ?
RETURNING *;

-- name: RemoveSandboxMember :exec
DELETE FROM sandbox_members
WHERE sandbox_id = ? AND user_id = ?;

-- name: CreateApp :one
INSERT INTO apps (id, workspace_id, name, slug, description, install_config)
VALUES (?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetApp :one
SELECT * FROM apps WHERE id = ? LIMIT 1;

-- name: ListAppsByWorkspace :many
SELECT * FROM apps
WHERE workspace_id = ? OR workspace_id IS NULL
ORDER BY name ASC;

-- name: UpdateApp :one
UPDATE apps
SET name = ?, slug = ?, description = ?, install_config = ?
WHERE id = ?
RETURNING *;

-- name: DeleteApp :exec
DELETE FROM apps WHERE id = ?;

-- name: GrantSandboxAppPermission :one
INSERT INTO sandbox_app_permissions (
    id, sandbox_id, app_id, action, effect
)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (sandbox_id, app_id, action)
DO UPDATE SET effect = excluded.effect
RETURNING *;

-- name: GetSandboxAppPermission :one
SELECT * FROM sandbox_app_permissions
WHERE sandbox_id = ? AND app_id = ? AND action = ?
LIMIT 1;

-- name: ListSandboxAppPermissions :many
SELECT sap.*, a.name AS app_name, a.slug AS app_slug
FROM sandbox_app_permissions sap
JOIN apps a ON a.id = sap.app_id
WHERE sap.sandbox_id = ?
ORDER BY a.name ASC;

-- name: DeleteSandboxAppPermission :exec
DELETE FROM sandbox_app_permissions
WHERE sandbox_id = ? AND app_id = ? AND action = ?;

-- name: CreateSandboxNetworkPolicy :one
INSERT INTO sandbox_network_policies (
    id, sandbox_id, default_action, allow_dns
)
VALUES (?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxNetworkPolicy :one
SELECT * FROM sandbox_network_policies
WHERE sandbox_id = ? LIMIT 1;

-- name: UpdateSandboxNetworkPolicy :one
UPDATE sandbox_network_policies
SET default_action = ?, allow_dns = ?,
    updated_at = CURRENT_TIMESTAMP
WHERE sandbox_id = ?
RETURNING *;

-- name: UpsertSandboxNetworkPolicy :one
INSERT INTO sandbox_network_policies (
    id, sandbox_id, default_action, allow_dns
)
VALUES (?, ?, ?, ?)
ON CONFLICT (sandbox_id)
DO UPDATE SET
    default_action = excluded.default_action,
    allow_dns = excluded.allow_dns,
    updated_at = CURRENT_TIMESTAMP
RETURNING *;

-- name: CreateSandboxNetworkRule :one
INSERT INTO sandbox_network_rules (
    id, policy_id, rule_type, value, effect
)
VALUES (?, ?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxNetworkRule :one
SELECT * FROM sandbox_network_rules WHERE id = ? LIMIT 1;

-- name: ListSandboxNetworkRules :many
SELECT * FROM sandbox_network_rules
WHERE policy_id = ?
ORDER BY created_at ASC;

-- name: UpdateSandboxNetworkRule :one
UPDATE sandbox_network_rules
SET rule_type = ?, value = ?, effect = ?
WHERE id = ?
RETURNING *;

-- name: DeleteSandboxNetworkRule :exec
DELETE FROM sandbox_network_rules WHERE id = ?;

-- name: DeleteSandboxNetworkRulesByPolicy :exec
DELETE FROM sandbox_network_rules WHERE policy_id = ?;

-- name: UpsertSandboxPermission :one
INSERT INTO sandbox_permissions (
    id, sandbox_id, permission, action, effect, rules
)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (sandbox_id, permission, action)
DO UPDATE SET
    effect = excluded.effect,
    rules = excluded.rules
RETURNING *;

-- name: GetSandboxPermission :one
SELECT * FROM sandbox_permissions
WHERE sandbox_id = ? AND permission = ? AND action = ?
LIMIT 1;

-- name: ListSandboxPermissions :many
SELECT * FROM sandbox_permissions
WHERE sandbox_id = ?
ORDER BY permission, action;

-- name: DeleteSandboxPermission :exec
DELETE FROM sandbox_permissions
WHERE sandbox_id = ? AND permission = ? AND action = ?;

-- name: CreateSandboxSecret :one
INSERT INTO sandbox_secrets (
    id, sandbox_id, name, secret_ref, injection_config, enabled
)
VALUES (?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxSecret :one
SELECT * FROM sandbox_secrets WHERE id = ? LIMIT 1;

-- name: GetSandboxSecretByName :one
SELECT * FROM sandbox_secrets
WHERE sandbox_id = ? AND name = ? LIMIT 1;

-- name: ListSandboxSecrets :many
SELECT id, sandbox_id, name, injection_config, enabled,
       created_at, updated_at
FROM sandbox_secrets
WHERE sandbox_id = ?
ORDER BY name ASC;

-- name: UpdateSandboxSecret :one
UPDATE sandbox_secrets
SET name = ?, secret_ref = ?, injection_config = ?,
    enabled = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: SetSandboxSecretEnabled :one
UPDATE sandbox_secrets
SET enabled = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: DeleteSandboxSecret :exec
DELETE FROM sandbox_secrets WHERE id = ?;

-- name: CreateAgentSession :one
INSERT INTO agent_sessions (
    id, sandbox_id, created_by, agent_type, config
)
VALUES (?, ?, ?, ?, ?)
RETURNING *;

-- name: GetAgentSession :one
SELECT * FROM agent_sessions WHERE id = ? LIMIT 1;

-- name: ListAgentSessionsBySandbox :many
SELECT * FROM agent_sessions
WHERE sandbox_id = ?
ORDER BY started_at DESC;

-- name: ListActiveAgentSessions :many
SELECT * FROM agent_sessions
WHERE sandbox_id = ? AND status = 'active'
ORDER BY started_at DESC;

-- name: UpdateAgentSessionStatus :one
UPDATE agent_sessions
SET status = ?,
    ended_at = CASE WHEN ? = 'active' THEN NULL ELSE CURRENT_TIMESTAMP END
WHERE id = ?
RETURNING *;

-- name: DeleteAgentSession :exec
DELETE FROM agent_sessions WHERE id = ?;

-- name: CreateToolExecution :one
INSERT INTO tool_executions (
    id, session_id, tool_name, input
)
VALUES (?, ?, ?, ?)
RETURNING *;

-- name: GetToolExecution :one
SELECT * FROM tool_executions WHERE id = ? LIMIT 1;

-- name: ListToolExecutionsBySession :many
SELECT * FROM tool_executions
WHERE session_id = ?
ORDER BY created_at ASC;

-- name: UpdateToolExecutionStatus :one
UPDATE tool_executions
SET status = ?, started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
WHERE id = ?
RETURNING *;

-- name: CompleteToolExecution :one
UPDATE tool_executions
SET status = 'completed',
    output = ?,
    completed_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: FailToolExecution :one
UPDATE tool_executions
SET status = 'failed',
    error_message = ?,
    completed_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: CreateSandboxArtifact :one
INSERT INTO sandbox_artifacts (
    id, sandbox_id, session_id, type,
    storage_key, mime_type, size_bytes, metadata
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetSandboxArtifact :one
SELECT * FROM sandbox_artifacts WHERE id = ? LIMIT 1;

-- name: ListSandboxArtifacts :many
SELECT * FROM sandbox_artifacts
WHERE sandbox_id = ?
ORDER BY created_at DESC;

-- name: ListSessionArtifacts :many
SELECT * FROM sandbox_artifacts
WHERE session_id = ?
ORDER BY created_at DESC;

-- name: DeleteSandboxArtifact :exec
DELETE FROM sandbox_artifacts WHERE id = ?;

-- name: CreateAPIKey :one
INSERT INTO api_keys (
    id, workspace_id, created_by, name,
    key_hash, key_prefix, scopes, expires_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetAPIKeyByHash :one
SELECT * FROM api_keys
WHERE key_hash = ? AND revoked_at IS NULL
AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
LIMIT 1;

-- name: ListAPIKeysByWorkspace :many
SELECT id, workspace_id, created_by, name, key_prefix,
       scopes, expires_at, last_used_at, revoked_at, created_at
FROM api_keys
WHERE workspace_id = ?
ORDER BY created_at DESC;

-- name: UpdateAPIKeyLastUsed :exec
UPDATE api_keys
SET last_used_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: RevokeAPIKey :one
UPDATE api_keys
SET revoked_at = CURRENT_TIMESTAMP
WHERE id = ? AND revoked_at IS NULL
RETURNING *;

-- name: DeleteAPIKey :exec
DELETE FROM api_keys WHERE id = ?;

-- name: CreateAuditLog :one
INSERT INTO audit_logs (
    id, workspace_id, actor_id, sandbox_id,
    action, resource_type, resource_id, metadata
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: ListAuditLogsByWorkspace :many
SELECT * FROM audit_logs
WHERE workspace_id = ?
ORDER BY created_at DESC
LIMIT ? OFFSET ?;

-- name: ListAuditLogsBySandbox :many
SELECT * FROM audit_logs
WHERE sandbox_id = ?
ORDER BY created_at DESC
LIMIT ? OFFSET ?;

-- name: DeleteAuditLogsBefore :exec
DELETE FROM audit_logs WHERE created_at < ?;
-- name: ListToolExecutionsBySandbox :many
SELECT te.* FROM tool_executions te
JOIN agent_sessions s ON s.id = te.session_id
WHERE s.sandbox_id = ?
ORDER BY te.created_at DESC
LIMIT ?;

-- name: ListAllSandboxes :many
SELECT * FROM sandboxes
WHERE deleted_at IS NULL
ORDER BY created_at DESC;

-- name: ClearSandboxRuntime :one
UPDATE sandboxes
SET runtime_id = NULL, runtime_host = NULL, access_url = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: CreateServer :one
INSERT INTO servers (id, name, docker_url, bind_address, platform, capabilities, created_by)
VALUES (?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: UpdateServerCapabilities :exec
UPDATE servers SET capabilities = ? WHERE id = ?;

-- name: GetServer :one
SELECT * FROM servers WHERE id = ? LIMIT 1;

-- name: ListServersByUser :many
SELECT * FROM servers WHERE created_by = ? ORDER BY created_at;

-- name: ListAllServers :many
SELECT * FROM servers;

-- name: DeleteServer :exec
DELETE FROM servers WHERE id = ?;

-- name: SetSandboxPlacement :one
UPDATE sandboxes
SET server_id = ?, kind = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?
RETURNING *;

-- name: CreateProfile :one
INSERT INTO profiles (id, user_id, name, app, size_bytes, encrypted, platform)
VALUES (?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: RenameProfile :one
UPDATE profiles SET name = ? WHERE id = ?
RETURNING *;

-- name: ListAllProfiles :many
SELECT * FROM profiles;

-- name: SetProfileEncrypted :exec
UPDATE profiles SET encrypted = ?, size_bytes = ? WHERE id = ?;

-- name: GetProfile :one
SELECT * FROM profiles WHERE id = ? LIMIT 1;

-- name: ListProfilesByUser :many
SELECT * FROM profiles WHERE user_id = ? ORDER BY created_at DESC;

-- name: FindProfile :one
SELECT * FROM profiles WHERE user_id = ? AND name = ? AND app = ? AND platform = ? LIMIT 1;

-- name: CreateProfileVersion :one
INSERT INTO profile_versions (id, profile_id, version, size_bytes, encrypted, sandbox_id, created_by)
VALUES (?, ?, (SELECT COALESCE(MAX(pv.version), 0) + 1 FROM profile_versions pv WHERE pv.profile_id = ?), ?, ?, ?, ?)
RETURNING *;

-- name: ListProfileVersions :many
SELECT * FROM profile_versions WHERE profile_id = ? ORDER BY version DESC;

-- name: GetProfileVersion :one
SELECT * FROM profile_versions WHERE profile_id = ? AND version = ? LIMIT 1;

-- name: GetLatestProfileVersion :one
SELECT * FROM profile_versions WHERE profile_id = ? ORDER BY version DESC LIMIT 1;

-- name: ListAllProfileVersions :many
SELECT v.*, p.user_id FROM profile_versions v JOIN profiles p ON p.id = v.profile_id;

-- name: SetProfileVersionEncrypted :exec
UPDATE profile_versions SET encrypted = ?, size_bytes = ? WHERE id = ?;

-- name: DeleteProfileVersion :exec
DELETE FROM profile_versions WHERE id = ?;

-- name: SetProfileLatest :exec
UPDATE profiles SET size_bytes = ?, encrypted = ? WHERE id = ?;

-- name: DeleteProfile :exec
DELETE FROM profiles WHERE id = ?;

-- name: DetachServer :exec
UPDATE sandboxes SET server_id = NULL WHERE server_id = ?;

-- name: CreateDomain :one
INSERT INTO domains (id, hostname, created_by)
VALUES (?, ?, ?)
RETURNING *;

-- name: GetDomainByHostname :one
SELECT * FROM domains WHERE hostname = ? LIMIT 1;

-- name: ListDomains :many
SELECT * FROM domains ORDER BY created_at;

-- name: DeleteDomain :exec
DELETE FROM domains WHERE id = ?;

-- name: CreateAgentMessage :one
INSERT INTO agent_messages (id, sandbox_id, run_id, kind, content, source, screenshot)
VALUES (?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetAgentMessage :one
SELECT * FROM agent_messages WHERE id = ? LIMIT 1;

-- name: ListAgentRunMessages :many
SELECT * FROM agent_messages
WHERE run_id = ?
ORDER BY rowid ASC
LIMIT 1000 OFFSET ?;

-- name: ListAgentMessages :many
SELECT * FROM agent_messages
WHERE sandbox_id = ?
ORDER BY rowid ASC;

-- name: DeleteAgentMessages :exec
DELETE FROM agent_messages WHERE sandbox_id = ?;

-- name: CreateAgentChannel :one
INSERT INTO agent_channels (id, sandbox_id, platform, external_id, created_by, allowed_users)
VALUES (?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: SetAgentChannelAllowedUsers :one
UPDATE agent_channels SET allowed_users = ? WHERE id = ?
RETURNING *;

-- name: ListAgentChannelsBySandbox :many
SELECT * FROM agent_channels
WHERE sandbox_id = ?
ORDER BY created_at ASC;

-- name: GetAgentChannel :one
SELECT * FROM agent_channels
WHERE platform = ? AND external_id = ?
LIMIT 1;

-- name: GetAgentChannelByID :one
SELECT * FROM agent_channels WHERE id = ? LIMIT 1;

-- name: DeleteAgentChannel :exec
DELETE FROM agent_channels WHERE id = ?;

-- name: CreateVaultSecret :one
INSERT INTO vault_secrets (id, user_id, name, description, ciphertext)
VALUES (?, ?, ?, ?, ?)
RETURNING *;

-- name: GetVaultSecret :one
SELECT * FROM vault_secrets WHERE id = ? LIMIT 1;

-- name: GetVaultSecretByName :one
SELECT * FROM vault_secrets WHERE user_id = ? AND name = ? LIMIT 1;

-- name: ListVaultSecretsByUser :many
SELECT id, user_id, name, description, created_at, updated_at, last_used_at, expires_at, rotate_every_days, rotated_at
FROM vault_secrets
WHERE user_id = ?
ORDER BY name ASC;

-- name: ListAllVaultSecrets :many
SELECT * FROM vault_secrets;

-- name: UpdateVaultSecretValue :exec
UPDATE vault_secrets
SET ciphertext = ?, updated_at = CURRENT_TIMESTAMP, rotated_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: SetVaultSecretSchedule :exec
UPDATE vault_secrets
SET expires_at = ?, rotate_every_days = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: MarkSandboxVaultSecretsUsed :exec
UPDATE sandbox_vault_secrets SET last_used_at = CURRENT_TIMESTAMP WHERE sandbox_id = ?;

-- name: ListVaultSecretSandboxes :many
SELECT g.sandbox_id, g.secret_id
FROM sandbox_vault_secrets g
JOIN sandboxes s ON s.id = g.sandbox_id
WHERE g.secret_id = ? AND s.status != 'deleted';

-- name: UpdateVaultSecretDescription :exec
UPDATE vault_secrets
SET description = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: RewrapVaultSecret :exec
UPDATE vault_secrets SET ciphertext = ? WHERE id = ?;

-- name: MarkVaultSecretUsed :exec
UPDATE vault_secrets SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?;

-- name: DeleteVaultSecret :exec
DELETE FROM vault_secrets WHERE id = ?;

-- name: AttachVaultSecret :exec
INSERT OR IGNORE INTO sandbox_vault_secrets (sandbox_id, secret_id)
VALUES (?, ?);

-- name: DetachVaultSecret :exec
DELETE FROM sandbox_vault_secrets WHERE sandbox_id = ? AND secret_id = ?;

-- name: DetachVaultSecretEverywhere :exec
DELETE FROM sandbox_vault_secrets WHERE secret_id = ?;

-- name: ListSandboxVaultSecrets :many
SELECT v.id, v.name, v.ciphertext
FROM sandbox_vault_secrets g
JOIN vault_secrets v ON v.id = g.secret_id
WHERE g.sandbox_id = ?
ORDER BY v.name ASC;

-- name: ListVaultGrantsByUser :many
SELECT g.secret_id, g.sandbox_id, s.name AS sandbox_name, s.status AS sandbox_status, g.last_used_at
FROM sandbox_vault_secrets g
JOIN sandboxes s ON s.id = g.sandbox_id
WHERE s.created_by = ? AND s.status != 'deleted'
ORDER BY s.name ASC;

-- name: ListAllSandboxSecrets :many
SELECT id, sandbox_id, secret_ref FROM sandbox_secrets;

-- name: RewrapSandboxSecret :exec
UPDATE sandbox_secrets SET secret_ref = ? WHERE id = ?;

-- name: ListVaultAuditLogs :many
SELECT * FROM audit_logs
WHERE workspace_id = ? AND resource_type IN ('secret', 'profile')
ORDER BY created_at DESC
LIMIT ?;

-- name: CreateJob :one
INSERT INTO jobs (id, sandbox_id, kind, args, max_attempts, deadline)
VALUES (?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetJob :one
SELECT * FROM jobs WHERE id = ?;

-- name: GetActiveJob :one
SELECT * FROM jobs
WHERE sandbox_id = ? AND state IN ('queued', 'running')
ORDER BY created_at DESC
LIMIT 1;

-- name: GetLatestJob :one
SELECT * FROM jobs
WHERE sandbox_id = ?
ORDER BY created_at DESC, rowid DESC
LIMIT 1;

-- name: ListDueJobs :many
SELECT * FROM jobs
WHERE state = 'queued' AND run_after <= CURRENT_TIMESTAMP
ORDER BY created_at ASC, rowid ASC;

-- name: ListJobsByState :many
SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC, rowid ASC;

-- name: ClaimJob :one
UPDATE jobs
SET state = 'running', attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
WHERE id = ? AND state = 'queued'
RETURNING *;

-- name: RetryJob :exec
UPDATE jobs
SET state = 'queued', last_error = ?, run_after = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ? AND state = 'running';

-- name: RequeueJob :exec
UPDATE jobs
SET state = 'queued', attempts = MAX(attempts - 1, 0), last_error = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ? AND state = 'running';

-- name: FinishJob :exec
UPDATE jobs
SET state = ?, last_error = ?, finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE id = ? AND state IN ('queued', 'running');

-- name: CancelSandboxJobs :exec
UPDATE jobs
SET state = 'cancelled', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE sandbox_id = ? AND state = 'queued';

-- name: SetSandboxReachable :exec
UPDATE sandboxes SET unreachable_since = NULL WHERE id = ? AND unreachable_since IS NOT NULL;

-- name: SetSandboxUnreachable :exec
UPDATE sandboxes SET unreachable_since = COALESCE(unreachable_since, CURRENT_TIMESTAMP) WHERE id = ?;

-- name: SetPoolSize :exec
INSERT INTO pool_settings (id, kind, server_id, size)
VALUES (?, ?, ?, ?)
ON CONFLICT (id) DO UPDATE SET size = excluded.size, updated_at = CURRENT_TIMESTAMP;

-- name: ListPoolSettings :many
SELECT * FROM pool_settings ORDER BY kind, server_id;

-- name: CreatePoolSandbox :one
INSERT INTO pool_sandboxes (id, kind, server_id, image, config)
VALUES (?, ?, ?, ?, ?)
RETURNING *;

-- name: ListPoolSandboxes :many
SELECT * FROM pool_sandboxes ORDER BY created_at, rowid;

-- name: SetPoolSandboxRuntime :exec
UPDATE pool_sandboxes
SET runtime_id = ?, runtime_host = ?, access_url = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: SetPoolSandboxIdle :exec
UPDATE pool_sandboxes SET status = 'idle', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'booting';

-- name: SetPoolSandboxFailed :exec
UPDATE pool_sandboxes SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;

-- name: ClaimPoolSandbox :one
DELETE FROM pool_sandboxes
WHERE id = (
    SELECT p.id FROM pool_sandboxes p
    WHERE p.status = 'idle' AND p.kind = ? AND COALESCE(p.server_id, '') = ? AND p.image = ?
    ORDER BY p.created_at, p.rowid
    LIMIT 1
)
RETURNING *;

-- name: DeletePoolSandbox :one
DELETE FROM pool_sandboxes WHERE id = ? RETURNING *;

-- name: GetSecretKey :one
SELECT * FROM secret_keys WHERE id = ? LIMIT 1;

-- name: GetSecretKeyByScope :one
SELECT * FROM secret_keys WHERE scope = ? LIMIT 1;

-- name: CreateSecretKey :exec
INSERT INTO secret_keys (id, scope, wrapped) VALUES (?, ?, ?)
ON CONFLICT (scope) DO NOTHING;

-- name: ListSecretKeys :many
SELECT * FROM secret_keys;

-- name: RewrapSecretKey :exec
UPDATE secret_keys SET wrapped = ?, rotated_at = CURRENT_TIMESTAMP WHERE id = ?;

-- name: DeferJob :exec
UPDATE jobs
SET state = 'queued', attempts = MAX(attempts - 1, 0), last_error = ?, run_after = ?, deadline = ?,
    updated_at = CURRENT_TIMESTAMP
WHERE id = ? AND state = 'running';

-- name: SetSandboxBoot :exec
UPDATE sandboxes
SET base_version = ?, boot_seconds = ?, updated_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: SetSandboxRecovered :exec
UPDATE sandboxes
SET recovered_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: GetWorkspaceAgentSettings :one
SELECT * FROM workspace_agent_settings WHERE workspace_id = ? LIMIT 1;

-- name: UpsertWorkspaceAgentSettings :one
INSERT INTO workspace_agent_settings (
    workspace_id, provider, model, api_key_secret_id, api_base, max_steps, max_seconds, max_tokens, updated_by
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (workspace_id)
DO UPDATE SET
    provider = excluded.provider,
    model = excluded.model,
    api_key_secret_id = excluded.api_key_secret_id,
    api_base = excluded.api_base,
    max_steps = excluded.max_steps,
    max_seconds = excluded.max_seconds,
    max_tokens = excluded.max_tokens,
    updated_by = excluded.updated_by,
    updated_at = CURRENT_TIMESTAMP
RETURNING *;

-- name: DeleteWorkspaceAgentSettings :exec
DELETE FROM workspace_agent_settings WHERE workspace_id = ?;

-- name: ListAgentKeySecrets :many
SELECT api_key_secret_id FROM workspace_agent_settings WHERE api_key_secret_id IS NOT NULL;

-- name: CreateAgentRun :one
INSERT INTO agent_runs (id, sandbox_id, user_id, source, model, max_steps, max_seconds, max_tokens, max_attempts)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: GetAgentRun :one
SELECT * FROM agent_runs WHERE id = ? LIMIT 1;

-- name: GetActiveAgentRun :one
SELECT * FROM agent_runs WHERE sandbox_id = ? AND state IN ('queued', 'running') LIMIT 1;

-- name: GetLatestAgentRun :one
SELECT * FROM agent_runs WHERE sandbox_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1;

-- name: ListQueuedAgentRuns :many
SELECT * FROM agent_runs WHERE state = 'queued' ORDER BY created_at ASC, rowid ASC;

-- name: ListStaleAgentRuns :many
SELECT * FROM agent_runs WHERE state = 'running' AND (heartbeat_at IS NULL OR heartbeat_at < ?);

-- name: ClaimAgentRun :one
UPDATE agent_runs
SET state = 'running', worker = ?, attempts = attempts + 1, heartbeat_at = CURRENT_TIMESTAMP,
    started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
WHERE id = ? AND state = 'queued'
RETURNING *;

-- name: HeartbeatAgentRun :one
UPDATE agent_runs SET heartbeat_at = CURRENT_TIMESTAMP
WHERE id = ? AND state = 'running' AND worker = ?
RETURNING cancel_requested;

-- name: RecordAgentRunUsage :exec
UPDATE agent_runs SET steps = ?, tokens = ?, cost = ? WHERE id = ?;

-- name: RequestAgentRunCancel :exec
UPDATE agent_runs SET cancel_requested = 1 WHERE id = ? AND state IN ('queued', 'running');

-- name: RequeueAgentRun :exec
UPDATE agent_runs
SET state = 'queued', worker = NULL, heartbeat_at = NULL, error = ?, attempts = MAX(attempts - ?, 0)
WHERE id = ? AND state = 'running';

-- name: FinishAgentRun :exec
UPDATE agent_runs
SET state = ?, error = ?, finished_at = CURRENT_TIMESTAMP, worker = NULL
WHERE id = ? AND state IN ('queued', 'running');

-- name: ListAgentRunIds :many
SELECT id FROM agent_runs;

-- name: RecordChatEvent :one
INSERT INTO chat_events (platform, event_id) VALUES (?, ?)
ON CONFLICT (platform, event_id) DO NOTHING
RETURNING event_id;

-- name: PurgeChatEvents :exec
DELETE FROM chat_events WHERE created_at < ?;

-- name: AcquireLease :one
INSERT INTO leases (name, holder, expires_at) VALUES (?, ?, ?)
ON CONFLICT (name) DO UPDATE SET holder = excluded.holder, expires_at = excluded.expires_at
WHERE leases.holder = excluded.holder OR leases.expires_at < CURRENT_TIMESTAMP
RETURNING holder;

-- name: ReleaseLease :exec
DELETE FROM leases WHERE name = ? AND holder = ?;

-- name: CountSandboxesByState :many
SELECT status, kind, COUNT(*) AS count FROM sandboxes WHERE status != 'deleted' GROUP BY status, kind;

-- name: ListAgentRunsBySandbox :many
SELECT * FROM agent_runs WHERE sandbox_id = ? ORDER BY created_at DESC, rowid DESC;

-- name: GetNodeAuthority :one
SELECT * FROM node_authority WHERE id = 1;

-- name: CreateNodeAuthority :exec
INSERT INTO node_authority (id, certificate, key_ciphertext) VALUES (1, ?, ?)
ON CONFLICT (id) DO NOTHING;

-- name: CreateNodeToken :one
INSERT INTO node_tokens (id, secret_hash, created_by, server_id, name, expires_at)
VALUES (?, ?, ?, ?, ?, ?)
RETURNING *;

-- name: ClaimNodeToken :one
UPDATE node_tokens SET used_at = CURRENT_TIMESTAMP
WHERE secret_hash = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP
RETURNING *;

-- name: PurgeNodeTokens :exec
DELETE FROM node_tokens WHERE expires_at < datetime('now', '-1 day');

-- name: UpsertNode :one
INSERT INTO nodes (id, server_id, serial, cert_expires_at, os, arch, hostname)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (server_id) DO UPDATE SET
    id = excluded.id, serial = excluded.serial, cert_expires_at = excluded.cert_expires_at, os = excluded.os,
    arch = excluded.arch, hostname = excluded.hostname, version = '', seen_at = NULL
RETURNING *;

-- name: GetNode :one
SELECT * FROM nodes WHERE id = ? LIMIT 1;

-- name: GetNodeByServer :one
SELECT * FROM nodes WHERE server_id = ? LIMIT 1;

-- name: ListNodes :many
SELECT * FROM nodes;

-- name: SetNodeCertificate :exec
UPDATE nodes SET serial = ?, cert_expires_at = ? WHERE id = ?;

-- name: SetNodeHello :exec
UPDATE nodes SET version = ?, os = ?, arch = ?, hostname = ?, drivers = ?, targets = ?, seen_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: SetNodeStatus :exec
UPDATE nodes
SET cpus = ?, memory_total = ?, memory_available = ?, disk_total = ?, disk_free = ?, load = ?, sandboxes = ?,
    checks = ?, seen_at = CURRENT_TIMESTAMP
WHERE id = ?;

-- name: CreateSnapshot :one
INSERT INTO snapshots (id, sandbox_id, server_id, name, created_by)
VALUES (?, ?, ?, ?, ?)
RETURNING *;

-- name: SetSnapshotReady :exec
UPDATE snapshots SET state = 'ready', size_bytes = ?, error = NULL WHERE id = ?;

-- name: SetSnapshotFailed :exec
UPDATE snapshots SET state = 'failed', error = ? WHERE id = ?;

-- name: GetSnapshot :one
SELECT * FROM snapshots WHERE id = ? LIMIT 1;

-- name: ListSnapshotsBySandbox :many
SELECT * FROM snapshots WHERE sandbox_id = ? ORDER BY created_at DESC, rowid DESC;

-- name: DeleteSnapshot :exec
DELETE FROM snapshots WHERE id = ?;
