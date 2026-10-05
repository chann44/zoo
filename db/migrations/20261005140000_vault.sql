-- +goose Up
-- +goose StatementBegin
CREATE TABLE vault_secrets (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    ciphertext TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at DATETIME,
    UNIQUE (user_id, name)
);

CREATE TABLE sandbox_vault_secrets (
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    secret_id TEXT NOT NULL REFERENCES vault_secrets(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sandbox_id, secret_id)
);

CREATE INDEX idx_sandbox_vault_secrets_secret ON sandbox_vault_secrets(secret_id);

ALTER TABLE profiles ADD COLUMN encrypted INTEGER NOT NULL DEFAULT 0 CHECK (encrypted IN (0, 1));
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE profiles DROP COLUMN encrypted;
DROP TABLE sandbox_vault_secrets;
DROP TABLE vault_secrets;
-- +goose StatementEnd
