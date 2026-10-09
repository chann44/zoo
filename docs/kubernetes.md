# Zoo on Kubernetes

Kubernetes is an added way to deploy Zoo, for teams that already run clusters. A single host (`docker compose`, [install.md](install.md)) and [zoo-node](nodes.md) stay the default and the fastest path.

On Kubernetes:

- Zoo itself runs as Deployments from a Helm chart (`deploy/helm/zoo`), with Postgres and any S3-compatible object storage.
- Linux sandboxes run as pods in the cluster: one pod per sandbox, under the Kata Containers RuntimeClass, with a PersistentVolumeClaim for its home and zoo-guest inside.
- macOS and Windows sandboxes still run on Macs and Hyper-V hosts outside the cluster. Their zoo-node registers with the same control plane, so one install offers every OS.

## What the chart runs

| Component | What it is | Scaling |
|---|---|---|
| `api` | The API and MCP endpoint (`ZOO_ROLE=api`) | HorizontalPodAutoscaler on CPU, 2–10 pods by default |
| `worker` | The job worker: sandbox lifecycle jobs, agent runs, the warm pool, the Discord bot (`ZOO_ROLE=worker`) | 1 pod; more are safe for agent runs |
| `gateway` | The connection gateway (`ZOO_ROLE=gateway`): holds every guest websocket and zoo-node stream | 1 pod, recreated on upgrade |
| `web` | The dashboard | Fixed replicas, or an HPA |
| `egress` | A DaemonSet in the sandbox namespace that enforces each sandbox's network policy on its node | One per node |

The chart also sets up:

- An Ingress for the dashboard host and the API host. `/guest/connect` on the API host goes to the gateway.
- A LoadBalancer Service for zoo-node (port 7443).
- A ServiceMonitor, if you turn it on.
- A Helm test that runs the sandbox requirements check.

**Why a gateway.** A sandbox's guest and a host's zoo-node each hold one long-lived connection, and it lands on one process. With several API pods behind a Service, a tool call can arrive at any pod, so one process, the gateway, holds every connection. The API and worker pods set `ZOO_GATEWAY` and reach guests and nodes through it (`server/gateway.py`):

- Guest calls, terminals and desktop tunnels go through a relay websocket that speaks the guest protocol.
- Docker and SSH connections to zoo-node hosts go through a tunnel websocket.

The gateway keeps nothing of its own. When it restarts, guests and nodes dial it again within seconds, and the calls in flight at that moment fail and can be retried.

## Install

Before you install, the cluster needs:

