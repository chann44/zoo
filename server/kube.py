"""Linux sandboxes on Kubernetes: one Pod per sandbox, with a PersistentVolumeClaim for /home/zoo, under a
RuntimeClass (Kata Containers by default, so each sandbox is its own VM) and zoo-guest inside, as on Docker.

ZOO_KUBERNETES_NAMESPACE turns it on: the sandboxes Zoo runs on "this machine" then run as pods in that namespace,
and servers added under Servers keep working as before. Zoo talks to the Kubernetes API itself, from inside the
cluster with its service account or from outside with a kubeconfig (KUBECONFIG, ZOO_KUBERNETES_CONTEXT).

The rest of the API reaches pods the way it reaches Docker containers (server/docker.py): a pod's runtime id is
k8s:<namespace>/<pod>, `container()` returns a Pod with docker-py's exec_run, get_archive and put_archive (run
through the pods/exec API), and `cluster` stands in for a Docker client where volumes and helper containers are
concerned, so snapshots and moves between hosts work unchanged. Pods have no pause, so the warm pool keeps its pods
running with every process stopped (SIGSTOP), and wakes them when a sandbox claims one."""

import base64
import contextlib
import json
import os
import re
import shlex
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from collections.abc import Iterator
from typing import Any, NamedTuple

import docker.errors
import httpx
import yaml
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from server.sizes import DEFAULT as DEFAULT_SIZE
from server.sizes import Size

