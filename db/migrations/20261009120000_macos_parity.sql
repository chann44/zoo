-- +goose Up
-- +goose StatementBegin
-- The base VM a macOS sandbox was cloned from ('<macOS version>-<build>-<when the base was prepared>'), how long its
-- last boot took from the stopped base, and when the API last restarted it because it hung.
ALTER TABLE sandboxes ADD COLUMN base_version TEXT;
ALTER TABLE sandboxes ADD COLUMN boot_seconds REAL;
ALTER TABLE sandboxes ADD COLUMN recovered_at DATETIME;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE sandboxes DROP COLUMN recovered_at;
ALTER TABLE sandboxes DROP COLUMN boot_seconds;
ALTER TABLE sandboxes DROP COLUMN base_version;
-- +goose StatementEnd
