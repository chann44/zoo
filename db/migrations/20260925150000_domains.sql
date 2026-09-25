-- +goose Up
-- +goose StatementBegin
CREATE TABLE domains (
    id TEXT PRIMARY KEY NOT NULL,
    hostname TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE domains;
-- +goose StatementEnd
