-- +goose Up
-- what a workspace may use at once (server/quotas.py); a null limit is no limit
CREATE TABLE workspace_quotas (
    workspace_id TEXT PRIMARY KEY NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    max_running_sandboxes BIGINT,
    max_cpus DOUBLE PRECISION,
    max_memory_mb BIGINT,
    max_storage_gb BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE IF EXISTS workspace_quotas;
