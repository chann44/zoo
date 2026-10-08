"""Upgrades a database holding data from before a migration and checks what the migration made of it."""

import re
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import MIGRATIONS, POSTGRES

# SQLite's own migrations; the Postgres schema is checked by running the whole suite on it
pytestmark = pytest.mark.skipif(bool(POSTGRES), reason="SQLite migrations")

DURABLE = "20261010120000_durable_agent_vault_profiles.sql"


def run(conn: sqlite3.Connection, migration: Path, section: str = "Up"):
    up, _, down = migration.read_text().partition("-- +goose Down")
    sql = up if section == "Up" else down
    conn.executescript(re.sub(r"^-- \+goose .*$", "", sql, flags=re.MULTILINE))


def migrate_until(conn: sqlite3.Connection, name: str):
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if migration.name == name:
            return migration
        run(conn, migration)
    raise AssertionError(f"{name} not found")


def legacy(conn: sqlite3.Connection):
    conn.executescript(
        """
        INSERT INTO users (id, email, password, name) VALUES ('u1', 'a@example.com', 'x', 'A');
        INSERT INTO users (id, email, password, name) VALUES ('u2', 'b@example.com', 'x', 'B');
        INSERT INTO workspaces (id, name, slug, created_by) VALUES ('w1', 'Personal', 'personal-u1', 'u1');
        INSERT INTO workspaces (id, name, slug, created_by) VALUES ('w2', 'Personal', 'personal-u2', 'u2');
        INSERT INTO sandbox_images (id, workspace_id, name, slug, created_by) VALUES ('i1', 'w1', 'd', 'd', 'u1');
        INSERT INTO sandbox_image_versions (id, image_id, version, image_uri, created_by) VALUES ('v1', 'i1', '1', 'img', 'u1');
        INSERT INTO sandboxes (id, workspace_id, image_version_id, created_by, name) VALUES ('s1', 'w1', 'v1', 'u1', 'box');
        INSERT INTO agent_messages (id, sandbox_id, kind, content, source) VALUES ('m1', 's1', 'user', 'hi', 'web');
        INSERT INTO agent_messages (id, sandbox_id, kind, content, source) VALUES ('m2', 's1', 'text', 'hello', 'web');
        INSERT INTO agent_channels (id, sandbox_id, platform, external_id, created_by)
            VALUES ('c1', 's1', 'slack', 'C1', 'u1');
        INSERT INTO agent_settings (user_id, provider, model, api_key_ref, api_base)
            VALUES ('u1', 'anthropic', 'claude-x', 'gAAAA-key-u1', NULL);
        -- u2 already has a secret with the name the migration would pick
        INSERT INTO vault_secrets (id, user_id, name, ciphertext) VALUES ('taken', 'u2', 'AGENT_OPENAI_API_KEY', 'other');
        INSERT INTO agent_settings (user_id, provider, model, api_key_ref, api_base)
            VALUES ('u2', 'openai', 'gpt', 'gAAAA-key-u2', 'http://proxy');
        INSERT INTO profiles (id, user_id, name, app, size_bytes, encrypted, platform)
            VALUES ('p1', 'u1', 'work', 'firefox', 42, 1, 'linux');
        INSERT INTO vault_secrets (id, user_id, name, ciphertext, updated_at)
            VALUES ('vs1', 'u1', 'TOKEN', 'c', '2026-01-02 03:04:05');
        """
    )


def test_the_durable_agent_migration_keeps_existing_data(tmp_path):
    with sqlite3.connect(tmp_path / "upgrade.db") as conn:
        conn.row_factory = sqlite3.Row
        migration = migrate_until(conn, DURABLE)
        legacy(conn)
        run(conn, migration)

        # messages survive, in order, and new kinds are allowed
        messages = conn.execute("SELECT id, kind, run_id, screenshot FROM agent_messages ORDER BY rowid").fetchall()
        assert [tuple(m) for m in messages] == [("m1", "user", None, None), ("m2", "text", None, None)]
        conn.execute("INSERT INTO agent_messages (id, sandbox_id, kind, content) VALUES ('m3', 's1', 'status', 'x')")

        # existing channels keep letting anyone in the channel command the sandbox
        assert conn.execute("SELECT allowed_users FROM agent_channels").fetchone()[0] == '["*"]'

        # saved keys moved into the vault, with the same ciphertext, and settings onto the workspace
        settings = {r["workspace_id"]: r for r in conn.execute("SELECT * FROM workspace_agent_settings")}
        assert set(settings) == {"w1", "w2"}
        key1 = conn.execute(
            "SELECT * FROM vault_secrets WHERE id = ?", (settings["w1"]["api_key_secret_id"],)
        ).fetchone()
        assert (key1["user_id"], key1["name"], key1["ciphertext"]) == ("u1", "AGENT_ANTHROPIC_API_KEY", "gAAAA-key-u1")
        key2 = conn.execute(
            "SELECT * FROM vault_secrets WHERE id = ?", (settings["w2"]["api_key_secret_id"],)
        ).fetchone()
        assert (key2["name"], key2["ciphertext"]) == ("AGENT_OPENAI_API_KEY_SAVED", "gAAAA-key-u2")
        assert conn.execute("SELECT ciphertext FROM vault_secrets WHERE id = 'taken'").fetchone()[0] == "other"
        assert (settings["w2"]["provider"], settings["w2"]["model"], settings["w2"]["api_base"]) == (
            "openai",
            "gpt",
            "http://proxy",
        )
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'agent_settings'").fetchone() is None

        # profiles become version 1, keeping the file named after the profile
        version = conn.execute("SELECT * FROM profile_versions").fetchone()
        assert (version["id"], version["profile_id"], version["version"], version["size_bytes"]) == ("p1", "p1", 1, 42)

        # rotation is counted from the last change
        assert (
            conn.execute("SELECT rotated_at FROM vault_secrets WHERE id = 'vs1'").fetchone()[0] == "2026-01-02 03:04:05"
        )

        # one unfinished run per sandbox
        conn.execute(
            "INSERT INTO agent_runs (id, sandbox_id, user_id, source, max_steps, max_seconds, max_tokens) "
            "VALUES ('r1', 's1', 'u1', 'web', 1, 1, 1)"
        )
        try:
            conn.execute(
                "INSERT INTO agent_runs (id, sandbox_id, user_id, source, max_steps, max_seconds, max_tokens) "
                "VALUES ('r2', 's1', 'u1', 'web', 1, 1, 1)"
            )
            raise AssertionError("a second active run was allowed")
        except sqlite3.IntegrityError:
            pass
        conn.execute("UPDATE agent_runs SET state = 'succeeded' WHERE id = 'r1'")
        conn.execute(
            "INSERT INTO agent_runs (id, sandbox_id, user_id, source, max_steps, max_seconds, max_tokens) "
            "VALUES ('r2', 's1', 'u1', 'web', 1, 1, 1)"
        )


def test_the_durable_agent_migration_rolls_back(tmp_path):
    with sqlite3.connect(tmp_path / "upgrade.db") as conn:
        migration = migrate_until(conn, DURABLE)
        legacy(conn)
        run(conn, migration)
        conn.execute("INSERT INTO agent_messages (id, sandbox_id, kind, content) VALUES ('m3', 's1', 'status', 'x')")
        run(conn, migration, "Down")
        assert conn.execute("SELECT kind FROM agent_messages WHERE id = 'm3'").fetchone()[0] == "error"
        assert (
            conn.execute("SELECT api_key_ref FROM agent_settings WHERE user_id = 'u1'").fetchone()[0] == "gAAAA-key-u1"
        )
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'agent_runs'").fetchone() is None
