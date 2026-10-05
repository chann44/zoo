# Zoo desktop sandbox

The image for `desktop` and `browser` sandboxes: Debian with XFCE, Firefox and noVNC. The API starts it under Kata Containers (or runc) and passes a per-sandbox VNC password that only the API knows; x11vnc listens only inside the sandbox.

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

Images are built for `linux/amd64` and `linux/arm64` and mirrored to `ghcr.io/chann44/zoo-sandbox-desktop`.

## Environment

| Variable | Purpose |
| --- | --- |
| `ZOO_VNC_PASSWORD` | x11vnc password, set by the API |

## Verify

Every tag is signed with cosign (keyless, from the release workflow) and carries an SBOM and build provenance:

```bash
cosign verify docker.io/chann44/zoo-sandbox-desktop:latest \
  --certificate-identity-regexp '^https://github.com/chann44/zoo/\.github/workflows/images\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect docker.io/chann44/zoo-sandbox-desktop:latest --format '{{ json .SBOM }}'
```
