---
title: Architecture
description: The components, the sandbox lifecycle and states, and the job system that runs everything.
---

## The components

```
server/            FastAPI app
  sandbox_api.py   sandbox lifecycle, tool calls, VNC proxy, reconcile loop
  registry.py      tool registry and sandbox types
  runtime.py       routes lifecycle and policy calls to Docker, macOS or Windows
  docker.py        containers, volumes, egress daemon, multi-host clients
  macos.py         macOS VMs over SSH (zoovm)
  windows.py       Windows Hyper-V VMs over SSH (zoovm.ps1)
  gateway.py       the connection gateway for multi-process installs
mcp_tools/         MCP server built from the registry
web/               dashboard (TanStack Start, React Query, shadcn)
node/              zoo-node: the dial-out daemon on each host
sdk/python/        zoo_sdk and zoo_sdk.agent
guest/             zoo-guest: the agent inside each sandbox
macos/, windows/   zoovm and zoovm.ps1, the VM helpers
deploy/zoo         operator CLI: upgrade, backup, restore, doctor
```

Every tool is registered once in `server/registry.py` and exposed the same way over REST,
MCP and the SDK — one registry, three doors. The dashboard is static: it talks to the same
API you do.

## Sandbox lifecycle and states

A sandbox moves through states (`pending`, `provisioning`, `running`, `stopped`,
`failed`); the SDK's `wait()` polls until it leaves `pending`/`provisioning`, and surfaces
`error_message` when it lands on `failed`.

- **Create** provisions on a server (picked, or **Least busy** — the most free memory
  among hosts reporting it). On Docker the home volume `zoo-home-<id>` is created and
  seeded from the image's `/home/zoo`. On a host with a [warm pool](#the-warm-pool), the
  sandbox claims a pre-warmed container and is running in about a second.
- **Running**, the container (or VM) is up: Linux kinds with 2 GB memory, 2 CPUs and 1024
  processes, as user `zoo` (uid 1000), reached only through the API — desktop ports bind
  to `127.0.0.1` or the compose network. macOS and Windows run within their per-host VM
  limits.
- **Stop** removes the container and keeps the volume (macOS/Windows: shuts the VM down
  and keeps its disk).
- **Start** creates a fresh container on the current image and mounts the same volume —
  files in `/home/zoo` survive stop and start.
- **Delete** removes the container or VM **and** the volume (and snapshots).
- **Move** relocates a stopped sandbox to another server, through `ZOO_OBJECT_STORE` when
  it is set — the data never passes through the API host.

A container reported as running in the database but gone from Docker is marked stopped
within 15 seconds: the API runs a reconcile loop against reality.

## The job system

Lifecycle work — boots, stops, deletes, moves, snapshots and restores — runs as **jobs**:
rows in the database that a worker process claims and executes, with retries and outcomes.
Snapshots and restores queue behind boots, stops and moves on the same sandbox, and the
SDK methods that trigger them wait by default (`box.stop()`, `snapshot()`,
`restore_snapshot()`).

Observability sees the queue: `zoo_job_duration_seconds` (per attempt, by kind and
outcome) and `zoo_job_wait_seconds` (from due to start) are in
[Grafana](/docs/guides/domain-https-backups/#observability).

Agent tasks are durable the same way: a row in `agent_runs`, claimed by a worker with a
heartbeat — an API restart pauses and resumes them, a crash is picked up within 30
seconds, and a task interrupted three times fails instead of looping.

## Process roles

One process can do everything (`ZOO_ROLE=all`, the compose default), or the work splits:

| Role | Does |
| --- | --- |
| `api` | serves requests |
| `worker` | background work: lifecycle jobs, agent tasks, the warm pool, the Discord bot |
| `gateway` | holds the guest websockets and zoo-node streams for the others |

Scale out with any number of `api` replicas behind one `worker` — that's the shape of the
[Kubernetes chart](/docs/guides/kubernetes/), where the gateway becomes its own pod.

## The warm pool

On Linux hosts, an admin can set a warm pool size under **Servers → Warm pool**. Pooled
sandboxes boot with no owner, wait until their guest connects, and hold. Creating a
sandbox claims one — its id becomes the sandbox's id, secrets and profiles attach before
hand-off — and a replacement boots. With a pool, create → running takes about a second.
