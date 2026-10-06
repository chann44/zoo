import pytest
from fastapi import HTTPException

from db.connection import db_manager
from db.generated.query import CreateProfileParams
from server.sandbox_api import AUTO, CreateSandboxRequest
from tests.test_sandboxes import add_server


@pytest.fixture
def user(alice):
    with db_manager.session() as db:
        return db.get_user_by_email(email="alice@example.com")


def place(zoo, user, server_id, kind="desktop"):
    with db_manager.session() as db:
        return zoo.sandbox_api.place(server_id, user, db, kind)


def create(zoo, user, kind, server_id=None):
    with db_manager.session() as db:
        return zoo.sandbox_api.create(CreateSandboxRequest(kind=kind, server_id=server_id), user, db)


def test_linux_defaults_to_local(zoo, user):
    assert place(zoo, user, None) is None


def test_explicit_server_must_belong_to_user(zoo, user, bob):
    mine = add_server("alice@example.com")
    theirs = add_server("bob@example.com", name="other")
    assert place(zoo, user, mine) == mine
    with pytest.raises(HTTPException) as e:
        place(zoo, user, theirs)
    assert e.value.status_code == 404


def test_linux_server_cannot_host_vms(zoo, user):
    linux = add_server("alice@example.com")
    with pytest.raises(HTTPException) as e:
        place(zoo, user, linux, "windows")
    assert e.value.status_code == 400


def test_auto_prefers_the_least_loaded_host(zoo, client, alice, make_sandbox, user):
    remote = add_server("alice@example.com")
    assert place(zoo, user, AUTO) is None
    make_sandbox()
    assert place(zoo, user, AUTO) == remote
    make_sandbox(server_id=remote)
    assert place(zoo, user, AUTO) is None


def test_vms_need_a_server(zoo, user):
    for kind in ("macos", "windows"):
        with pytest.raises(HTTPException) as e:
            place(zoo, user, None, kind)
        assert e.value.status_code == 400


def test_vm_placement_balances_and_caps(zoo, user, monkeypatch):
    monkeypatch.setattr("server.windows.MAX_VMS", 1)
    a = add_server("alice@example.com", "windows", "a")
    b = add_server("alice@example.com", "windows", "b")
    first = place(zoo, user, AUTO, "windows")
    create(zoo, user, "windows", first)
    second = place(zoo, user, None, "windows")
    assert {first, second} == {a, b}
    create(zoo, user, "windows", second)
    with pytest.raises(HTTPException) as e:
        place(zoo, user, None, "windows")
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        place(zoo, user, "missing", "windows")
    assert e.value.status_code == 404


def test_vm_sandboxes_reject_profiles_from_another_os(zoo, user):
    add_server("alice@example.com", "macos")
    with db_manager.session() as db:
        db.create_profile(
            CreateProfileParams(
                id="p", user_id=user.id, name="work", app="firefox", size_bytes=0, encrypted=1, platform="linux"
            )
        )
    with db_manager.session() as db, pytest.raises(HTTPException) as e:
        zoo.sandbox_api.create(CreateSandboxRequest(kind="macos", profile_ids=["p"]), user, db)
    assert e.value.status_code == 400 and "linux" in e.value.detail
