---
title: Install
description: Docker by default, Kubernetes by explicit choice, with hardware virtualization required.
---

## Default: Docker on one Linux host

```bash
curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash -s -- --admin-email you@example.com
```

The installer prepares Docker Engine, the pinned Kata Go QEMU shim, KSM, release images,
Postgres, SeaweedFS, a native Go gateway, egress, the Python API/worker and the dashboard.
With `--domain`, Caddy provides the public HTTPS endpoint.

Use a dedicated Debian/Ubuntu systemd host. Both amd64 and arm64 installations use Kata
VMs when configured with the Kata runtime. Extra Linux, Mac and Windows hosts can enroll
through **Servers → Add server** — every host with a working Linux Docker engine can run
Linux desktop, Firefox browser and code sandboxes ([Remote servers](/docs/guides/remote-servers/)).

Updating: installed deployments use published images, no source checkout. From the
installation directory:

```bash
docker compose pull
docker compose up -d
```

## Requirements checked by the API

| Check | Requirement |
| --- | --- |
| Configuration | `DATABASE_URL` and `ZOO_OBJECT_STORE` reachable; `JWT_SECRET`; `ZOO_SECRETS_KEY` or `ZOO_KMS`; `ZOO_API_URL` |
| Runtime | `ZOO_RUNTIME` is `docker` or `kube` |
| Docker | Local Linux daemon reachable, sandbox images present; `ZOO_ISOLATION=kata` additionally needs runtime `io.containerd.kata.v2` and `/dev/kvm`; `auto` falls back to ordinary containers |
| Kubernetes | API reachable; RuntimeClass `kata`; StorageClass `ZOO_STORAGE_CLASS` (default `zoo-local`, TopoLVM); VolumeSnapshotClass `ZOO_SNAPSHOT_CLASS` |
| macOS hosts | Apple Silicon, macOS 14+, zoo-node, zoovm, base VM with guest + Accessibility grant |
| Windows hosts | Hyper-V capable edition, zoo-node, base VM with guest |

Startup collects named requirement failures before serving; `/readyz` exposes readiness.

## Options

The installer creates its own configuration under the chosen directory, normally
`/opt/zoo`. Back up the database and encryption keys; don't reuse placeholder secrets.

| Option | Effect |
| --- | --- |
| `--runtime docker\|kube` | Choose the Linux runtime; Docker is the default |
| `--version VERSION` | Install a specific release |
| `--dir PATH` | Installation directory |
| `--admin-email EMAIL` | Administrator account email |
| `--domain HOST` | Public HTTPS endpoint via Caddy |
| `--check` | Preflight only — does not provision missing capabilities |
| `--device EMPTY_BLOCK_DEVICE` | Kubernetes storage on an explicitly selected empty device (destructive) |
| `--disk-gb GB` | Kubernetes storage on a development loop file (not durable) |
| `--bundle PATH` | Install from a matching architecture/release offline archive |

For Kubernetes prerequisites and storage behavior, see [Kubernetes](/docs/guides/kubernetes/).

## Offline bundles

Release bundles contain pinned runtime binaries, charts, manifests and component images —
not just Zoo images. Required host tools must already exist: Python, OpenSSL, zstd, tar,
systemd, iptables and networking tools; Kubernetes additionally needs LVM/thin-provisioning
tools. Bundle version, architecture, component pins and checksums must match the installer.

Offline HTTPS certificates are not automatically trusted: browsers, enrolled hosts and VM
guests must trust the issuing CA, and their DNS must resolve the public API and native node
endpoint. Host-only address entries don't configure a guest VM's DNS.

## KSM and Kata tuning

Enable KSM on every sandbox node and persist it at reboot:

```bash
echo 1 | sudo tee /sys/kernel/mm/ksm/run
```

The Kubernetes deployment pins Kata 4.2.0's Go `clh` shim (RuntimeClass `kata`, handler
`kata-clh`, amd64) with `shared_fs = "virtio-fs"`, `enable_mem_prealloc = false`,
`reclaim_guest_freed_memory = true` and `enable_template = false` — disabling templating is
an intentional correctness requirement, and the current Cloud Hypervisor filesystem API
does not support DAX/cache windows. Docker keeps the upstream-supported Go QEMU shim.

KSM merges eligible private anonymous pages, not shared file-backed guest RAM; free-page
reporting reclaims pages a running guest frees. True whole-VM pause requires the matching
Zoo-patched Kata shim and authenticated node-local VM-control service — stock workload
freezing is not VM pause.

## Development

Docker runtime on a Linux KVM host: `make dev`. Kubernetes runtime on a local k3s with
Kata: `make dev-kube` (on a Mac: M3+, macOS 15+, a Lima VM with nested virtualization —
the pinned Cloud Hypervisor deployment requires amd64, so native ARM Lima is not an
equivalent setup). See the
[development documentation](https://github.com/chann44/zoo/blob/main/docs/development.md).

:::note
Installer code and static artifacts are not deployment certification. Runtime isolation,
disk/snapshot recovery, VM pause/resume and the [performance targets](/docs/reference/performance/)
remain to be validated on real infrastructure.
:::