NAMESPACE = os.environ.get("ZOO_KUBERNETES_NAMESPACE", "")
RUNTIME_CLASS = os.environ.get("ZOO_KUBERNETES_RUNTIME_CLASS", "kata")
STORAGE_CLASS = os.environ.get("ZOO_KUBERNETES_STORAGE_CLASS", "")
HOME_SIZE = os.environ.get("ZOO_KUBERNETES_HOME_SIZE", "10Gi")
# with a VolumeSnapshotClass, snapshots are CSI volume snapshots; without one, copies into a new claim
SNAPSHOT_CLASS = os.environ.get("ZOO_KUBERNETES_SNAPSHOT_CLASS", "")
EGRESS_NAMESPACE = os.environ.get("ZOO_KUBERNETES_EGRESS_NAMESPACE", "") or NAMESPACE
EGRESS_SELECTOR = os.environ.get("ZOO_KUBERNETES_EGRESS_SELECTOR", "app.kubernetes.io/component=egress")
PULL_SECRET = os.environ.get("ZOO_KUBERNETES_IMAGE_PULL_SECRET", "")
HELPER_IMAGE = os.environ.get("ZOO_KUBERNETES_HELPER_IMAGE", "")
# the requirements check starts this under the RuntimeClass on each node: running proves the runtime (and, for
# Kata, KVM) works there. The kubelet's own sandbox image, so nodes already have it.
PROBE_IMAGE = os.environ.get("ZOO_KUBERNETES_PROBE_IMAGE", "registry.k8s.io/pause:3.10")
START_TIMEOUT = float(os.environ.get("ZOO_KUBERNETES_START_TIMEOUT", "600"))
# what a sandbox gets, as on Docker (docker.run_container)
# the share of a sandbox's CPUs its pod requests (the default 2 CPUs request 500m)
CPU_REQUEST_SHARE = 0.25
SHM = "1Gi"
HOME = "/home/zoo"
CONTAINER = "sandbox"
EGRESS_DIR = "/run/zoo-egress"
PREFIX = "k8s:"
LABELS = {"app.kubernetes.io/managed-by": "zoo", "app.kubernetes.io/part-of": "zoo"}
# waiting reasons that won't fix themselves
STUCK = {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError", "CreateContainerError"}
CHUNK = 64 * 1024


def enabled() -> bool:
    return bool(NAMESPACE)


def owns(runtime_id: str | None) -> bool:
    return bool(runtime_id) and str(runtime_id).startswith(PREFIX)


def runtime_id(namespace: str, name: str) -> str:
    return f"{PREFIX}{namespace}/{name}"


def parse_id(rid: str) -> tuple[str, str]:
    namespace, _, name = rid[len(PREFIX) :].partition("/")
    return namespace, name


def pod_name(sandbox_id: str) -> str:
    return f"zoo-sandbox-{sandbox_id}"


def claim_name(sandbox_id: str) -> str:
    # the Docker volume's name (docker.volume_name), so helpers address both the same way
    return f"zoo-home-{sandbox_id}"


class ExecResult(NamedTuple):
    """docker-py's exec_run result: output is bytes, or a (stdout, stderr) pair with demux."""

    exit_code: int
    output: Any


class KubeError(RuntimeError):
    def __init__(self, status: int, message: str, reason: str = ""):
        super().__init__(message)
        self.status = status
        self.reason = reason


class NotFound(KubeError, docker.errors.NotFound):
    """A missing object; also docker-py's NotFound, which the Docker paths already handle."""

    def __init__(self, status: int, message: str, reason: str = ""):
        KubeError.__init__(self, status, message, reason)
        self.response = None
        self.explanation = message

    def __str__(self) -> str:
        return str(self.args[0])


# --- the API client ---


def quantity(value: str | float | None) -> float:
    """A Kubernetes quantity (2Gi, 500m, 1e3) as a number of its base unit."""
    if value is None:
        return 0.0
    text = str(value).strip()
    match = re.fullmatch(r"([0-9.]+(?:[eE][-+]?[0-9]+)?)([a-zA-Z]*)", text)
    if not match:
        raise ValueError(f"not a quantity: {value!r}")
    number, suffix = float(match.group(1)), match.group(2)
    binary = {"Ki": 1, "Mi": 2, "Gi": 3, "Ti": 4, "Pi": 5, "Ei": 6}
    decimal = {"n": -3, "u": -2, "m": -1, "": 0, "k": 1, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}
    if suffix in binary:
        return number * 1024 ** binary[suffix]
    if suffix in decimal:
        return number * 1000 ** decimal[suffix]
    raise ValueError(f"unknown quantity suffix in {value!r}")


class Api:
    """Requests to the Kubernetes API: in the cluster with the pod's service account, else with a kubeconfig."""

    def __init__(self):
        self.lock = threading.Lock()
        self.loaded = False
        self.server = ""
        self.context: ssl.SSLContext | None = None
        self.token_file = ""
        self.token = ""
        self.exec_plugin: dict | None = None
        self.token_expires = 0.0
        self.in_cluster = False
        self.http: httpx.Client | None = None

    def load(self):
        with self.lock:
            if self.loaded:
                return
            token_file = "/var/run/secrets/kubernetes.io/serviceaccount/token"
            if os.environ.get("KUBERNETES_SERVICE_HOST") and os.path.exists(token_file):
                self.in_cluster_config(token_file)
            else:
                self.kubeconfig()
            self.http = httpx.Client(base_url=self.server, verify=self.context or False, timeout=30)
            self.loaded = True

    def in_cluster_config(self, token_file: str):
        host, port = os.environ["KUBERNETES_SERVICE_HOST"], os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.server = f"https://{'[' + host + ']' if ':' in host else host}:{port}"
        self.context = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        # bound tokens rotate, so it is read again on each request
        self.token_file = token_file
        self.in_cluster = True

    def kubeconfig(self):
        path = (os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")).split(os.pathsep)[0]
        if not os.path.exists(path):
            raise RuntimeError("no Kubernetes access: not in a cluster, and no kubeconfig at " + path)
        with open(path) as f:
            config = yaml.safe_load(f) or {}
        base = os.path.dirname(os.path.abspath(path))
        name = os.environ.get("ZOO_KUBERNETES_CONTEXT") or config.get("current-context")
        context = next((c["context"] for c in config.get("contexts") or [] if c.get("name") == name), None)
        if context is None:
            raise RuntimeError(f"kubeconfig {path} has no context {name!r}")
        cluster = next(c["cluster"] for c in config.get("clusters") or [] if c.get("name") == context.get("cluster"))
        user = next((u["user"] for u in config.get("users") or [] if u.get("name") == context.get("user")), {}) or {}
        self.server = cluster["server"].rstrip("/")
        if self.server.startswith("https://"):
            if cluster.get("insecure-skip-tls-verify"):
                self.context = ssl.create_default_context()
                self.context.check_hostname = False
                self.context.verify_mode = ssl.CERT_NONE
            else:
                self.context = ssl.create_default_context(**ca_of(cluster, base))
            cert, key = file_of(user, "client-certificate", base), file_of(user, "client-key", base)
            if cert and key:
                self.context.load_cert_chain(cert, key)
        self.token = user.get("token") or ""
        if user.get("tokenFile"):
            self.token_file = os.path.join(base, user["tokenFile"])
        self.exec_plugin = user.get("exec")

    def bearer(self) -> str:
        if self.token_file:
            with open(self.token_file) as f:
                return f.read().strip()
        if self.exec_plugin is not None and time.time() >= self.token_expires:
            self.token, self.token_expires = run_exec_plugin(self.exec_plugin)
        return self.token

    def headers(self) -> dict[str, str]:
        token = self.bearer()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def request(
        self, method: str, path: str, body: Any = None, params: dict | None = None, timeout: float = 30
    ) -> dict:
        self.load()
        assert self.http is not None
        headers = self.headers()
        if method == "PATCH":
            headers["Content-Type"] = "application/merge-patch+json"
        response = self.http.request(method, path, json=body, params=params, headers=headers, timeout=timeout)
        if response.status_code >= 400:
            try:
                status = response.json()
            except ValueError:
                status = {"message": response.text}
            message = f"{method} {path}: {status.get('message') or response.reason_phrase}"
            error = NotFound if response.status_code == 404 else KubeError
            raise error(response.status_code, message, status.get("reason", ""))
        return response.json() if response.content else {}

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params or None)

    def exists(self, path: str) -> dict | None:
        try:
            return self.get(path)
        except NotFound:
            return None

    def open_exec(self, url: str, where: str, attempts: int = 3):
        """The exec websocket. A handshake that gets no answer is tried again: the command hasn't started then."""
        for attempt in range(attempts):
            try:
                return connect(
                    url,
                    ssl=self.context if url.startswith("wss://") else None,
                    additional_headers=self.headers(),
                    subprotocols=["v4.channel.k8s.io"],  # type: ignore[list-item]
                    max_size=None,
                    open_timeout=10,
                )
            except TimeoutError:
                if attempt == attempts - 1:
                    raise KubeError(0, f"exec in {where}: the API server didn't answer") from None
            except WebSocketException as e:
                if "404" in str(e):
                    raise NotFound(404, f"pod {where} not found") from e
                raise KubeError(0, f"exec in {where}: {e}") from e
        raise AssertionError("unreachable")

    def exec_stream(
        self, namespace: str, pod: str, argv: list[str], container: str | None = None, stdin: bytes | None = None
    ) -> Iterator[tuple[int, bytes]]:
        """Runs argv in the pod; yields (1, stdout) and (2, stderr) chunks as they arrive, then (0, exit code)."""
        self.load()
        params = [("command", a) for a in argv] + [("stdout", "true"), ("stderr", "true")]
        if stdin is not None:
            params.append(("stdin", "true"))
        if container:
            params.append(("container", container))
        url = self.server.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url += f"/api/v1/namespaces/{namespace}/pods/{pod}/exec?" + urllib.parse.urlencode(params)
        connection = self.open_exec(url, f"{namespace}/{pod}")
        writer = None
        if stdin is not None:
            # the command reads exactly len(stdin) bytes: v4 can't close stdin, so nothing waits for its end
            def feed():
                with contextlib.suppress(WebSocketException, OSError):
                    for i in range(0, len(stdin), CHUNK):
                        connection.send(b"\x00" + stdin[i : i + CHUNK])

            writer = threading.Thread(target=feed, daemon=True)
            writer.start()
        status = None
        try:
            for message in connection:
                frame = message if isinstance(message, bytes) else message.encode()
                if len(frame) < 2:
                    continue
                channel, data = frame[0], frame[1:]
                if channel in (1, 2):
                    yield channel, data
                elif channel == 3:
                    status = json.loads(data)
        except WebSocketException as e:
            raise KubeError(0, f"exec in {namespace}/{pod} was cut off: {e}") from e
        finally:
            connection.close()
            if writer is not None:
                writer.join(5)
        yield 0, str(exit_code(status, f"{namespace}/{pod}")).encode()

    def exec(
        self, namespace: str, pod: str, argv: list[str], container: str | None = None, stdin: bytes | None = None
    ) -> tuple[int, bytes, bytes, bytes]:
        """Runs argv in the pod: exit code, stdout, stderr, and both as they interleaved."""
        out, err, both = bytearray(), bytearray(), bytearray()
        code = 0
        for channel, data in self.exec_stream(namespace, pod, argv, container, stdin):
            if channel == 0:
                code = int(data)
                continue
            (out if channel == 1 else err).extend(data)
            both.extend(data)
        return code, bytes(out), bytes(err), bytes(both)


def ca_of(cluster: dict, base: str) -> dict:
    if cluster.get("certificate-authority-data"):
        return {"cadata": base64.b64decode(cluster["certificate-authority-data"]).decode()}
    if cluster.get("certificate-authority"):
        return {"cafile": os.path.join(base, cluster["certificate-authority"])}
    return {}


def file_of(user: dict, key: str, base: str) -> str | None:
    """A kubeconfig credential as a file path, writing inline (-data) values to a private temporary file."""
    if user.get(f"{key}-data"):
        fd, path = tempfile.mkstemp(prefix="zoo-kube-")
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(user[f"{key}-data"]))
        return path
    if user.get(key):
        return os.path.join(base, user[key])
    return None


