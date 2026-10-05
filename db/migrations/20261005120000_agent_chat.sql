-- +goose Up
-- +goose StatementBegin
CREATE TABLE agent_messages (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('user', 'text', 'reasoning', 'action', 'error')),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'web',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_messages_sandbox ON agent_messages(sandbox_id);

CREATE TABLE agent_channels (
    id TEXT PRIMARY KEY NOT NULL,
    sandbox_id TEXT NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK (platform IN ('slack', 'discord', 'whatsapp')),
    external_id TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (platform, external_id)
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE agent_channels;
DROP TABLE agent_messages;
-- +goose StatementEnd
