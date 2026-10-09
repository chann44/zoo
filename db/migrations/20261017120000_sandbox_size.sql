-- +goose Up
-- what each sandbox may use; disk_gb null: no disk limit beyond the host's (server/sizes.py)
ALTER TABLE sandboxes ADD COLUMN cpus DOUBLE PRECISION NOT NULL DEFAULT 2;
ALTER TABLE sandboxes ADD COLUMN memory_mb BIGINT NOT NULL DEFAULT 2048;
ALTER TABLE sandboxes ADD COLUMN disk_gb BIGINT;

-- +goose Down
ALTER TABLE sandboxes DROP COLUMN disk_gb;
ALTER TABLE sandboxes DROP COLUMN memory_mb;
ALTER TABLE sandboxes DROP COLUMN cpus;