def run_exec_plugin(plugin: dict) -> tuple[str, float]:
    """A token from a kubeconfig exec plugin (aws eks get-token, gke-gcloud-auth-plugin, kubelogin)."""
    env = {**os.environ, **{e["name"]: e["value"] for e in plugin.get("env") or []}}
    env["KUBERNETES_EXEC_INFO"] = json.dumps(
        {"apiVersion": plugin.get("apiVersion"), "kind": "ExecCredential", "spec": {"interactive": False}}
    )
    result = subprocess.run(
        [plugin["command"], *(plugin.get("args") or [])],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubeconfig exec plugin {plugin['command']} failed: {result.stderr.strip()[-300:]}")
    status = json.loads(result.stdout).get("status") or {}
    expires = status.get("expirationTimestamp")
    until = time.time() + 300
    if expires:
        from datetime import datetime

        until = datetime.fromisoformat(expires).timestamp() - 60
    return status.get("token", ""), until


def exit_code(status: dict | None, where: str) -> int:
    if status is None:
        raise KubeError(0, f"exec in {where} ended without an exit status")
    if status.get("status") == "Success":
        return 0
    if status.get("reason") == "NonZeroExitCode":
        for cause in (status.get("details") or {}).get("causes") or []:
            if cause.get("reason") == "ExitCode":
                return int(cause.get("message", 1))
        return 1
    raise KubeError(0, f"exec in {where}: {status.get('message') or status}")


api = Api()


def pods_path(namespace: str, name: str = "") -> str:
    return f"/api/v1/namespaces/{namespace}/pods" + (f"/{name}" if name else "")


def claims_path(namespace: str, name: str = "") -> str:
    return f"/api/v1/namespaces/{namespace}/persistentvolumeclaims" + (f"/{name}" if name else "")


def snapshots_path(namespace: str, name: str = "") -> str:
    return f"/apis/snapshot.storage.k8s.io/v1/namespaces/{namespace}/volumesnapshots" + (f"/{name}" if name else "")


# --- pods as docker-py containers ---


def user_argv(argv: list[str], user: str | None, environment: dict | None, workdir: str | None) -> list[str]:
    """docker exec's user, environment and working directory for a pods/exec command, which runs as the
    container's user (root, in the sandbox images) in its working directory."""
    if environment:
        argv = ["env", *[f"{k}={v}" for k, v in environment.items()], *argv]
    if user and user not in ("root", "0"):
        argv = ["runuser", "-u", user, "--", *argv]
    if workdir:
        argv = ["sh", "-c", 'cd "$1" && shift && exec "$@"', "sh", workdir, *argv]
    return argv


class Pod:
    """A pod, with the parts of docker-py's Container the API uses."""

    def __init__(self, namespace: str, name: str, obj: dict | None = None):
        self.namespace = namespace
        self.name = name
        self.obj = obj if obj is not None else api.get(pods_path(namespace, name))

    @property
    def id(self) -> str:
        return runtime_id(self.namespace, self.name)

    def reload(self):
        self.obj = api.get(pods_path(self.namespace, self.name))

    @property
    def labels(self) -> dict[str, str]:
        return self.obj["metadata"].get("labels") or {}

    @property
    def node(self) -> str:
        return self.obj["spec"].get("nodeName") or ""

    @property
    def ip(self) -> str:
        return self.obj.get("status", {}).get("podIP") or ""

    def container_state(self) -> dict:
        for status in self.obj.get("status", {}).get("containerStatuses") or []:
            if status.get("name") == CONTAINER:
                return status.get("state") or {}
        return {}

    @property
    def status(self) -> str:
        if self.obj["metadata"].get("deletionTimestamp"):
            return "removing"
        if self.obj.get("status", {}).get("phase") == "Running" and "running" in self.container_state():
            return "running"
        return "exited" if self.obj.get("status", {}).get("phase") in ("Succeeded", "Failed") else "created"

    @property
    def attrs(self) -> dict:
        spec = next(
            (c for c in self.obj["spec"]["containers"] if c["name"] == CONTAINER), self.obj["spec"]["containers"][0]
        )
        addrs = [a["ip"] for a in self.obj.get("status", {}).get("podIPs") or [] if a.get("ip")] or [self.ip]
        return {
            "Config": {
                "Env": [f"{e['name']}={e.get('value', '')}" for e in spec.get("env") or []],
                "Image": spec["image"],
            },
            "NetworkSettings": {
                "Networks": {
                    "pod": {"IPAddress": addrs[0], "GlobalIPv6Address": next((a for a in addrs if ":" in a), "")}
                }
            },
        }

    def exec_run(
        self,
        cmd,
        user: str | None = None,
        environment: dict | None = None,
        workdir: str | None = None,
        demux: bool = False,
        **_: Any,
    ) -> ExecResult:
        argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        code, out, err, both = api.exec(
            self.namespace, self.name, user_argv(argv, user, environment, workdir), self.container
        )
        return ExecResult(code, (out or None, err or None) if demux else both)

    @property
    def container(self) -> str:
        names = [c["name"] for c in self.obj["spec"]["containers"]]
        return CONTAINER if CONTAINER in names else names[0]

    def get_archive(self, path: str) -> tuple[Iterator[bytes], dict]:
        """A tar of `path`, named by its last part like docker's, streamed as the pod sends it."""
        parent, base = os.path.split(path.rstrip("/") or "/")
        stream = api.exec_stream(
            self.namespace, self.name, ["tar", "-C", parent or "/", "-cf", "-", base], self.container
        )

        def chunks() -> Iterator[bytes]:
            errors = bytearray()
            for channel, data in stream:
                if channel == 1:
                    yield data
                elif channel == 2:
                    errors.extend(data)
                elif int(data) != 0:
                    raise RuntimeError(errors.decode(errors="replace").strip() or f"tar exited with {int(data)}")

        return chunks(), {"name": base}

    def put_archive(self, path: str, data: bytes) -> bool:
        script = f"head -c {len(data)} | tar -C {shlex.quote(path)} -xf -"
        code, _, err, _ = api.exec(self.namespace, self.name, ["sh", "-c", script], self.container, stdin=data)
        if code != 0:
            raise RuntimeError(err.decode(errors="replace").strip() or f"tar exited with {code}")
        return True

    def remove(self, force: bool = True):
        node = self.node
        delete_pod(self.namespace, self.name)
        if node and self.labels.get("app.kubernetes.io/component") == "sandbox":
            forget_policy(self.id, node)

    def start(self):
        """A helper pod is created when it starts, like a docker container from containers.create."""


class HelperPod(Pod):
    """A one-shot root pod with claims mounted, for work on a sandbox's home disk (docker.helper)."""

    def __init__(self, namespace: str, image: str, volumes: dict[str, dict], labels: dict[str, str]):
        self.namespace = namespace
        self.name = f"zoo-helper-{uuid.uuid4().hex[:12]}"
        self.image = image
        self.volumes = volumes
        self.extra_labels = labels
        self.obj = {}

    def start(self):
        node = ""
        mounts, volumes = [], []
        for i, (claim, mount) in enumerate(self.volumes.items()):
            ensure_claim(self.namespace, claim)
            mounts.append({"name": f"v{i}", "mountPath": mount["bind"]})
            volumes.append({"name": f"v{i}", "persistentVolumeClaim": {"claimName": claim}})
            # a claim a running sandbox holds can only be mounted on that sandbox's node
            if claim.startswith("zoo-home-"):
                sandbox = existing_pod(self.namespace, pod_name(claim[len("zoo-home-") :]))
                node = node or (sandbox.node if sandbox is not None else "")
        spec: dict = {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "terminationGracePeriodSeconds": 1,
            "containers": [
                {
                    "name": CONTAINER,
                    "image": self.image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["sleep", "21600"],
                    "securityContext": {"runAsUser": 0, "allowPrivilegeEscalation": False},
                    "volumeMounts": mounts,
                }
            ],
            "volumes": volumes,
        }
        if node:
            spec["affinity"] = on_node(node)
        pull_secrets(spec)
        labels = {**LABELS, "app.kubernetes.io/component": "helper", **sanitize_labels(self.extra_labels)}
        self.obj = api.request(
            "POST", pods_path(self.namespace), {"metadata": {"name": self.name, "labels": labels}, "spec": spec}
        )
        self.obj = wait_running(self.namespace, self.name, START_TIMEOUT)

    def remove(self, force: bool = True):
        delete_pod(self.namespace, self.name, wait=False)


def sanitize_labels(labels: dict[str, str]) -> dict[str, str]:
    return {re.sub(r"[^\w.-]", "-", k): re.sub(r"[^\w.-]", "-", v)[:63] for k, v in (labels or {}).items()}


class Claim:
    def __init__(self, namespace: str, name: str):
        self.namespace = namespace
        self.name = name

    def remove(self, force: bool = True):
        delete_claim(self.namespace, self.name)


class Pods:
    def get(self, name_or_id: str) -> Pod:
        if owns(name_or_id):
            return Pod(*parse_id(name_or_id))
        return Pod(NAMESPACE, name_or_id)

    def create(self, image: str, volumes: dict | None = None, labels: dict | None = None, **_: Any) -> HelperPod:
        return HelperPod(NAMESPACE, HELPER_IMAGE or image, volumes or {}, labels or {})


class Claims:
    def get(self, name: str) -> Claim:
        api.get(claims_path(NAMESPACE, name))
        return Claim(NAMESPACE, name)


class Cluster:
    """The cluster where a Docker client would be (docker.client_for), for volumes and helper containers."""

    def __init__(self):
        self.containers = Pods()
        self.volumes = Claims()


cluster = Cluster()


def container(rid: str) -> Pod:
    return Pod(*parse_id(rid))


def existing_pod(namespace: str, name: str) -> Pod | None:
    found = api.exists(pods_path(namespace, name))
    return Pod(namespace, name, found) if found is not None else None


def on_node(node: str) -> dict:
    """Affinity for one node. Unlike nodeName it goes through the scheduler, which binds a new claim that waits for
    its first consumer, and keeps the RuntimeClass's tolerations in play."""
    term = {"matchFields": [{"key": "metadata.name", "operator": "In", "values": [node]}]}
    return {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [term]}}}