- Kubernetes 1.29 or later, and an ingress controller. Long-lived websockets go through the ingress; for ingress-nginx, raise the read timeout with `nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"` and `proxy-send-timeout`.
- Postgres, from one of:
  - the [CloudNativePG](https://cloudnative-pg.io) operator, in which case the chart creates the cluster;
  - a managed database, through `database.mode=external` and a secret holding its URL.
- Storage for `/data`, which every Zoo pod shares: profiles, agent screenshots and SSH host keys. With more than one Zoo pod this must be ReadWriteMany, such as EFS, Filestore, Azure Files, CephFS or NFS.
- For sandboxes:
  - Kata Containers, installed with [kata-deploy](https://github.com/kata-containers/kata-containers/tree/main/tools/packaging/kata-deploy), which also creates the `kata` RuntimeClass;
  - nodes with KVM;
  - a default StorageClass.

The smallest install:

```sh
helm install zoo oci://registry-1.docker.io/chann44/zoo --version <version> \
  --namespace zoo --create-namespace \
  --set ingress.host=zoo.example.com --set ingress.apiHost=api.zoo.example.com \
  --set 'env.ADMIN_EMAILS=you@example.com'
helm test zoo --namespace zoo --logs
```

The chart is published to Docker Hub as an OCI artifact with every release, at the same version as the images.

Every setting is in [`values.yaml`](../deploy/helm/zoo/values.yaml), with comments. The ones that matter most:

| Value | What it does |
|---|---|
| `ingress.host`, `ingress.apiHost`, `ingress.tls` | The public addresses. The API host also takes guests from sandboxes outside the cluster. |
| `database.mode` | `cnpg` (default) creates a CloudNativePG `Cluster`, and Zoo reads its `<release>-db-app` secret. `external` reads `database.external.existingSecret`. |
| `objectStorage.url`, `.endpoint`, `.existingSecret` | Moves of homes and VM disks between hosts go through it. |
| `secrets.existingSecret`, `secrets.kms`, `externalSecrets.*` | Where `JWT_SECRET` and `ZOO_SECRETS_KEY` come from. See below. |
| `gateway.nodes.endpoint` | `host:port` of the zoo-node load balancer. Required before you add a server with zoo-node. |
| `sandboxes.runtimeClass` | `kata` by default. `runc` runs plain containers on clusters without KVM, with weaker isolation. |
| `sandboxes.storageClass`, `.homeSize`, `.snapshotClass` | The sandboxes' home claims, and CSI snapshots of them. |
| `metrics.serviceMonitor.enabled` | Prometheus Operator scraping of every Zoo pod's `/metrics` (port 9464). |
| `env` | Any setting from [configuration.md](configuration.md), for every Zoo pod. |

Zoo pods migrate the database as they start, under a Postgres advisory lock (`db/migrate.py`), so pods starting together take turns. Upgrades need nothing else.

## Postgres and object storage

Zoo runs on Postgres only (`DATABASE_URL`), and needs S3-compatible object storage (`objectStorage.url`); the chart refuses to render without it.

- **Migrations.** The Postgres schema has its own migrations in `db/postgres`. The queries are shared: `db/connection.py` rewrites each one for Postgres once.
- **Tests.** The whole test suite runs on both databases in CI.
- **Backups.** On Postgres, `/admin/backups` refuses: back up with the database itself, through CloudNativePG's `backup` (passed through from `database.cnpg.backup`) or your provider's snapshots.

Object storage is any S3 API, set with `objectStorage`. Credentials come from one of:

- a secret with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`;
- on EKS, the pods' identity: IAM roles for service accounts (set `serviceAccount.annotations."eks.amazonaws.com/role-arn"`) or EKS Pod Identity.

With pod identity, presigned URLs last only as long as the session credentials, about an hour, which bounds how long one move can take.

## Secrets

`JWT_SECRET` signs logins and `ZOO_SECRETS_KEY` wraps the keys that encrypt stored secrets. Choose one of three sources:

- **Generated (default).** The chart generates both once into `<release>-secrets` and keeps that secret when the chart is uninstalled, since losing `ZOO_SECRETS_KEY` loses every stored secret.
- **Your own secret.** Set `secrets.existingSecret`.
- **External Secrets Operator.** Set `externalSecrets.enabled=true`, a `secretStoreRef`, and `externalSecrets.data`, which maps environment variables to remote keys. The chart writes an `ExternalSecret` (`external-secrets.io/v1`) that fills the same secret from Vault, AWS Secrets Manager, GCP Secret Manager or any other store ESO supports. Add anything else Zoo should read from the store, such as `DATABASE_URL` or `SLACK_BOT_TOKEN`. Pods read the secret when they start, so restart them after it changes.

**`ZOO_SECRETS_KEY` from a KMS.** Set `secrets.kms` (`ZOO_KMS`) to `aws:<key ARN>`, `gcp:projects/…/cryptoKeys/<key>` or `vault:<mount>/<key>`. The workspace data keys are then wrapped by the KMS and `ZOO_SECRETS_KEY` only opens keys from before (see `server/kms.py`). On EKS and GKE the pods' identity reaches the KMS, through the service account's IRSA or Workload Identity annotation, so no key is stored in the cluster.

## Sandboxes on Kubernetes

Set `ZOO_KUBERNETES_NAMESPACE` (the chart does) and the Linux sandboxes Zoo runs on "this machine" become pods in that namespace (`server/kube.py`). Servers added under Servers keep working as before. Placement compares the cluster, as the most memory any one sandbox node has left unrequested, with every other host.

| | How it works |
|---|---|
| Pod | `zoo-sandbox-<id>`, under the RuntimeClass (`kata`), with 2 GiB of memory and 2 CPUs (limits), as on Docker. `NET_RAW` is dropped, privilege escalation is off and the default seccomp profile applies. |
| Home | The claim `zoo-home-<id>`. On first use an init container copies the image's `/home/zoo` into it, as Docker does for a new volume. Stopping a sandbox deletes its pod and keeps the claim. |
| Guest | zoo-guest in the pod dials the gateway's Service. Tool calls, terminals and file transfers go through it. Without it they fall back to the pods/exec API, which also covers root commands. |
| Desktop | Zoo reaches the pod's noVNC port (6080) at the pod's address. From outside the cluster (a kubeconfig), desktops go through the guest's tunnel instead. |
| Snapshots | With `sandboxes.snapshotClass`, CSI VolumeSnapshots; restoring replaces the claim with one made from the snapshot. Without one, a copy into a claim `zoo-snap-<id>`, made by a helper pod on the sandbox's node. |
| Moves | To and from Docker hosts and zoo-node servers, through object storage when it is configured, else streamed through the API. |
| Warm pool | Pooled pods are booted, wait until their guest connects, and then have every process but init stopped (`SIGSTOP`). A pod can't be paused, so this is the next best thing: it keeps its memory and uses no CPU. A claim wakes it (`SIGCONT`) in well under a second, where starting a pod takes seconds. |

Zoo needs these permissions, all of which the chart grants:

- in the sandbox namespace: pods, `pods/exec`, PersistentVolumeClaims and VolumeSnapshots;
- across the cluster, read-only: nodes, pods (for free capacity), RuntimeClasses, StorageClasses and VolumeSnapshotClasses.

### Network

There are two layers.

- **The baseline, a NetworkPolicy from the chart.**
  - Sandboxes reach DNS, the gateway and the internet, but none of `sandboxes.networkPolicy.blockedCIDRs` (cloud metadata by default).
  - Only Zoo's pods reach a sandbox, and only on port 6080.
  - It needs a CNI that enforces NetworkPolicy, such as Cilium or Calico.
  - Some CNIs also apply the internet rule (`0.0.0.0/0`) to pod addresses. On those, add your pod and service CIDRs to `blockedCIDRs` to keep sandboxes off the rest of the cluster; the gateway and DNS stay open, since they are allowed by name.
- **Each sandbox's own policy, enforced by the egress daemon.** The daemon is the same one as on Docker hosts (`zoo-guest -egress`), run as a DaemonSet in the host's network namespace with only `NET_ADMIN`. The API writes the policy to the daemon on the sandbox's node, and the daemon enforces it with nftables and a filtering proxy outside the sandbox: allowed and denied domains, addresses and DNS. Root inside the sandbox can't change it.
  - The daemon sees pod traffic as the host does, which is what kindnet, flannel, Calico and Cilium do by default.
  - Cilium with eBPF host routing bypasses the host's netfilter. Set `bpf.hostLegacyRouting=true` there.

### Requirements check

`helm test <release>` runs `python -m server.kube check --probe`. The Servers page shows the same checks; an admin can run the probe from there too. It checks:

- the API, and Zoo's access to the sandbox namespace;
- that the RuntimeClass exists, and which ready nodes it can schedule onto;
- **KVM on those nodes**: the labels kata-deploy and node-feature-discovery set (`katacontainers.io/kata-runtime`, `cpu-cpuid.VMX`/`SVM`), or a KubeVirt KVM device;
- a default StorageClass (or the one you named), and the VolumeSnapshotClass if you set one;
- that the egress daemon runs on every sandbox node;
- with `--probe`, a pod under the RuntimeClass on every sandbox node (the kubelet's `pause` image). It reaching Running proves the runtime, and for Kata KVM, works there.

Kata needs KVM, so nodes must be one of:

- bare metal;
- cloud VMs with nested virtualization:
  - GCE with nested virtualization enabled;
  - Azure Dv3/Ev3 and newer;
  - AWS `*.metal` instances, or the instance families that support nested virtualization.

Clusters without KVM can run `sandboxes.runtimeClass=runc`, which gives each sandbox a container rather than a VM.

### kubernetes-sigs/agent-sandbox

Before writing anything of our own, we evaluated [agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) (SIG Apps). It provides:

- a `Sandbox` resource (`agents.x-k8s.io/v1beta1`): one stateful pod with a stable identity and storage;
- extensions for templates, claims and a warm pool (`SandboxTemplate`, `SandboxClaim`, `SandboxWarmPool`);
- a controller that runs them.

It fits the same problem. We use plain Pods and claims for now, for four reasons:

- **Zoo already reconciles sandboxes.** Its job queue boots, stops, retries and recovers every sandbox, on Docker, zoo-node, macOS and Windows alike. A second controller would make two owners of one pod's lifecycle.
- **The warm pool doesn't map.** Zoo's pool boots each pooled sandbox under the id its sandbox will take, so the guest token, home claim and name are already right when it is claimed. A `SandboxClaim` adopts a pre-warmed `Sandbox` under its own name instead.
- **It would be another operator to install.** Plain Pods need nothing in the cluster beyond Kata.
- **It doesn't do more for isolation.** It leaves isolation to the RuntimeClass, as we do. Its pause and hibernation are on its roadmap and not yet documented behavior.

We'll look again when its API reaches v1 and hibernation (pausing a sandbox with its state kept) lands; that is where it would do more than our pods do. The driver keeps everything Kubernetes-specific in `server/kube.py`, so moving to `Sandbox` resources would replace that file and nothing else.

## macOS and Windows with the cluster

Macs and Hyper-V hosts can't join the cluster, so they join the control plane instead:

1. Set `gateway.nodes.endpoint` to the zoo-node load balancer's address (`kubectl get service <release>-nodes`), port 7443.
2. Add each host under **Servers > Add a server**. Its zoo-node dials the gateway, as described in [nodes.md](nodes.md).

The same goes for Linux servers outside the cluster.

The guests in their VMs dial `wss://<apiHost>/guest/connect`, which the Ingress routes to the gateway.

## Testing

- **Every pull request that touches the driver or the chart** runs the driver's tests (`tests/kubernetes`) on a kind cluster in CI, with a `runc` RuntimeClass. They cover:
  - the requirements check with its probe pod;
  - a sandbox pod's lifecycle: the seeded home, exec as the sandbox user and as root, binary archives both ways, adopting a running pod, and the warm pool's pause and resume;
  - snapshots and restores;
  - moving a home from the cluster to a Docker host.
- **Nightly**, the same tests run on a real cluster with Kata, from the `ZOO_NIGHTLY_KUBECONFIG` secret.
- **Every pull request** also lints the chart and renders it with each database and secrets mode.

To run the driver's tests locally:

```sh
kind create cluster && kubectl apply -f tests/kubernetes/runtimeclass-runc.yaml
docker build -t zoo-kube-test:1 tests/kubernetes && kind load docker-image zoo-kube-test:1
ZOO_TEST_KUBERNETES=zoo-test ZOO_TEST_RUNTIME_CLASS=runc uv run pytest tests/kubernetes
```

## Limits

- **One gateway.** It is a single pod. While it restarts, which takes seconds, tool calls through guests wait or fail, and nodes reconnect on their own.
- **Shared `/data`.** It must be ReadWriteMany once more than one Zoo pod runs.
- **runc sandboxes are less confined than on Docker.** They get the runtime's default seccomp profile rather than Zoo's stricter one and its AppArmor profile, because a Localhost profile would have to be installed on every node. Under Kata, each sandbox is its own VM and that doesn't apply.
- **No pids limit per sandbox.** Kubernetes sets pid limits per node, in the kubelet's `podPidsLimit`.
