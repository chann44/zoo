-- +goose Up
-- +goose StatementBegin
CREATE TABLE agent_settings (
    user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key_ref TEXT,
    api_base TEXT,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE agent_settings;
-- +goose StatementEnd