def pull_secrets(spec: dict):
    if PULL_SECRET:
        spec["imagePullSecrets"] = [{"name": PULL_SECRET}]


def ensure_claim(namespace: str, name: str, source: dict | None = None, storage: str = HOME_SIZE):
    """Creates the claim unless it exists. Docker creates a volume the same way the first time it is mounted."""
    if api.exists(claims_path(namespace, name)) is not None:
        return
    spec: dict = {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": storage}}}
    if STORAGE_CLASS:
        spec["storageClassName"] = STORAGE_CLASS
    if source is not None:
        spec["dataSource"] = source
    body = {"metadata": {"name": name, "labels": {**LABELS, "app.kubernetes.io/component": "home"}}, "spec": spec}
    try:
        api.request("POST", claims_path(namespace), body)
    except KubeError as e:
        if e.status != 409:
            raise


def delete_claim(namespace: str, name: str, wait: bool = False, timeout: float = 120):
    with contextlib.suppress(NotFound):
        api.request("DELETE", claims_path(namespace, name))
    if wait:
        gone(claims_path(namespace, name), timeout)


def gone(path: str, timeout: float):
    deadline = time.monotonic() + timeout
    while api.exists(path) is not None:
        if time.monotonic() > deadline:
            raise RuntimeError(f"{path} is still there after {int(timeout)}s")
        time.sleep(0.5)


def delete_pod(namespace: str, name: str, wait: bool = True, timeout: float = 120):
    with contextlib.suppress(NotFound):
        api.request("DELETE", pods_path(namespace, name), {"gracePeriodSeconds": 5, "propagationPolicy": "Background"})
    if wait:
        gone(pods_path(namespace, name), timeout)


def wait_running(namespace: str, name: str, timeout: float) -> dict:
    """Waits for the pod's containers to run; fails early on what won't fix itself (a missing image)."""
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        obj = api.get(pods_path(namespace, name))
        status = obj.get("status") or {}
        phase = status.get("phase")
        if phase in ("Succeeded", "Failed"):
            raise RuntimeError(f"pod {name} stopped: {pod_problem(obj) or phase}")
        if phase == "Running" and all(
            "running" in (c.get("state") or {}) for c in status.get("containerStatuses") or []
        ):
            return obj
        problem = pod_problem(obj)
        if problem and any(reason in problem for reason in STUCK):
            raise RuntimeError(f"pod {name} can't start: {problem}")
        last = problem or last
        if time.monotonic() > deadline:
            raise RuntimeError(f"pod {name} didn't start within {int(timeout)}s" + (f": {last}" if last else ""))
        time.sleep(0.5)


def pod_problem(obj: dict) -> str:
    """Why a pod isn't running yet, as the scheduler or kubelet put it."""
    status = obj.get("status") or {}
    for condition in status.get("conditions") or []:
        if condition.get("type") == "PodScheduled" and condition.get("status") == "False":
            return f"{condition.get('reason')}: {condition.get('message')}"
    benign = (None, "PodInitializing", "ContainerCreating", "Completed")
    for c in [*(status.get("initContainerStatuses") or []), *(status.get("containerStatuses") or [])]:
        state = c.get("state") or {}
        waiting, terminated = state.get("waiting"), state.get("terminated")
        if waiting is not None and waiting.get("reason") not in benign:
            return f"{waiting.get('reason')}: {waiting.get('message') or ''}".strip(": ")
        if terminated is not None and (terminated.get("exitCode") or terminated.get("reason") not in benign):
            detail = terminated.get("message") or terminated.get("reason") or ""
            return f"{c.get('name')} exited with {terminated.get('exitCode')}" + (f": {detail}" if detail else "")
    return ""


# The image's /home/zoo, copied into a new home claim on its first mount, as Docker does for an empty volume
SEED_HOME = (
    'if [ -z "$(ls -A /seed | grep -v "^lost+found$")" ]; then cp -a /home/zoo/. /seed/; fi; '
    "chown zoo:zoo /seed && chmod 755 /seed"
)


def cpu_quantity(cpus: float) -> str:
    """CPUs as Kubernetes writes them: whole cores as a number, else millicores."""
    return str(int(cpus)) if cpus == int(cpus) else f"{round(cpus * 1000)}m"


def memory_quantity(mb: int) -> str:
    return f"{mb >> 10}Gi" if mb % 1024 == 0 else f"{mb}Mi"


def sandbox_pod(
    name: str, image: str, sandbox_id: str, env: dict[str, str], desktop: bool, size: Size = DEFAULT_SIZE
) -> dict:
    claim = claim_name(sandbox_id)
    home = {"name": "home", "mountPath": HOME}
    security = {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["NET_RAW"]}}
    container: dict = {
        "name": CONTAINER,
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "env": [{"name": k, "value": v} for k, v in env.items()],
        "resources": {
            # a fraction of the CPUs is reserved, so idle desktops pack densely; memory is reserved in full
            "requests": {"cpu": cpu_quantity(size.cpus * CPU_REQUEST_SHARE), "memory": memory_quantity(size.memory_mb)},
            "limits": {"cpu": cpu_quantity(size.cpus), "memory": memory_quantity(size.memory_mb)},
        },
        "securityContext": security,
        "volumeMounts": [home, {"name": "shm", "mountPath": "/dev/shm"}],
    }
    if desktop:
        container["ports"] = [{"name": "vnc", "containerPort": 6080}]
    spec: dict = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "terminationGracePeriodSeconds": 10,
        "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
        "initContainers": [
            {
                "name": "home",
                "image": image,
                "imagePullPolicy": "IfNotPresent",
                "command": ["sh", "-c", SEED_HOME],
                "securityContext": {**security, "runAsUser": 0},
                "volumeMounts": [{"name": "home", "mountPath": "/seed"}],
            }
        ],
        "containers": [container],
        "volumes": [
            {"name": "home", "persistentVolumeClaim": {"claimName": claim}},
            {"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": SHM}},
        ],
    }
    if RUNTIME_CLASS:
        spec["runtimeClassName"] = RUNTIME_CLASS
    pull_secrets(spec)
    labels = {**LABELS, "app.kubernetes.io/component": "sandbox", "zoo.dev/sandbox": sandbox_id}
    return {"metadata": {"name": name, "labels": labels}, "spec": spec}


