# Zoo API

The FastAPI server: REST API, MCP endpoint (`/mcp`), the VNC viewer proxy and the job worker that boots, stops and moves sandboxes. It drives Docker through `/var/run/docker.sock` and keeps its SQLite database in `/data`; migrations run when it starts.

Part of [Zoo](https://github.com/chann44/zoo), self-hosted sandboxes for AI agents. Install a whole stack with:

```bash
curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash
```

## Tags

| Tag | Points at |
| --- | --- |
| `1.4.2`, `1.4`, `1`, `latest` | releases |
| `edge` | the latest commit on `main`, rebuilt nightly with patched base images |
| `sha-<commit>` | one commit on `main` |

Images are built for `linux/amd64` and `linux/arm64` and mirrored to `ghcr.io/chann44/zoo-api`.

## Environment

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | signs sessions |
| `ZOO_SECRETS_KEY` | encrypts stored secrets; required for new installs |
| `ZOO_RUNTIME` | `kata` (default) or `runc` |
| `ZOO_SANDBOX_IMAGE`, `ZOO_CODE_IMAGE` | sandbox images to launch |

## Verify

Every tag is signed with cosign (keyless, from the release workflow) and carries an SBOM and build provenance:

```bash
cosign verify docker.io/chann44/zoo-api:latest \
  --certificate-identity-regexp '^https://github.com/chann44/zoo/\.github/workflows/images\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect docker.io/chann44/zoo-api:latest --format '{{ json .SBOM }}'
```
