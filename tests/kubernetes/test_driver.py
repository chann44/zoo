"""The Kubernetes driver (server/kube.py) against a real cluster: pods, home claims, exec, archives, the paused warm
pool, snapshots, moving a home to a Docker host, and the requirements check.

Runs when ZOO_TEST_KUBERNETES names a namespace to use (it is created and removed), with the cluster from the
kubeconfig. CI runs it on kind with the runc RuntimeClass; the nightly run uses a cluster with Kata:

    kind create cluster && kubectl apply -f tests/kubernetes/runtimeclass-runc.yaml
    docker build -t zoo-kube-test:1 tests/kubernetes && kind load docker-image zoo-kube-test:1
    ZOO_TEST_KUBERNETES=zoo-test ZOO_TEST_RUNTIME_CLASS=runc uv run pytest tests/kubernetes

ZOO_TEST_IMAGE names the image (zoo-kube-test:1, tests/kubernetes/Dockerfile) and ZOO_TEST_DOCKER a Docker to move a
home to (the local one by default; set it empty to skip)."""

import io
import os
import tarfile
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from server import docker, kube

NAMESPACE = os.environ.get("ZOO_TEST_KUBERNETES", "")
IMAGE = os.environ.get("ZOO_TEST_IMAGE", "zoo-kube-test:1")
DOCKER = os.environ.get("ZOO_TEST_DOCKER", "unix:///var/run/docker.sock")

pytestmark = pytest.mark.skipif(not NAMESPACE, reason="set ZOO_TEST_KUBERNETES to run against a cluster")


@pytest.fixture(scope="module", autouse=True)
def namespace():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(kube, "NAMESPACE", NAMESPACE)
    monkeypatch.setattr(kube, "EGRESS_NAMESPACE", NAMESPACE)
    monkeypatch.setattr(kube, "RUNTIME_CLASS", os.environ.get("ZOO_TEST_RUNTIME_CLASS", "kata"))
    monkeypatch.setattr(kube, "HELPER_IMAGE", IMAGE)
    monkeypatch.setattr(kube, "HOME_SIZE", "1Gi")
    monkeypatch.setattr(kube, "START_TIMEOUT", 300)
    with pytest.raises(kube.NotFound):
        kube.api.get(f"/api/v1/namespaces/{NAMESPACE}")
    kube.api.request("POST", "/api/v1/namespaces", {"metadata": {"name": NAMESPACE}})
    yield
    kube.api.request("DELETE", f"/api/v1/namespaces/{NAMESPACE}")
    monkeypatch.undo()


@pytest.fixture
def real(monkeypatch, fake):
    """The real Docker backend functions in place of the test suite's fake runtime."""
    for name, original in fake.originals.items():
        monkeypatch.setattr(docker, name, original)


def tar(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def untar(chunks) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(b"".join(chunks))) as archive:
        return {m.name: archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}  # type: ignore[union-attr]


def test_requirements_check():
    checks = {c["name"]: c for c in kube.check(probe=True)}
    for name in ("api", "namespace", "runtime class", "nodes", "storage"):
        assert checks[name]["ok"], checks[name]
    probes = [c for n, c in checks.items() if n.startswith("node ")]
    assert probes and all(c["ok"] for c in probes), probes
    # nothing of the probe is left behind
    assert not kube.api.get(kube.pods_path(NAMESPACE), labelSelector="app.kubernetes.io/component=probe")["items"]