def run_pod(
    name: str, image: str, sandbox_id: str, env: dict[str, str], desktop: bool = True, size: Size = DEFAULT_SIZE
):
    """Starts (or adopts) the sandbox's pod; returns its runtime id and where its desktop is, as
    docker.run_container does: the pod's address and websockify port, or no port when the guest tunnels it."""
    api.load()
    if desktop and not api.in_cluster and "ZOO_GUEST_TOKEN" not in env:
        raise RuntimeError(
            "from outside the cluster, desktops are reached through the sandbox's guest: set ZOO_GUEST_URL to an "
            "address pods can reach"
        )
    ensure_claim(NAMESPACE, claim_name(sandbox_id), storage=f"{size.disk_gb}Gi" if size.disk_gb else HOME_SIZE)
    found = existing_pod(NAMESPACE, name)
    if found is not None:
        spec = next(c for c in found.obj["spec"]["containers"] if c["name"] == CONTAINER)
        if found.status != "running" or found.labels.get("zoo.dev/sandbox") != sandbox_id or spec["image"] != image:
            # a pod left by an earlier attempt that can't be adopted
            delete_pod(NAMESPACE, name)
            found = None
    if found is None:
        api.request("POST", pods_path(NAMESPACE), sandbox_pod(name, image, sandbox_id, env, desktop, size))
        found = Pod(NAMESPACE, name, wait_running(NAMESPACE, name, START_TIMEOUT))
    if not desktop:
        return found.id, None, None
    if api.in_cluster:
        return found.id, found.ip, 6080
    return found.id, found.ip, None


