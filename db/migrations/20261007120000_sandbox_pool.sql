-- +goose Up
-- +goose StatementBegin
-- how many idle sandboxes to keep booted per kind and host; server_id NULL is the API's own Docker
CREATE TABLE pool_settings (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    size INTEGER NOT NULL DEFAULT 0 CHECK (size >= 0),
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- sandboxes booted ahead of a create, with no owner, home data or secrets; a create claims one by taking its id
CREATE TABLE pool_sandboxes (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    image TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'booting' CHECK (status IN ('booting', 'idle', 'failed')),
    runtime_id TEXT,
    runtime_host TEXT,
    access_url TEXT,
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pool_sandboxes_claim ON pool_sandboxes(kind, status, created_at);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE pool_sandboxes;
DROP TABLE pool_settings;
-- +goose StatementEnd
