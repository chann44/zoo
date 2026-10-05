import os
import re
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

# configuration is read at import time, so it has to be in place before any server module loads
WORK = Path(tempfile.mkdtemp(prefix="zoo-tests-"))
ADMIN_EMAIL = "admin@example.com"
os.environ.update(
    JWT_SECRET="test-jwt-secret-that-is-at-least-32-bytes",
    DB_PATH=str(WORK / "zoo.db"),
    PROFILE_DIR=str(WORK / "profiles"),
    BACKUP_DIR=str(WORK / "backups"),
    ADMIN_EMAILS=ADMIN_EMAIL,
    CORS_ORIGINS="http://localhost:3000",
)
for name in (
    "ZOO_SECRETS_KEY",
    "ZOO_SECRETS_KEY_PREVIOUS",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "SLACK_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "WHATSAPP_TOKEN",
    "ZOO_DOMAIN",
    "ZOO_PUBLIC_IP",
):
    os.environ.pop(name, None)

from fastapi.testclient import TestClient

from db.connection import db_manager
from tests.fake_runtime import FakeRuntime

MIGRATIONS = Path(__file__).parent.parent / "db" / "migrations"
TEMPLATE = WORK / "template.db"
PASSWORD = "correct-horse"


def migrate(path: Path):
    """Applies the goose Up sections in order, the same schema `goose up` builds."""
    with sqlite3.connect(path) as conn:
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            up = migration.read_text().split("-- +goose Down")[0]
            conn.executescript(re.sub(r"^-- \+goose .*$", "", up, flags=re.MULTILINE))


migrate(TEMPLATE)
_fake = FakeRuntime()
_patches = pytest.MonkeyPatch()
_fake.install(_patches)

from server.limits import LIMITS
from server.server import Server

_server = Server()
# lifecycle jobs run in the request that queued them, so a test sees their outcome right away
_server.sandbox_api.jobs.inline = True


def pytest_unconfigure(config):
    _patches.undo()
    shutil.rmtree(WORK, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Every test starts from an empty, fully migrated database and a clean fake runtime."""
    path = tmp_path / "zoo.db"
    shutil.copy(TEMPLATE, path)
    db_manager.init_db(str(path))
    _fake.reset()
    for limit in LIMITS:
        limit.reset()
    yield path


@pytest.fixture
def fake() -> FakeRuntime:
    return _fake


@pytest.fixture
def zoo() -> Server:
    return _server


@pytest.fixture
def client() -> TestClient:
    return TestClient(_server.app)


def signup(client: TestClient, email: str) -> dict[str, str]:
    res = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "name": email.split("@")[0]})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def alice(client) -> dict[str, str]:
    return signup(client, "alice@example.com")


@pytest.fixture
def bob(client) -> dict[str, str]:
    return signup(client, "bob@example.com")


@pytest.fixture
def admin(client) -> dict[str, str]:
    return signup(client, ADMIN_EMAIL)


@pytest.fixture
def make_sandbox(client, alice):
    """Creates a sandbox and returns it once the (synchronous, faked) boot has finished."""

    def make(kind: str = "desktop", headers: dict | None = None, **body) -> dict:
        headers = headers or alice
        res = client.post("/sandboxes", json={"kind": kind, **body}, headers=headers)
        assert res.status_code == 201, res.text
        return client.get(f"/sandboxes/{res.json()['id']}", headers=headers).json()

    return make


@pytest.fixture
def sandbox(make_sandbox) -> dict:
    return make_sandbox()


def runtime_of(sandbox_id: str) -> str:
    with db_manager.session() as db:
        return db.get_sandbox(id=sandbox_id).runtime_id


@pytest.fixture(scope="session")
def live_url():
    """The app served over a real socket with its lifespan running, for the SDK and MCP clients."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_server.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
