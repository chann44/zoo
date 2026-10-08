---
title: Choosing a runtime
description: runc, Kata and Kubernetes — what each isolates, what each costs, and how to pick.
---

Zoo runs every Linux sandbox through a pluggable runtime. The choice is `ZOO_RUNTIME` on a
Docker host (`kata` or `runc`) and `ZOO_KUBERNETES_RUNTIME_CLASS` in a cluster.

| Runtime | What it is | Isolation | Needs |
| --- | --- | --- | --- |
| `kata` (default) | Kata Containers: each sandbox boots in its own lightweight VM | its own kernel per sandbox — a guest kernel escape lands in a throwaway VM, not the host | KVM (`/dev/kvm`): bare metal, or cloud VMs with nested virtualization |
| `runc` | plain containers | shares the host kernel; Zoo compensates with a tighter seccomp filter and, on AppArmor hosts, the `zoo-sandbox` profile | nothing special — works on any Docker host |
| Kubernetes pods | one pod per sandbox, under a RuntimeClass | whatever the RuntimeClass gives: `kata` as above, or the cluster default | a cluster, [kata-deploy](https://github.com/kata-containers/kata-containers/tree/main/tools/packaging/kata-deploy), nodes with KVM (for Kata) |

macOS and Windows sandboxes don't use this setting — they are always VMs: `zoovm` on
Apple's Virtualization.framework, and Hyper-V on Windows hosts.

## How to choose

- **Bare metal or nested-virtualization cloud VM** → keep the default. Kata is the reason
  every sandbox can run as root-equivalent inside without endangering the host, and the
  reason the same image works for `desktop`, `browser` and `code` kinds.
- **Development laptop or a host without KVM** → `ZOO_RUNTIME=runc`. The installer falls
  back to it automatically (and says so); expect weaker isolation, not a different feature
  set.
- **Already running a cluster** → the [Kubernetes chart](/docs/guides/kubernetes/), with
  sandboxes as Kata pods. Clusters without KVM can run `sandboxes.runtimeClass=runc`, with
  weaker isolation: the runtime's default seccomp profile replaces Zoo's stricter one and
  the `zoo-sandbox` AppArmor profile.
- **Not sure** → `zoo doctor` on a candidate host checks KVM, the sandbox runtime, disk,
  ports, DNS and the API. On Kubernetes, `helm test` runs the requirements check with a
  probe pod that proves the runtime works on every node.

## Why Kata, and not Firecracker

Zoo ships Kata, not Firecracker. Kata registers as an ordinary Docker/containerd runtime
(`io.containerd.kata.v2`), which means the same code path drives a laptop with Docker, a
bare-metal host, a remote server added through zoo-node, and a Kubernetes cluster — and
sandboxes are just containers as far as Docker is concerned. That is what keeps the
scheduler, the job system and the tool implementations runtime-agnostic. Firecracker
microVMs (the choice behind several hosted sandboxes — see the [comparison
page](/compare)) would mean maintaining a second lifecycle layer; Kata buys the same
per-sandbox kernel boundary without it.

## The cost

A microVM uses more memory than a container — beyond each sandbox's own 2 GB guest limit,
each VM carries a small kernel. On a 32 GB host, plan for roughly ten sandboxes; the
[placement rules](/docs/guides/remote-servers/#placement-and-moves) spread further
sandboxes across servers by free memory. Plain `runc` containers are lighter, at the cost
of the kernel boundary.
