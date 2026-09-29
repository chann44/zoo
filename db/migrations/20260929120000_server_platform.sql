-- +goose Up
-- +goose StatementBegin
ALTER TABLE servers ADD COLUMN platform TEXT NOT NULL DEFAULT 'linux';
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE servers DROP COLUMN platform;
-- +goose StatementEnd
