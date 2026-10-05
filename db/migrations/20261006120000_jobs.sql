-- +goose Up
-- +goose StatementBegin
CREATE TABLE jobs (
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

CREATE INDEX idx_jobs_state ON jobs(state, run_after);
CREATE INDEX idx_jobs_sandbox ON jobs(sandbox_id, created_at);

ALTER TABLE sandboxes ADD COLUMN unreachable_since DATETIME;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE sandboxes DROP COLUMN unreachable_since;
DROP TABLE jobs;
-- +goose StatementEnd
