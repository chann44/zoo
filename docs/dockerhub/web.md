# Zoo dashboard

The dashboard: create and watch sandboxes, take over their desktops, set policies, secrets and API keys.

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

Images are built for `linux/amd64` and `linux/arm64` and mirrored to `ghcr.io/chann44/zoo-web`.

## Environment

| Variable | Purpose |
| --- | --- |
| `ZOO_API_URL` | URL of the Zoo API as the browser sees it, read at start |

## Verify

Every tag is signed with cosign (keyless, from the release workflow) and carries an SBOM and build provenance:

```bash
cosign verify docker.io/chann44/zoo-web:latest \
  --certificate-identity-regexp '^https://github.com/chann44/zoo/\.github/workflows/images\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect docker.io/chann44/zoo-web:latest --format '{{ json .SBOM }}'
```
