-- +goose Up
-- single-use websocket tickets (server/tickets.py), shared by every API process; only the ticket's hash is stored
CREATE TABLE tickets (
    ticket_hash TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_tickets_expires ON tickets(expires_at);

-- +goose Down
DROP TABLE IF EXISTS tickets;
