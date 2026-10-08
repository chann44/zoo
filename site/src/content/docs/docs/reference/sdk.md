---
title: Python SDK
description: zoo_sdk classes and methods, generated from the SDK's docstrings.
---

:::note
Generated from the code by `site/scripts/generate_reference.py` — do not edit by hand.
Regenerate with `bun run docs:gen` from `site/`.
:::

```bash
pip install ./sdk/python
```

```python
from zoo_sdk import Zoo

zoo = Zoo()  # reads ZOO_API_KEY and ZOO_URL
```

## `zoo_sdk.ZooError`


## `zoo_sdk.Zoo`

### `Zoo.__init__`

```python
Zoo(self, api_key: str | None=None, base_url: str | None=None)
```

| Method | |
| --- | --- |
| [`request()`](#zoorequest) |  |
| [`sandboxes()`](#zoosandboxes) |  |
| [`sandbox()`](#zoosandbox) |  |
| [`create()`](#zoocreate) |  |
| [`servers()`](#zooservers) |  |
| [`add_server()`](#zooadd_server) |  |
| [`profiles()`](#zooprofiles) |  |
| [`tools()`](#zootools) |  |

### `Zoo.request` {#zoorequest}

```python
request(self, method: str, path: str, **kwargs)
```


### `Zoo.sandboxes` {#zoosandboxes}

```python
sandboxes(self) -> list['Sandbox']
```


### `Zoo.sandbox` {#zoosandbox}

```python
sandbox(self, sandbox_id: str) -> 'Sandbox'
```


### `Zoo.create` {#zoocreate}

```python
create(self, name: str | None=None, kind: str='desktop', server_id: str | None=None, profile_ids: list[str] | None=None, wait: bool=True, timeout: int=180) -> 'Sandbox'
```


### `Zoo.servers` {#zooservers}

```python
servers(self) -> list[dict]
```


### `Zoo.add_server` {#zooadd_server}

```python
add_server(self, name: str, docker_url: str, bind_address: str) -> dict
```


### `Zoo.profiles` {#zooprofiles}

```python
profiles(self) -> list[dict]
```


### `Zoo.tools` {#zootools}

```python
tools(self) -> list[dict]
```


## `zoo_sdk.Sandbox`

### `Sandbox.__init__`

```python
Sandbox(self, client: Zoo, data: dict)
```

| Method | |
| --- | --- |
| [`refresh()`](#sandboxrefresh) |  |
| [`wait()`](#sandboxwait) |  |
| [`tool()`](#sandboxtool) |  |
| [`exec()`](#sandboxexec) |  |
| [`claude()`](#sandboxclaude) |  |
| [`screenshot()`](#sandboxscreenshot) |  |
| [`ask()`](#sandboxask) | Runs the server-side CUA agent on this sandbox and yields its events as they stream in: {"type": "user" \| "reasoning" \| "action" \| "text" \| "status" \| "error", "text": ...}, then {"type": "usage", "steps", "tokens", "cost", "elapsed", "max_steps", ...} after each model call and {"type": "done", "state": "succeeded" \| "failed" \| "cancelled"} at the end. An action event's "id" fetches the screenshot it was decided on with step_screenshot(). |
| [`stop_agent()`](#sandboxstop_agent) |  |
| [`agent_state()`](#sandboxagent_state) | The conversation, and the latest run with its usage and limits. |
| [`step_screenshot()`](#sandboxstep_screenshot) | The screen the agent saw before an action (an action message's or event's id). |
| [`hotkey()`](#sandboxhotkey) |  |
| [`start()`](#sandboxstart) |  |
| [`stop()`](#sandboxstop) | Stops the sandbox. Stopping runs as a job on the server, so by default this waits until it has stopped. |
| [`delete()`](#sandboxdelete) | Deletes the sandbox. Deleting runs as a job on the server, so by default this waits until it is gone. |
| [`set_secret()`](#sandboxset_secret) |  |
| [`set_permission()`](#sandboxset_permission) |  |
| [`set_network()`](#sandboxset_network) |  |
| [`add_rule()`](#sandboxadd_rule) |  |
| [`backup()`](#sandboxbackup) | Exports the home folder as a tar file; snapshots (`snapshot()`) are the faster way to keep a copy. |
| [`restore()`](#sandboxrestore) |  |
| [`snapshots()`](#sandboxsnapshots) |  |
| [`snapshot()`](#sandboxsnapshot) | Snapshots the home disk on the sandbox's server (a VM must be stopped). Waits until it is ready. |
| [`restore_snapshot()`](#sandboxrestore_snapshot) | Replaces the home disk with a snapshot's. The sandbox must be stopped. |
| [`delete_snapshot()`](#sandboxdelete_snapshot) |  |
| [`move()`](#sandboxmove) |  |
| [`save_profile()`](#sandboxsave_profile) | Saves the app's profile from this sandbox. Saving under an existing name (or a profile_id) adds a version. |
| [`apply_profile()`](#sandboxapply_profile) | Loads a profile, the latest version unless one is given. The app must not be running (409). |

### `Sandbox.refresh` {#sandboxrefresh}

```python
refresh(self) -> 'Sandbox'
```


### `Sandbox.wait` {#sandboxwait}

```python
wait(self, timeout: int=120) -> 'Sandbox'
```


### `Sandbox.tool` {#sandboxtool}

```python
tool(self, name: str, **args)
```


### `Sandbox.exec` {#sandboxexec}

```python
exec(self, command: str, timeout: int=30) -> dict
```


### `Sandbox.claude` {#sandboxclaude}

```python
claude(self, prompt: str, cwd: str='~/work', timeout: int=900, args: str='') -> dict
```


### `Sandbox.screenshot` {#sandboxscreenshot}

```python
screenshot(self) -> bytes
```


### `Sandbox.ask` {#sandboxask}

Runs the server-side CUA agent on this sandbox and yields its events as they stream in:
{"type": "user" | "reasoning" | "action" | "text" | "status" | "error", "text": ...}, then
{"type": "usage", "steps", "tokens", "cost", "elapsed", "max_steps", ...} after each model call and
{"type": "done", "state": "succeeded" | "failed" | "cancelled"} at the end. An action event's "id" fetches the
screenshot it was decided on with step_screenshot().

```python
ask(self, message: str, model: str | None=None)
```


### `Sandbox.stop_agent` {#sandboxstop_agent}

```python
stop_agent(self)
```


### `Sandbox.agent_state` {#sandboxagent_state}

The conversation, and the latest run with its usage and limits.

```python
agent_state(self) -> dict
```


### `Sandbox.step_screenshot` {#sandboxstep_screenshot}

The screen the agent saw before an action (an action message's or event's id).

```python
step_screenshot(self, message_id: str) -> bytes
```


### `Sandbox.hotkey` {#sandboxhotkey}

```python
hotkey(self, *keys: str) -> dict
```


### `Sandbox.start` {#sandboxstart}

```python
start(self, wait: bool=True) -> 'Sandbox'
```


### `Sandbox.stop` {#sandboxstop}

Stops the sandbox. Stopping runs as a job on the server, so by default this waits until it has stopped.

```python
stop(self, wait: bool=True, timeout: int=120) -> 'Sandbox'
```


### `Sandbox.delete` {#sandboxdelete}

Deletes the sandbox. Deleting runs as a job on the server, so by default this waits until it is gone.

```python
delete(self, wait: bool=True, timeout: int=120)
```


### `Sandbox.set_secret` {#sandboxset_secret}

```python
set_secret(self, name: str, value: str)
```


### `Sandbox.set_permission` {#sandboxset_permission}

```python
set_permission(self, permission: str, action: str, effect: str)
```


### `Sandbox.set_network` {#sandboxset_network}

```python
set_network(self, default_action: str='allow', allow_dns: bool=True)
```


### `Sandbox.add_rule` {#sandboxadd_rule}

```python
add_rule(self, rule_type: str, value: str, effect: str='allow')
```


### `Sandbox.backup` {#sandboxbackup}

Exports the home folder as a tar file; snapshots (`snapshot()`) are the faster way to keep a copy.

```python
backup(self, path: str)
```


### `Sandbox.restore` {#sandboxrestore}

```python
restore(self, path: str)
```


### `Sandbox.snapshots` {#sandboxsnapshots}

```python
snapshots(self) -> list[dict]
```


### `Sandbox.snapshot` {#sandboxsnapshot}

Snapshots the home disk on the sandbox's server (a VM must be stopped). Waits until it is ready.

```python
snapshot(self, name: str='', wait: bool=True, timeout: int=1800) -> dict
```


### `Sandbox.restore_snapshot` {#sandboxrestore_snapshot}

Replaces the home disk with a snapshot's. The sandbox must be stopped.

```python
restore_snapshot(self, snapshot_id: str, wait: bool=True, timeout: int=1800) -> 'Sandbox'
```


### `Sandbox.delete_snapshot` {#sandboxdelete_snapshot}

```python
delete_snapshot(self, snapshot_id: str)
```


### `Sandbox.move` {#sandboxmove}

```python
move(self, server_id: str | None) -> 'Sandbox'
```


### `Sandbox.save_profile` {#sandboxsave_profile}

Saves the app's profile from this sandbox. Saving under an existing name (or a profile_id) adds a version.

```python
save_profile(self, name: str, app: str='firefox', profile_id: str | None=None) -> dict
```


### `Sandbox.apply_profile` {#sandboxapply_profile}

Loads a profile, the latest version unless one is given. The app must not be running (409).

```python
apply_profile(self, profile_id: str, version: int | None=None) -> dict
```


## `zoo_sdk.agent.Agent`

| Method | |
| --- | --- |
| [`tools()`](#agenttools) |  |
| [`screenshot()`](#agentscreenshot) |  |
| [`xdotool()`](#agentxdotool) |  |
| [`computer()`](#agentcomputer) |  |
| [`bash()`](#agentbash) |  |
| [`run()`](#agentrun) |  |

### `Agent.tools` {#agenttools}

```python
tools(self) -> list[dict]
```


### `Agent.screenshot` {#agentscreenshot}

```python
screenshot(self) -> dict
```


### `Agent.xdotool` {#agentxdotool}

```python
xdotool(self, args: str)
```


### `Agent.computer` {#agentcomputer}

```python
computer(self, action: str, coordinate=None, text=None, **kw) -> list[dict]
```


### `Agent.bash` {#agentbash}

```python
bash(self, command: str | None=None, restart: bool=False, **_) -> list[dict]
```


### `Agent.run` {#agentrun}

```python
run(self, task: str) -> str
```


## Errors

Any non-2xx response raises `zoo_sdk.ZooError` with the status code and the API's
`detail`; see [Errors](/docs/reference/errors/). Any tool can be called as a method
(`box.window_focus(window_id=...)`) or with `box.tool(name, **args)`.