def test_a_sandbox_pod_runs_and_answers_like_a_container(real):
    sandbox_id = str(uuid.uuid4())
    rid, host, port = docker.run_container(
        kube.pod_name(sandbox_id), IMAGE, sandbox_id, {"ZOO_SANDBOX_ID": sandbox_id}, None, desktop=False
    )
    try:
        assert rid == f"k8s:{NAMESPACE}/zoo-sandbox-{sandbox_id}" and (host, port) == (None, None)
        assert docker.is_running(rid)
        pod: Any = docker.container(rid)
        # the image's home was copied into the new claim, owned by the sandbox user
        result = pod.exec_run(["sh", "-c", "test -f ~/.bashrc && echo seeded; whoami; stat -c %U ~"], user="zoo")
        assert result.exit_code == 0 and result.output == b"seeded\nzoo\nzoo\n", result
        result = pod.exec_run(
            ["sh", "-c", 'echo "$A $PWD"; echo err >&2; exit 3'], environment={"A": "1"}, workdir="/tmp", demux=True
        )
        assert result.exit_code == 3 and result.output == (b"1 /tmp\n", b"err\n")
        assert pod.exec_run("whoami", user="root").output == b"root\n"

        # archives, both ways, binary-safe and bigger than one websocket frame
        blob = os.urandom(300_000)
        docker.import_dir(rid, "/home/zoo/.config/app", tar({"state.bin": blob, "a.txt": b"hello"}))
        files = untar([docker.export_dir(rid, "/home/zoo/.config/app")])
        assert files["app/state.bin"] == blob and files["app/a.txt"] == b"hello"
        assert pod.exec_run(["stat", "-c", "%U", "/home/zoo/.config/app/a.txt"]).output == b"zoo\n"
        docker.write_secrets(rid, {"TOKEN": "s3cret"})
        assert pod.exec_run(["cat", "/run/zoo/env.json"]).output == b'{"TOKEN": "s3cret"}'

        # a retried boot adopts the running pod rather than starting another
        uid = pod.obj["metadata"]["uid"]
        again, _, _ = docker.run_container(kube.pod_name(sandbox_id), IMAGE, sandbox_id, {}, None, desktop=False)
        assert again == rid and kube.container(rid).obj["metadata"]["uid"] == uid

        # the warm pool's pause: every process but init stops, and wakes again
        pod.exec_run(["sh", "-c", "nohup sleep 300 >/dev/null 2>&1 &"])
        state = "for p in /proc/[0-9]*; do [ $(cat $p/comm) = sleep ] && [ ${p#/proc/} != 1 ] && cut -d' ' -f3 $p/stat; done"
        kube.pause(rid)
        assert b"T" in pod.exec_run(["sh", "-c", state]).output
        kube.resume(rid)
        assert b"T" not in pod.exec_run(["sh", "-c", state]).output

        assert kube.free_memory(ttl=0) is not None
        assert kube.host_info()["ContainersRunning"] >= 1
    finally:
        docker.remove_container(rid)
        assert not docker.is_running(rid)
        docker.remove_volume(sandbox_id)
    kube.gone(kube.claims_path(NAMESPACE, kube.claim_name(sandbox_id)), 60)


def test_snapshots_restore_a_stopped_sandbox(real):
    sandbox_id, snapshot_id = str(uuid.uuid4()), str(uuid.uuid4())
    rid, _, _ = docker.run_container(kube.pod_name(sandbox_id), IMAGE, sandbox_id, {}, None, desktop=False)
    try:
        pod: Any = docker.container(rid)
        pod.exec_run(["sh", "-c", "echo before > /home/zoo/note"], user="zoo")
        # taken while the sandbox runs, on its node
        assert docker.snapshot(sandbox_id, snapshot_id, None) > 0
        pod.exec_run(["sh", "-c", "echo after > /home/zoo/note"], user="zoo")
        docker.remove_container(rid)
        docker.restore_snapshot(sandbox_id, snapshot_id, None)
        rid, _, _ = docker.run_container(kube.pod_name(sandbox_id), IMAGE, sandbox_id, {}, None, desktop=False)
        assert docker.container(rid).exec_run(["cat", "/home/zoo/note"]).output == b"before\n"
        docker.remove_snapshot(snapshot_id, None)
        kube.gone(kube.claims_path(NAMESPACE, docker.snapshot_name(snapshot_id)), 60)
        wait_helpers_gone()
    finally:
        docker.remove_container(rid)
        docker.remove_volume(sandbox_id)


def wait_helpers_gone():
    deadline = time.monotonic() + 60
    while kube.api.get(kube.pods_path(NAMESPACE), labelSelector="app.kubernetes.io/component=helper")["items"]:
        assert time.monotonic() < deadline, "helper pods left behind"
        time.sleep(1)


@pytest.mark.skipif(not DOCKER, reason="no Docker to move to")
def test_a_home_moves_from_the_cluster_to_a_docker_host(real):
    sandbox_id = str(uuid.uuid4())
    rid, _, _ = docker.run_container(kube.pod_name(sandbox_id), IMAGE, sandbox_id, {}, None, desktop=False)
    docker.container(rid).exec_run(["sh", "-c", "echo moved > /home/zoo/note"], user="zoo")
    docker.remove_container(rid)
    host = SimpleNamespace(id=f"test-{sandbox_id}", docker_url=DOCKER)
    client = docker.connect(host.id, host.docker_url)
    try:
        client.images.get(IMAGE)
    except Exception:
        pytest.skip(f"{IMAGE} isn't on the Docker host")
    try:
        docker.copy_volume(sandbox_id, None, host, IMAGE)
        out = client.containers.run(
            IMAGE,
            ["cat", "/home/zoo/note"],
            volumes={docker.volume_name(sandbox_id): {"bind": "/home/zoo"}},
            remove=True,
        )
        assert out == b"moved\n"
        # the source claim goes once the copy is done
        kube.gone(kube.claims_path(NAMESPACE, kube.claim_name(sandbox_id)), 60)
    finally:
        docker.remove_volume(sandbox_id, host)
        docker.remove_volume(sandbox_id)
