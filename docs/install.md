# Install and operate

## Quickstart

On a fresh Ubuntu or Debian server (bare metal, or a cloud VM with nested virtualization):

```bash
curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash -s -- --admin-email you@example.com
```

The installer:

1. installs Docker if it's missing;
2. installs [Kata Containers](https://katacontainers.io) and registers it with Docker when the host has KVM (`/dev/kvm`), so each sandbox boots in its own lightweight VM. Without KVM, or if Kata can't start a test VM, it falls back to `runc` (plain containers sharing the host kernel) and says so;
3. writes `/opt/zoo/.env` with a fresh `JWT_SECRET` and `ZOO_SECRETS_KEY` (back the latter up: it encrypts stored secrets);
4. downloads the release's pinned `compose.yml`, pulls its signed images and starts the stack;
5. installs the `zoo` operator CLI.

It prints the dashboard URL when the stack is healthy, usually `http://<server ip>:3000` (the API is on `:8000`, OpenAPI docs at `/docs`). Sign up, create a sandbox, then create an API key under **Profile → API keys**. The key is shown once. Options: `--version X.Y.Z`, `--dir PATH`, `--domain HOST` (HTTPS through Caddy, see [Custom domain and HTTPS](#custom-domain-and-https)), `--runc`.

### Operating an install

```bash
zoo upgrade            # back up the database, move to the latest release, roll back if it isn't healthy
zoo upgrade 1.4.2      # or to a given release
zoo backup             # save the database to /opt/zoo/backups
zoo restore FILE       # put a backup back and restart the API
zoo doctor             # check KVM, the sandbox runtime, disk, ports, DNS and the API
```

Migrations run when the new API starts. Running sandboxes keep the image they booted from, across restarts too; their Overview tab offers **Restart on new image** (`POST /sandboxes/{id}/upgrade`), which keeps the home directory.

### Images

Releases publish signed, multi-arch (`linux/amd64`, `linux/arm64`) images to Docker Hub, mirrored to `ghcr.io/chann44`:

| Image | Used for |
| --- | --- |
| `chann44/zoo-api` | FastAPI server, MCP endpoint and job worker |
| `chann44/zoo-web` | the dashboard |
| `chann44/zoo-sandbox-desktop` | `desktop` and `browser` sandboxes (Debian, XFCE, Firefox, noVNC) |
| `chann44/zoo-sandbox-code` | `code` sandboxes (Python 3.12, Node, git, ripgrep, Claude Code) |

Tags: `1.4.2`, `1.4`, `1` and `latest` for releases; `edge` and `sha-<commit>` from `main` (`edge` is rebuilt nightly to pick up patched base images). Each tag is signed with cosign keyless and carries an SBOM and build provenance:

```bash
cosign verify docker.io/chann44/zoo-api:1.4.2 \
  --certificate-identity-regexp '^https://github.com/chann44/zoo/\.github/workflows/images\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

### From a checkout

```bash
cp .env.example .env        # set JWT_SECRET and ZOO_SECRETS_KEY to two different long random strings
docker compose up -d --build
```

`--build` builds the four images from the checkout instead of pulling them. To set up Kata by hand:

```bash
ls /dev/kvm                                  # bare metal, or a cloud VM with nested virtualization
# install Kata Containers 3.x: https://github.com/kata-containers/kata-containers/releases
sudo tee /etc/docker/daemon.json <<'JSON'
{ "runtimes": { "kata": { "runtimeType": "io.containerd.kata.v2" } } }
JSON
sudo systemctl restart docker
docker run --rm --runtime kata alpine uname -r   # prints the guest kernel, not the host's
```

On a machine without KVM (for development), set `ZOO_RUNTIME=runc` in `.env` to run plain containers.

The API talks to Docker through `/var/run/docker.sock` and stores its data in the `postgres` service and object storage in the `seaweedfs` service. Migrations run on boot.

## Custom domain and HTTPS

The `domain` compose profile adds Caddy on ports 80 and 443.

```bash
ADMIN_EMAILS=you@example.com ZOO_PUBLIC_IP=<server ip> docker compose --profile domain up -d --build
```

1. Point an A record at the server.
2. Add the hostname under **Profile → Domains** (admins only). The card shows whether DNS resolves to `ZOO_PUBLIC_IP` (IPv4 or IPv6); after changing the record, **Check DNS again**.
3. Open `https://your.domain`. Caddy gets a Let's Encrypt certificate on the first request.

Caddy only issues certificates for hostnames listed in the DB, or for `ZOO_DOMAIN`. It checks with `GET /domains/check?domain=<host>` (case and a trailing dot don't matter; anything else gets 404, so nobody can make the server request certificates for names it doesn't serve). On a custom domain the dashboard calls the API at `https://your.domain/api`, so you don't need to rebuild the web image or configure CORS.

## Backups

- **Sandbox files**: the **Backup** button (or `GET /sandboxes/{id}/backup`) downloads `/home/zoo` as a tar. `POST /sandboxes/{id}/restore` with the tar as the body restores it.
- **Database**: a worker dumps the database and snapshots every Linux sandbox's home to object storage every `ZOO_BACKUP_INTERVAL_HOURS` (`POST /admin/backups` runs one now, `GET /admin/backups` lists them); restore with `python -m server.backups restore <key>`. `zoo backup` / `zoo restore FILE` keep a local `pg_dump` for upgrades.
