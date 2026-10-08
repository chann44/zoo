---
title: Upgrading
description: zoo upgrade moves the stack between releases and rolls back if the new one isn't healthy; sandboxes keep their images until you say otherwise.
---

## The operator CLI

The installer puts a `zoo` CLI on the host:

```bash
zoo upgrade            # back up the database, move to the latest release, roll back if it isn't healthy
zoo upgrade 1.4.2      # or to a given release
zoo backup             # save the database to /opt/zoo/backups
zoo restore FILE       # put a backup back and restart the API
zoo doctor             # check KVM, the sandbox runtime, disk, ports, DNS and the API
```

Migrations run when the new API starts. If the new release isn't healthy, `zoo upgrade`
rolls back.

## What happens to running sandboxes

Running sandboxes keep the image they booted from, across restarts too. To move one to the
new image, use **Restart on new image** on its Overview tab (`POST
/sandboxes/{id}/upgrade`) — it keeps the home directory. New sandboxes get the new image
immediately.

zoo-node hosts update themselves: when a node runs another version than the API, the API
streams it the matching build, the node checks the size and SHA-256, swaps the binary and
restarts. Guest agents (`zoo-guest`) update in place the same way on their next boot.

## Releases

[release-please](https://github.com/googleapis/release-please) tags `vX.Y.Z` from
conventional commits and publishes:

- images `chann44/zoo-*:X.Y.Z` (plus `X.Y`, `X`, `latest`), signed with cosign keyless,
  with an SBOM and build provenance:

```bash
cosign verify docker.io/chann44/zoo-api:1.4.2 \
  --certificate-identity-regexp '^https://github.com/chann44/zoo/\.github/workflows/images\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

- `install.sh`, the pinned `compose.yml`, `Caddyfile`, the `zoo` CLI, the `zoovm` binary
  and the Windows scripts as release assets;
- the Helm chart as an OCI artifact, at the same version as the images.

`edge` and `sha-<commit>` images build from `main` (rebuilt nightly to pick up patched
base images). The docs site's Reference section is generated from the code at build time
and carries the release badge it documents.
