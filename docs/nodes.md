# zoo-node

zoo-node is a small daemon on each host that runs sandboxes. It joins the control plane once with a token from the dashboard, then **dials out** to the API and keeps the link up. Hosts need no inbound port and can sit behind NAT. The daemon:

- reports the host's capacity, health and running sandboxes, and the scheduler places sandboxes by that free capacity;
- carries the API's connections to the host's Docker socket and, on macOS and Windows, its SSH server, so every runtime operation works the same as over SSH;
- updates itself to the API's version;
- renews its own certificate.

It runs on Linux (amd64, arm64), Apple Silicon Macs and Windows (amd64). The source is in `node/`.

## Add a server with zoo-node

1. Under **Servers > Add a server**, pick the machine's OS, name it and click **Get the command**.
2. Run the command on the machine. It sets the machine up (Docker and Kata on Linux, zoovm on a Mac, Hyper-V on Windows, as before), downloads zoo-node from the control plane and runs `zoo-node join <token> --service`.
3. The server shows up under **Servers** once the node connects.

On a machine that is already set up, run only the join line the dashboard shows:

```sh
sudo zoo-node join '<token>' --service                    # Linux
zoo-node join '<token>' --service                         # Mac, as the user that runs the VMs
zoo-node.exe join '<token>' --service --ssh-user <user>   # Windows, elevated
```

The binary is at `<API URL>/nodes/download/<linux|darwin|windows>/<amd64|arm64>`. `zoo node …` works the same as `zoo-node …`.

A token works once and expires after an hour. It carries the API's URL and the fingerprint of its node CA. The node checks the CA it gets back against that fingerprint, so a man in the middle of the join request can't slip in its own.

## How it connects

- **Join**: the node makes an EC P-256 key and sends a CSR with the token to `POST /nodes/join`. The API signs a certificate for a year, naming the node by its id (CN), and returns it with the CA and the API's gRPC endpoints. The key never leaves the host.
- **Link**: the node holds one gRPC `Connect` stream (`node/proto/node.proto`) to each endpoint, over TLS 1.3 with client certificates (mTLS). It reconnects with backoff. The API checks that the certificate's serial is still the node's current one, so joining again or deleting the server cuts off the old certificate.
- **Tunnels**: the API opens byte streams through the node to `docker` (the Docker socket) and `ssh` (`127.0.0.1:22`, macOS and Windows only).
  - On Linux, docker-py talks to the Docker socket through a local Unix socket the API bridges.
  - On macOS and Windows, paramiko runs SSH over the tunnel and checks the host key as usual.
- **Reports**: every 15 seconds the node sends:
  - CPUs, total and available memory, disk, and load (the 1-minute load average per CPU, or CPU use on Windows);
  - the ids of the sandboxes each runtime runs;
  - health checks: each runtime, each tunnel target, and at least 10 GB of free disk.
- **Runtimes**:
  - Linux: `kata` (Kata Containers, the containerd shim `io.containerd.kata.v2` registered with Docker) and `runc`.
  - Mac: `zoovm`.
  - Windows: `hyperv`.
  - The API creates and changes sandboxes through its runtime backends over the tunnels; the node's drivers report which runtimes exist and what they run.
- **Updates**: when a node runs another version than the API, the API streams it the matching build from `node/dist` (built by `make node-dist` and included in the API image). The node checks the size and SHA-256, swaps the binary and exits so its service manager starts the new one. Development builds (`dev`) are never replaced.
- **Renewal**: within 30 days of expiry, the node sends a CSR for a new key on its stream and swaps in the new certificate.

Each API process listens for nodes on `ZOO_NODE_PORT` (default 7443), and nodes dial every address in `ZOO_NODE_ENDPOINTS`. Without that setting, nodes dial the host from `ZOO_API_URL` on that port. With `api` and `worker` replicas, give every process its own reachable address and list them all, since each process reaches hosts only through its own streams. Publish the port straight through: the stream carries its own TLS, so it can't sit behind the HTTP proxy.

## Services

| Host | Runs as | Files |
|---|---|---|
| Linux | systemd `zoo-node.service`, root (for Docker) | `/usr/local/bin/zoo-node`, `/var/lib/zoo-node` |
| macOS | LaunchAgent `dev.zoo.node` of the VM user | `~/.zoo-node`, log `~/.zoo-node/node.log` |
| Windows | Service `zoo-node`, LocalSystem, restarted on failure | `C:\ProgramData\zoo-node` |

## Converting an SSH server

Servers added over SSH keep working until Zoo 2.0. To convert one in place, click **Switch to zoo-node** on it, or run:

```sh
zoo-node migrate <server-id> --api https://zoo.example.com/api --key <API key>
```

Both call `POST /servers/{id}/migrate`. The API installs zoo-node over the connection it already has and joins it to the same server, then waits up to a minute for it to connect. Sandboxes stay where they are.

- **Linux**: Docker access over SSH already amounts to root on the host. The API runs a one-shot runc container with the host's filesystem, copies the binary in and runs the join on the host, which installs the systemd service.
- **Mac and Windows**: the API uploads the binary over SSH and runs the join as the SSH user.

The server's `ssh://` URL stays. While the node is offline, the API falls back to Docker over SSH or plain SSH.

## Placement

When a sandbox is placed automatically, hosts that report free memory are ranked by it. These are servers whose node reported in the last 90 seconds, and the control plane's own machine on Linux. A Linux sandbox needs 2 GB; a macOS or Windows VM needs its configured memory.

Servers without a node, or hosts short on memory, fall back to the old rule: the server running the fewest sandboxes. The macOS and Windows per-host VM limits still apply.
