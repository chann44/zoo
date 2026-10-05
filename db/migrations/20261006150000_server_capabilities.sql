-- +goose Up
-- +goose StatementBegin
-- the sandbox OSes a server can run, comma separated: a Linux host runs linux, a Mac runs macos and, with
-- Docker, linux, a Windows host runs windows and, with Docker, linux
ALTER TABLE servers ADD COLUMN capabilities TEXT NOT NULL DEFAULT '';
UPDATE servers SET capabilities = platform;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE servers DROP COLUMN capabilities;
-- +goose StatementEnd
