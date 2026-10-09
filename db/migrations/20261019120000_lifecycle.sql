-- +goose Up
-- idle auto-stop and maximum lifetime (server/sandbox_api.py, expire); a sandbox's null setting takes its
-- workspace's default, and a null default is never
ALTER TABLE sandboxes ADD COLUMN last_activity_at TIMESTAMPTZ;
ALTER TABLE sandboxes ADD COLUMN idle_timeout_minutes BIGINT CHECK (idle_timeout_minutes > 0);
ALTER TABLE sandboxes ADD COLUMN max_lifetime_minutes BIGINT CHECK (max_lifetime_minutes > 0);
ALTER TABLE workspaces ADD COLUMN default_idle_timeout_minutes BIGINT CHECK (default_idle_timeout_minutes > 0);
ALTER TABLE workspaces ADD COLUMN default_max_lifetime_minutes BIGINT CHECK (default_max_lifetime_minutes > 0);

-- +goose Down
ALTER TABLE workspaces DROP COLUMN default_max_lifetime_minutes;
ALTER TABLE workspaces DROP COLUMN default_idle_timeout_minutes;
ALTER TABLE sandboxes DROP COLUMN max_lifetime_minutes;
ALTER TABLE sandboxes DROP COLUMN idle_timeout_minutes;
ALTER TABLE sandboxes DROP COLUMN last_activity_at;
