import base64
import os
import time

import requests


class ZooError(Exception):
    pass


class Zoo:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get("ZOO_URL", "http://localhost:8000")).rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key or os.environ['ZOO_API_KEY']}"

    def request(self, method: str, path: str, **kwargs):
        res = self.session.request(method, f"{self.base_url}{path}", timeout=kwargs.pop("timeout", 330), **kwargs)
        if not res.ok:
            try:
                detail = res.json().get("detail")
            except ValueError:
                detail = res.text
            raise ZooError(f"{res.status_code}: {detail}")
        return res

    def sandboxes(self) -> list["Sandbox"]:
        return [Sandbox(self, s) for s in self.request("GET", "/sandboxes").json()]

    def sandbox(self, sandbox_id: str) -> "Sandbox":
        return Sandbox(self, self.request("GET", f"/sandboxes/{sandbox_id}").json())

    def create(self, name: str | None = None, wait: bool = True, timeout: int = 120) -> "Sandbox":
        sandbox = Sandbox(self, self.request("POST", "/sandboxes", json={"name": name}).json())
        return sandbox.wait(timeout) if wait else sandbox

    def tools(self) -> list[dict]:
        return self.request("GET", "/tools").json()


class Sandbox:
    def __init__(self, client: Zoo, data: dict):
        self.client = client
        self.data = data

    def __getattr__(self, name: str):
        if name in ("id", "name", "status", "error_message"):
            return self.data[name]
        return lambda **kwargs: self.tool(name, **kwargs)

    def __repr__(self):
        return f"Sandbox({self.id!r}, {self.name!r}, {self.status!r})"

    def refresh(self) -> "Sandbox":
        self.data = self.client.request("GET", f"/sandboxes/{self.id}").json()
        return self

    def wait(self, timeout: int = 120) -> "Sandbox":
        deadline = time.monotonic() + timeout
        while self.refresh().status in ("pending", "provisioning"):
            if time.monotonic() > deadline:
                raise ZooError(f"sandbox {self.id} not ready after {timeout}s")
            time.sleep(1)
        if self.status != "running":
            raise ZooError(f"sandbox {self.id} is {self.status}: {self.error_message}")
        return self

    def tool(self, name: str, **args):
        return self.client.request("POST", f"/sandboxes/{self.id}/tools/{name}", json=args).json()

    def exec(self, command: str, timeout: int = 30) -> dict:
        return self.tool("execute_command", command=command, timeout=timeout)

    def screenshot(self) -> bytes:
        return base64.b64decode(self.tool("screenshot"))

    def hotkey(self, *keys: str) -> dict:
        return self.tool("hotkey", keys=list(keys))

    def start(self, wait: bool = True) -> "Sandbox":
        self.data = self.client.request("POST", f"/sandboxes/{self.id}/start").json()
        return self.wait() if wait else self

    def stop(self) -> "Sandbox":
        self.data = self.client.request("POST", f"/sandboxes/{self.id}/stop").json()
        return self

    def delete(self):
        self.client.request("DELETE", f"/sandboxes/{self.id}")

    def set_secret(self, name: str, value: str):
        return self.client.request("PUT", f"/sandboxes/{self.id}/secrets", json={"name": name, "value": value}).json()

    def set_permission(self, permission: str, action: str, effect: str):
        body = {"permission": permission, "action": action, "effect": effect}
        return self.client.request("PUT", f"/sandboxes/{self.id}/permissions", json=body).json()

    def set_network(self, default_action: str = "allow", allow_dns: bool = True):
        body = {"default_action": default_action, "allow_dns": allow_dns}
        return self.client.request("PUT", f"/sandboxes/{self.id}/network", json=body).json()

    def add_rule(self, rule_type: str, value: str, effect: str = "allow"):
        body = {"rule_type": rule_type, "value": value, "effect": effect}
        return self.client.request("POST", f"/sandboxes/{self.id}/network/rules", json=body).json()

    def backup(self, path: str):
        with open(path, "wb") as f:
            for chunk in self.client.request("GET", f"/sandboxes/{self.id}/backup", stream=True).iter_content(1 << 16):
                f.write(chunk)

    def restore(self, path: str):
        with open(path, "rb") as f:
            self.client.request("POST", f"/sandboxes/{self.id}/restore", data=f.read())
