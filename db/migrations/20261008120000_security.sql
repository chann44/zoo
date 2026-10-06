-- +goose Up
-- +goose StatementBegin
-- One data key per workspace (scope 'system' for what belongs to none), wrapped by ZOO_SECRETS_KEY or a KMS
-- (server/kms.py). Secrets are encrypted with their workspace's data key and name it (server/security.py).
CREATE TABLE secret_keys (
    id TEXT PRIMARY KEY NOT NULL,
    scope TEXT NOT NULL UNIQUE,
    wrapped TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rotated_at DATETIME
);

-- the OS a profile was captured on: its files only fit sandboxes of the same one
ALTER TABLE profiles ADD COLUMN platform TEXT NOT NULL DEFAULT 'linux';
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE profiles DROP COLUMN platform;
DROP TABLE secret_keys;
-- +goose StatementEnd
