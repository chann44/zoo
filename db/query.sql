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