def pause(rid: str):
    """Stops every process in a pooled sandbox but its init, so it holds its memory but uses no CPU."""
    namespace, name = parse_id(rid)
    code, _, err, _ = api.exec(namespace, name, ["sh", "-c", "kill -STOP -1"], CONTAINER)
    if code != 0:
        raise RuntimeError(f"couldn't pause {name}: {err.decode(errors='replace').strip()}")


def resume(rid: str):
    namespace, name = parse_id(rid)
    code, _, err, _ = api.exec(namespace, name, ["sh", "-c", "kill -CONT -1"], CONTAINER)
    if code != 0:
        raise RuntimeError(f"couldn't resume {name}: {err.decode(errors='replace').strip()}")


# --- snapshots through CSI ---


def csi_snapshot(sandbox_id: str, snapshot_id: str, name: str, timeout: float = 600) -> int:
    """A CSI VolumeSnapshot of the sandbox's home claim; returns its size."""
    body = {
        "apiVersion": "snapshot.storage.k8s.io/v1",
        "kind": "VolumeSnapshot",
        "metadata": {
            "name": name,
            "labels": {**LABELS, "zoo.dev/sandbox": sandbox_id, "zoo.dev/snapshot": snapshot_id},
        },
        "spec": {
            "volumeSnapshotClassName": SNAPSHOT_CLASS,
            "source": {"persistentVolumeClaimName": claim_name(sandbox_id)},
        },
    }
    api.request("POST", snapshots_path(NAMESPACE), body)
    deadline = time.monotonic() + timeout
    while True:
        status = api.get(snapshots_path(NAMESPACE, name)).get("status") or {}
        if status.get("error", {}).get("message"):
            remove_csi_snapshot(name)
            raise RuntimeError(f"the volume snapshot failed: {status['error']['message']}")
        if status.get("readyToUse"):
            return int(quantity(status.get("restoreSize") or 0))
        if time.monotonic() > deadline:
            remove_csi_snapshot(name)
            raise RuntimeError(f"the volume snapshot wasn't ready within {int(timeout)}s")
        time.sleep(1)


