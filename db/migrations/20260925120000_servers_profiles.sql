-- +goose Up
-- +goose StatementBegin
CREATE TABLE servers (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    docker_url TEXT NOT NULL,
    bind_address TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE sandboxes ADD COLUMN server_id TEXT REFERENCES servers(id);
ALTER TABLE sandboxes ADD COLUMN kind TEXT NOT NULL DEFAULT 'desktop';

CREATE TABLE profiles (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    app TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE profiles;
ALTER TABLE sandboxes DROP COLUMN kind;
ALTER TABLE sandboxes DROP COLUMN server_id;
DROP TABLE servers;
-- +goose StatementEnd
