---
title: Install
description: One command installs Zoo on a single Ubuntu or Debian host, with Kata microVMs when the host has KVM and plain containers when it doesn't.
---

Zoo installs on a fresh Ubuntu or Debian server — bare metal, or a cloud VM with nested
virtualization:

```bash
curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash -s -- --admin-email you@example.com
```

The installer:

1. installs Docker if it's missing;
2. installs [Kata Containers](https://katacontainers.io) and registers it with Docker when
   the host has KVM (`/dev/kvm`), so each sandbox boots in its own lightweight VM. Without
   KVM, or if Kata can't start a test VM, it falls back to `runc` (plain containers sharing
   the host kernel) and says so;
3. writes `/opt/zoo/.env` with a fresh `JWT_SECRET` and `ZOO_SECRETS_KEY` (back the latter
   up: it encrypts stored secrets);
4. downloads the release's pinned `compose.yml`, pulls its signed images and starts the stack;
5. installs the `zoo` operator CLI.

It prints the dashboard URL when the stack is healthy, usually `http://<server ip>:3000`.
The API is on `:8000`, with OpenAPI docs at `/docs`.

Installer options: `--version X.Y.Z`, `--dir PATH`, `--domain HOST` (HTTPS through Caddy,
see [Custom domain and HTTPS](/docs/guides/domain-https-backups/)), and `--runc` to skip
Kata even when KVM is present.

## With KVM, and without

| Host | Runtime | Isolation |
| --- | --- | --- |
| KVM present (`ls /dev/kvm`) | Kata (default) | each sandbox is its own microVM with its own kernel |
| No KVM, or `--runc` | `runc` | plain containers sharing the host kernel, with a tighter seccomp filter and, on AppArmor hosts, the `zoo-sandbox` profile |

Check a host with `zoo doctor`: it checks KVM, the sandbox runtime, disk, ports, DNS and
the API. On a machine without KVM — for development — set `ZOO_RUNTIME=runc` in `.env`.

Kata needs nested virtualization on cloud VMs: GCE with it enabled, Azure Dv3/Ev3 and
newer, AWS `*.metal` or instance families that support it.

## From a checkout

```bash
cp .env.example .env        # set JWT_SECRET and ZOO_SECRETS_KEY to two different long random strings
docker compose up -d --build
```

`--build` builds the four images from the checkout instead of pulling them. To set up Kata
by hand:

```bash
ls /dev/kvm                                  # bare metal, or a cloud VM with nested virtualization
# install Kata Containers 3.x: https://github.com/kata-containers/kata-containers/releases
sudo tee /etc/docker/daemon.json <<'JSON'
{ "runtimes": { "kata": { "runtimeType": "io.containerd.kata.v2" } } }
JSON
sudo systemctl restart docker
docker run --rm --runtime kata alpine uname -r   # prints the guest kernel, not the host's
```

The API talks to Docker through `/var/run/docker.sock` and stores its data in the
`postgres` and `seaweedfs` services. Migrations run on boot.

## What gets installed

Releases publish signed, multi-arch (`linux/amd64`, `linux/arm64`) images to Docker Hub,
mirrored to `ghcr.io/chann44`:

| Image | Used for |
| --- | --- |
| `chann44/zoo-api` | FastAPI server, MCP endpoint and job worker |
| `chann44/zoo-web` | the dashboard |
| `chann44/zoo-sandbox-desktop` | `desktop` and `browser` sandboxes (Debian, XFCE, Firefox, noVNC) |
| `chann44/zoo-sandbox-code` | `code` sandboxes (Python 3.12, Node, git, ripgrep, Claude Code) |

Tags: `1.4.2`, `1.4`, `1` and `latest` for releases; `edge` and `sha-<commit>` from `main`.
Each tag is signed with cosign keyless and carries an SBOM and build provenance.

## Next steps

- [Your first sandbox in the dashboard](/docs/get-started/first-sandbox/)
- [Connect Claude Code or Claude Desktop through MCP](/docs/get-started/mcp/)
- Upgrades, backups and the `zoo` CLI: [Upgrading](/docs/guides/upgrading/)