def restore_csi_snapshot(sandbox_id: str, name: str):
    """Replaces the home claim with one made from the snapshot. The sandbox's pod must be gone."""
    if api.exists(snapshots_path(NAMESPACE, name)) is None:
        raise RuntimeError("the volume snapshot is gone from the cluster")
    claim = claim_name(sandbox_id)
    delete_claim(NAMESPACE, claim, wait=True)
    ensure_claim(NAMESPACE, claim, {"apiGroup": "snapshot.storage.k8s.io", "kind": "VolumeSnapshot", "name": name})


def remove_csi_snapshot(name: str):
    with contextlib.suppress(NotFound):
        api.request("DELETE", snapshots_path(NAMESPACE, name))


# --- network policy through the node's egress daemon ---


def egress_daemon(node: str) -> Pod:
    found = (
        api.get(pods_path(EGRESS_NAMESPACE), labelSelector=EGRESS_SELECTOR, fieldSelector=f"spec.nodeName={node}").get(
            "items"
        )
        or []
    )
    running = [Pod(EGRESS_NAMESPACE, p["metadata"]["name"], p) for p in found]
    running = [p for p in running if p.obj.get("status", {}).get("phase") == "Running"]
    if not running:
        raise RuntimeError(f"the egress daemon is not running on node {node}")
    return running[0]


def apply_network(rid: str, default_action: str, allow_dns: bool, rules: list[tuple[str, str, str]]):
    """Hands the policy to the egress daemon on the sandbox's node (the same daemon as on a Docker host, run by the
    chart as a DaemonSet), which enforces it outside the sandbox."""
    from server import egress
    from server.docker import guest_endpoint, tar_file

    pod = container(rid)
    addrs = sorted({a for a in (pod.attrs["NetworkSettings"]["Networks"]["pod"].values()) if a})
    if not addrs:
        raise RuntimeError("the sandbox has no network address to apply the policy to")
    endpoint = guest_endpoint(rid)
    resolved = egress.addresses(endpoint[0]) if endpoint else []
    data = egress.policy(rid, addrs, default_action, allow_dns, rules, egress.always(endpoint, resolved))
    daemon = egress_daemon(pod.node)
    prune_policies(daemon)
    daemon.put_archive(EGRESS_DIR, tar_file(egress.file_name(rid), data))


def prune_policies(daemon: Pod):
    """Drops the policies of sandboxes no longer on the daemon's node, so a pod given the same address later
    doesn't inherit one."""
    from server import egress

    names = daemon.exec_run(["ls", EGRESS_DIR]).output.decode(errors="replace").split()
    pods = (
        api.get(
            pods_path(NAMESPACE),
            labelSelector="app.kubernetes.io/component=sandbox",
            fieldSelector=f"spec.nodeName={daemon.node}",
        ).get("items")
        or []
    )
    live = {egress.file_name(runtime_id(NAMESPACE, p["metadata"]["name"])) for p in pods}
    stale = [f"{EGRESS_DIR}/{n}" for n in names if n.endswith(".json") and n not in live]
    if stale:
        daemon.exec_run(["rm", "-f", *stale])


def forget_policy(rid: str, node: str):
    from server import egress

    # no daemon there means no policy either; a later prune catches anything left
    with contextlib.suppress(Exception):
        egress_daemon(node).exec_run(["rm", "-f", f"{EGRESS_DIR}/{egress.file_name(rid)}"])


# --- capacity and requirements ---


_free: dict[str, Any] = {}


def nodes_for_sandboxes() -> list[dict]:
    """Ready, schedulable nodes the RuntimeClass can place pods on."""
    selector: dict = {}
    if RUNTIME_CLASS:
        found = api.exists(f"/apis/node.k8s.io/v1/runtimeclasses/{RUNTIME_CLASS}")
        selector = ((found or {}).get("scheduling") or {}).get("nodeSelector") or {}
    out = []
    for node in api.get("/api/v1/nodes").get("items") or []:
        labels = node["metadata"].get("labels") or {}
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in node.get("status", {}).get("conditions") or []
        )
        if ready and not node["spec"].get("unschedulable") and all(labels.get(k) == v for k, v in selector.items()):
            out.append(node)
    return out


def free_memory(ttl: float = 10) -> int | None:
    """The most memory any one sandbox node has left unrequested, for placing against other hosts."""
    if _free and time.monotonic() - _free["at"] < ttl:
        return _free["bytes"]
    try:
        nodes = {n["metadata"]["name"]: quantity(n["status"]["allocatable"]["memory"]) for n in nodes_for_sandboxes()}
        pods = api.get("/api/v1/pods", fieldSelector="status.phase!=Succeeded,status.phase!=Failed").get("items") or []
    except Exception:
        return None
    for pod in pods:
        node = pod["spec"].get("nodeName")
        if node in nodes:
            requested = sum(
                quantity((c.get("resources") or {}).get("requests", {}).get("memory"))
                for c in pod["spec"]["containers"]
            )
            requested += quantity((pod["spec"].get("overhead") or {}).get("memory"))
            nodes[node] -= requested
    free = int(max(nodes.values())) if nodes else 0
    _free.update(at=time.monotonic(), bytes=free)
    return free


def host_info() -> dict:
    """The cluster, as the monitoring view shows a Docker host (docker info's names)."""
    nodes = nodes_for_sandboxes()
    first = nodes[0]["status"]["nodeInfo"] if nodes else {}
    running = (
        api.get(
            pods_path(NAMESPACE),
            labelSelector="app.kubernetes.io/component=sandbox",
            fieldSelector="status.phase=Running",
        ).get("items")
        or []
    )
    return {
        "Name": f"Kubernetes ({len(nodes)} node{'s' if len(nodes) != 1 else ''})",
        "OperatingSystem": first.get("osImage", "unknown"),
        "Architecture": first.get("architecture", "unknown"),
        "ServerVersion": first.get("kubeletVersion", "unknown"),
        "NCPU": int(sum(quantity(n["status"]["allocatable"]["cpu"]) for n in nodes)),
        "MemTotal": int(sum(quantity(n["status"]["allocatable"]["memory"]) for n in nodes)),
        "ContainersRunning": len(running),
        "Images": 0,
    }


def ping():
    api.get("/version")


def check(probe: bool = False) -> list[dict]:
    """What sandboxes on this cluster need, each as {name, ok, detail}. With `probe`, a pod under the RuntimeClass
    is started on every sandbox node, which proves the runtime works there (for Kata, that KVM does)."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        version = api.get("/version")
        add("api", True, f"Kubernetes {version.get('gitVersion', '')}")
    except Exception as e:
        add("api", False, str(e))
        return checks
    try:
        api.get(pods_path(NAMESPACE), limit="1")
        add("namespace", True, NAMESPACE)
    except Exception as e:
        add("namespace", False, f"{NAMESPACE}: {e}")
    handler = ""
    if RUNTIME_CLASS:
        found = api.exists(f"/apis/node.k8s.io/v1/runtimeclasses/{RUNTIME_CLASS}")
        handler = (found or {}).get("handler", "")
        add(
            "runtime class",
            found is not None,
            f"{RUNTIME_CLASS} (handler {handler})"
            if found
            else f"no RuntimeClass {RUNTIME_CLASS}: install Kata "
            "Containers (kata-deploy), or set ZOO_KUBERNETES_RUNTIME_CLASS",
        )
    nodes = nodes_for_sandboxes()
    add("nodes", bool(nodes), f"{len(nodes)} ready node{'s' if len(nodes) != 1 else ''} can run sandboxes")
    kata = "kata" in (handler or RUNTIME_CLASS)
    if kata:
        hinted = [n["metadata"]["name"] for n in nodes if kvm_hint(n)]
        add(
            "kvm",
            len(hinted) == len(nodes) and bool(nodes),
            f"{len(hinted)} of {len(nodes)} nodes show KVM (kata-deploy or node-feature-discovery labels); "
            "Kata needs bare metal or nested virtualization",
        )
    claims = api.get("/apis/storage.k8s.io/v1/storageclasses").get("items") or []
    if STORAGE_CLASS:
        add("storage", any(c["metadata"]["name"] == STORAGE_CLASS for c in claims), f"StorageClass {STORAGE_CLASS}")
    else:
        default = [
            c["metadata"]["name"]
            for c in claims
            if (c["metadata"].get("annotations") or {}).get("storageclass.kubernetes.io/is-default-class") == "true"
        ]
        add("storage", bool(default), f"default StorageClass {default[0]}" if default else "no default StorageClass")
    if SNAPSHOT_CLASS:
        found = api.exists(f"/apis/snapshot.storage.k8s.io/v1/volumesnapshotclasses/{SNAPSHOT_CLASS}")
        add("snapshots", found is not None, f"VolumeSnapshotClass {SNAPSHOT_CLASS}")
    try:
        daemons = api.get(pods_path(EGRESS_NAMESPACE), labelSelector=EGRESS_SELECTOR).get("items") or []
        on = {p["spec"].get("nodeName") for p in daemons if (p.get("status") or {}).get("phase") == "Running"}
        missing = [n["metadata"]["name"] for n in nodes if n["metadata"]["name"] not in on]
        add("egress", not missing, "on every sandbox node" if not missing else f"not running on {', '.join(missing)}")
    except Exception as e:
        add("egress", False, str(e))
    if probe:
        for node in nodes:
            ok, detail = probe_node(node["metadata"]["name"])
            add(f"node {node['metadata']['name']}", ok, detail)
    return checks


def kvm_hint(node: dict) -> bool:
    labels = node["metadata"].get("labels") or {}
    allocatable = node.get("status", {}).get("allocatable") or {}
    return (
        labels.get("katacontainers.io/kata-runtime") == "true"
        or labels.get("feature.node.kubernetes.io/cpu-cpuid.VMX") == "true"
        or labels.get("feature.node.kubernetes.io/cpu-cpuid.SVM") == "true"
        or quantity(allocatable.get("devices.kubevirt.io/kvm")) > 0
    )


def probe_node(node: str, timeout: float = 120) -> tuple[bool, str]:
    name = f"zoo-probe-{uuid.uuid4().hex[:8]}"
    spec: dict = {
        "affinity": on_node(node),
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "terminationGracePeriodSeconds": 0,
        "containers": [
            {"name": "probe", "image": PROBE_IMAGE, "resources": {"limits": {"cpu": "100m", "memory": "64Mi"}}}
        ],
    }
    if RUNTIME_CLASS:
        spec["runtimeClassName"] = RUNTIME_CLASS
    pull_secrets(spec)
    labels = {**LABELS, "app.kubernetes.io/component": "probe"}
    started = time.monotonic()
    try:
        api.request("POST", pods_path(NAMESPACE), {"metadata": {"name": name, "labels": labels}, "spec": spec})
        wait_running(NAMESPACE, name, timeout)
        return True, f"a {RUNTIME_CLASS or 'default'} pod started in {time.monotonic() - started:.1f}s"
    except Exception as e:
        return False, str(e)
    finally:
        with contextlib.suppress(Exception):
            delete_pod(NAMESPACE, name, timeout=60)


def main(argv: list[str]) -> int:
    """`python -m server.kube check [--probe]`: the requirements check, for the Helm chart's test hook."""
    if argv[:1] != ["check"] or not enabled():
        print("usage: ZOO_KUBERNETES_NAMESPACE=<namespace> python -m server.kube check [--probe]")
        return 2
    checks = check(probe="--probe" in argv)
    for c in checks:
        print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    return 0 if all(c["ok"] for c in checks) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
