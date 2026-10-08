import { Link, createFileRoute } from "@tanstack/react-router"
import {
  Check,
  Copy,
  Download,
  ExternalLink,
  Play,
  Plus,
  Server,
  Square,
  Terminal,
  Trash2,
  Waypoints,
} from "lucide-react"
import { useState } from "react"

import { EmptyState, Page } from "@/components/page"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  serverInputSchema,
  useBaseAction,
  useBaseSetup,
  useBaseStatus,
  parseJoinLine,
  useCreateNodeToken,
  useCreateServer,
  useInstallCommand,
  useMigrateServer,
  useMonitoring,
  usePool,
  useRemoveServer,
  useServerStatus,
  useServers,
  useSetPool,
} from "@/lib/api_client"
import type { NodeInfo, PoolEntry, ServerInput } from "@/lib/api_client"
import { formatBytes, relativeTime } from "@/lib/utils"

export const Route = createFileRoute("/_app/servers")({
  component: ServersPage,
})

function ServersPage() {
  const monitoring = useMonitoring()
  // nodes join and report on their own, so the list keeps itself current
  const servers = useServers(10000)
  const host = monitoring.data?.host

  return (
    <Page
      icon={Server}
      title="Remote Servers"
      description="Machines that run your sandboxes."
    >
      {monitoring.isPending ? (
        <Skeleton className="h-36 rounded-xl" />
      ) : monitoring.error || !host ? (
        <EmptyState
          icon={Server}
          title="Can't reach the Docker host"
          description={monitoring.error?.message}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg border border-border bg-muted">
                  <Server className="size-4" />
                </div>
                <div>
                  <div className="font-medium">{host.name}</div>
                  <div className="text-xs text-muted-foreground">
                    Local · {host.os}
                  </div>
                </div>
              </div>
              <StatusBadge status="online" />
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">CPU</dt>
                <dd>
                  {host.cpus} cores · {host.architecture}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Memory</dt>
                <dd>{formatBytes(host.memory_total)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Docker</dt>
                <dd>{host.docker_version}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Containers</dt>
                <dd>{host.containers_running} running</dd>
              </div>
            </dl>
          </div>
        </div>
      )}
      {servers.data?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {servers.data.map((s) => (
            <RemoteServerCard
              key={s.id}
              id={s.id}
              name={s.name}
              url={s.docker_url}
              platform={s.platform}
              capabilities={s.capabilities}
              node={s.node}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Server}
          title="No remote servers yet"
          description="Linux sandboxes already run on this machine. Add a Linux server for more room, a Mac for macOS sandboxes or a Windows machine for Windows sandboxes."
        />
      )}
      <PoolPanel />
      <AddServerCard />
    </Page>
  )
}

const POOL_KINDS: Record<PoolEntry["kind"], string> = {
  desktop: "Desktop",
  browser: "Browser",
  code: "Code",
}

function PoolPanel() {
  const pool = usePool()
  if (!pool.data?.length) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Warm pool</CardTitle>
        <CardDescription>
          Linux sandboxes kept booted ahead of time, so a new sandbox starts in
          about a second. Each idle one uses a container&apos;s memory.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-2 pr-4 font-normal">Host</th>
                <th className="py-2 pr-4 font-normal">Kind</th>
                <th className="py-2 pr-4 font-normal">Size</th>
                <th className="py-2 pr-4 font-normal">Idle</th>
                <th className="py-2 pr-4 font-normal">Booting</th>
                <th className="py-2 pr-4 font-normal">Claimed</th>
              </tr>
            </thead>
            <tbody>
              {pool.data.map((e) => (
                <PoolRow
                  key={`${e.kind}:${e.server_id ?? "local"}`}
                  entry={e}
                />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function PoolRow({ entry }: { entry: PoolEntry }) {
  const setPool = useSetPool()
  const [size, setSize] = useState(String(entry.size))
  const value = Number(size)
  const valid = Number.isInteger(value) && value >= 0 && value <= 10
  const save = () => {
    if (valid && value !== entry.size)
      setPool.mutate({
        kind: entry.kind,
        server_id: entry.server_id,
        size: value,
      })
  }
  return (
    <tr className="border-t border-border align-top">
      <td className="py-2 pr-4">{entry.server_name}</td>
      <td className="py-2 pr-4">{POOL_KINDS[entry.kind]}</td>
      <td className="py-2 pr-4">
        <Input
          type="number"
          min={0}
          max={10}
          className="h-8 w-20"
          value={size}
          aria-invalid={!valid}
          onChange={(ev) => setSize(ev.target.value)}
          onBlur={save}
          onKeyDown={(ev) => ev.key === "Enter" && save()}
        />
        {setPool.error && (
          <div className="mt-1 text-xs text-destructive">
            {setPool.error.message}
          </div>
        )}
      </td>
      <td className="py-2 pr-4">{entry.idle}</td>
      <td className="py-2 pr-4">{entry.booting}</td>
      <td className="py-2 pr-4">
        {entry.claimed}
        {entry.error && (
          <div className="mt-1 max-w-xs text-xs text-destructive">
            Boot failed: {entry.error}
          </div>
        )}
      </td>
    </tr>
  )
}

function RemoteServerCard({
  id,
  name,
  url,
  platform,
  capabilities,
  node,
}: {
  id: string
  name: string
  url: string
  platform: Platform
  capabilities: Array<Platform>
  node: NodeInfo | null
}) {
  const status = useServerStatus(id)
  const remove = useRemoveServer()
  const migrate = useMigrateServer()
  const s = status.data

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted">
            <Server className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="font-medium">{name}</div>
            <div className="truncate text-xs text-muted-foreground">
              {PLATFORM_LABELS[platform]} ·{url}
            </div>
            <div className="text-xs text-muted-foreground">
              {capabilities.length
                ? `Runs ${capabilities.map((c) => PLATFORM_LABELS[c]).join(" and ")} sandboxes`
                : "Runs no sandboxes yet"}
            </div>
          </div>
        </div>
        <StatusBadge
          status={
            status.isPending ? "pending" : s?.online ? "online" : "offline"
          }
        />
      </div>
      {s?.online ? (
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">CPU</dt>
            <dd>{s.cpus} cores</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Memory</dt>
            <dd>{formatBytes(s.memory_total ?? 0)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">
              {platform === "linux" ? "Docker" : "OS"}
            </dt>
            <dd>{platform === "linux" ? s.docker_version : s.os}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Isolation</dt>
            <dd>
              {platform === "windows"
                ? s.microvm
                  ? "Hyper-V VM"
                  : "Hyper-V missing"
                : s.microvm
                  ? "microVM"
                  : "runtime missing"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Sandboxes</dt>
            <dd>{s.sandboxes} running</dd>
          </div>
        </dl>
      ) : (
        s?.error && (
          <p className="line-clamp-3 text-xs text-destructive">{s.error}</p>
        )
      )}
      {node && <NodePanel node={node} />}
      {platform !== "linux" && s?.online && (
        <BaseVmPanel id={id} platform={platform} />
      )}
      {!node && url.startsWith("ssh://") && (
        <p className="text-xs text-muted-foreground">
          Reached with Docker over SSH, which works until Zoo 2.0. Switching
          installs zoo-node over the same connection; SSH stays the fallback
          while the node is offline.
        </p>
      )}
      {(remove.error ?? migrate.error) && (
        <p className="text-xs text-destructive">
          {(remove.error ?? migrate.error)?.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {!node && url.startsWith("ssh://") && (
          <Button
            variant="outline"
            size="sm"
            disabled={migrate.isPending}
            onClick={() => migrate.mutate(id)}
          >
            <Waypoints />
            {migrate.isPending ? "Installing zoo-node…" : "Switch to zoo-node"}
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={remove.isPending}
          onClick={() => remove.mutate(id)}
        >
          <Trash2 />
          Remove
        </Button>
      </div>
    </div>
  )
}

function Meter({
  label,
  free,
  total,
}: {
  label: string
  free: number
  total: number
}) {
  const used = total > 0 ? Math.min(100, ((total - free) / total) * 100) : 0
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>
          {formatBytes(free)} of {formatBytes(total)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full ${used > 90 ? "bg-destructive" : "bg-primary"}`}
          style={{ width: `${used}%` }}
        />
      </div>
    </div>
  )
}

function NodePanel({ node }: { node: NodeInfo }) {
  const failing = node.checks.filter((c) => !c.ok)
  const runtimes = node.drivers.filter((d) => d.available).map((d) => d.name)
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">zoo-node</span>
        <span className="text-xs text-muted-foreground">
          {node.connected ? "connected" : "offline"}
          {node.version && ` · ${node.version}`}
          {node.seen_at && ` · seen ${relativeTime(node.seen_at)}`}
        </span>
      </div>
      {node.memory_total != null && node.memory_available != null && (
        <Meter
          label="Free memory"
          free={node.memory_available}
          total={node.memory_total}
        />
      )}
      {node.disk_total != null && node.disk_free != null && (
        <Meter
          label="Free disk"
          free={node.disk_free}
          total={node.disk_total}
        />
      )}
      <div className="text-xs text-muted-foreground">
        {runtimes.length
          ? `Runtimes: ${runtimes.join(", ")}`
          : "No runtime found"}
        {` · ${node.sandboxes} running`}
        {node.load != null && ` · load ${Math.round(node.load * 100)}%`}
      </div>
      {failing.map((c) => (
        <p key={c.name} className="text-xs text-destructive">
          {c.name}: {c.detail || "failing"}
        </p>
      ))}
      {!node.connected && (
        <p className="text-xs text-muted-foreground">
          The node dials out to the control plane; check it&apos;s running on
          the host (
          {node.os === "linux"
            ? "systemctl status zoo-node"
            : node.os === "darwin"
              ? "~/.zoo-node/node.log"
              : "the zoo-node service"}
          ).
        </p>
      )}
    </div>
  )
}

const BASE_LABELS = {
  missing: "Not installed",
  installing: "Installing",
  failed: "Install failed",
  stopped: "Ready",
  running: "Running",
}

function BaseVmPanel({
  id,
  platform,
}: {
  id: string
  platform: "macos" | "windows"
}) {
  const base = useBaseStatus(id)
  const action = useBaseAction(id)
  const setup = useBaseSetup()
  const [iso, setIso] = useState("")
  const [edition, setEdition] = useState("")
  const b = base.data
  const error = base.error ?? action.error ?? setup.error
  const windows = platform === "windows"

  function run(next: "install" | "start" | "stop") {
    action.mutate({
      id,
      action: next,
      ...(next === "install" && windows && { iso, edition }),
    })
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">Base VM</span>
        <span className="text-xs text-muted-foreground">
          {b ? BASE_LABELS[b.state] : "…"}
          {b &&
            (b.state === "stopped" || b.state === "running") &&
            (b.ready ? " · ready" : " · setup needed")}
        </span>
      </div>
      {b?.state === "stopped" && !b.ready && (
        <p className="text-xs text-muted-foreground">
          {windows
            ? "Start the base VM and wait for its setup to finish before creating Windows sandboxes."
            : "Start the base VM and finish its setup before creating macOS sandboxes."}
        </p>
      )}
      {b?.state === "installing" && (
        <div className="flex flex-col gap-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${b.progress ?? 0}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground">
            {b.message}
            {b.progress != null && ` · ${b.progress.toFixed(1)}%`}
          </span>
        </div>
      )}
      {b?.state === "failed" && b.message && (
        <p className="line-clamp-3 text-xs text-destructive">{b.message}</p>
      )}
      {b?.state === "running" && windows && !b.ready && b.message && (
        <p className="text-xs text-muted-foreground">{b.message}</p>
      )}
      {b?.state === "running" && windows && b.ready && (
        <p className="text-xs text-muted-foreground">
          Setup is done. Open the screen to install apps or change settings,
          then Stop. Stopping saves the base as the template new sandboxes start
          from.
        </p>
      )}
      {b?.state === "running" && !windows && (
        <ol className="list-decimal space-y-1 pl-4 text-xs text-muted-foreground">
          <li>
            Open the screen and finish macOS setup with a user named admin.
          </li>
          <li>
            Click Run setup and type the admin password in the Terminal it
            opens.
          </li>
          <li>
            Grant Accessibility to /usr/libexec/sshd-keygen-wrapper, install any
            apps, then Stop.
          </li>
        </ol>
      )}
      {windows && (b?.state === "missing" || b?.state === "failed") && (
        <div className="flex flex-col gap-2">
          <Input
            placeholder="ISO path on the server, or https:// URL"
            value={iso}
            onChange={(event) => setIso(event.target.value)}
          />
          <Input
            placeholder="Edition (optional, e.g. Pro)"
            value={edition}
            onChange={(event) => setEdition(event.target.value)}
          />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {(b?.state === "missing" || b?.state === "failed") && (
          <Button
            size="sm"
            disabled={action.isPending || (windows && !iso.trim())}
            onClick={() => run("install")}
          >
            <Download />
            {b.state === "failed"
              ? "Retry install"
              : windows
                ? "Install Windows"
                : "Install macOS"}
          </Button>
        )}
        {b?.state === "stopped" && (
          <Button
            size="sm"
            variant="outline"
            disabled={action.isPending}
            onClick={() => run("start")}
          >
            <Play />
            {action.isPending ? "Booting…" : "Start"}
          </Button>
        )}
        {b?.state === "running" && (
          <>
            <Button
              size="sm"
              render={
                <Link
                  to="/base/$serverId"
                  params={{ serverId: id }}
                  target="_blank"
                />
              }
            >
              <ExternalLink />
              Open screen
            </Button>
            {!windows && (
              <Button
                size="sm"
                variant="outline"
                disabled={setup.isPending}
                onClick={() => setup.mutate(id)}
              >
                <Terminal />
                {setup.isPending ? "Typing…" : "Run setup"}
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={action.isPending}
              onClick={() => run("stop")}
            >
              <Square />
              {action.isPending ? "Stopping…" : "Stop"}
            </Button>
          </>
        )}
      </div>
      {error && <p className="text-xs text-destructive">{error.message}</p>}
    </div>
  )
}

type Platform = ServerInput["platform"]

const PLATFORM_LABELS: Record<Platform, string> = {
  linux: "Linux",
  macos: "macOS",
  windows: "Windows",
}

const HOSTS: Array<{ value: Platform; label: string; runs: string }> = [
  { value: "linux", label: "Linux", runs: "Linux sandboxes" },
  { value: "macos", label: "Mac", runs: "macOS and Linux sandboxes" },
  { value: "windows", label: "Windows", runs: "Windows and Linux sandboxes" },
]

const PLATFORMS = Object.entries(PLATFORM_LABELS).map(([value, label]) => ({
  value,
  label,
}))

const EMPTY: ServerInput = {
  name: "",
  docker_url: "",
  bind_address: "",
  platform: "linux",
}

function CopyLine({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border bg-muted p-3">
      <code className="min-w-0 flex-1 font-mono text-xs break-all">{text}</code>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => {
          void navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
      >
        {copied ? <Check /> : <Copy />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  )
}

function Step({
  n,
  title,
  children,
}: {
  n: number
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-3">
      <div className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-medium">
        {n}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="text-sm font-medium">{title}</div>
        {children}
      </div>
    </div>
  )
}

function AddServerCard() {
  const [host, setHost] = useState<Platform>("linux")
  const [name, setName] = useState("")
  const token = useCreateNodeToken()
  const [ssh, setSsh] = useState(false)

  function pick(next: Platform) {
    setHost(next)
    token.reset()
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add a server</CardTitle>
        <CardDescription>
          Run one command on the machine. It checks the machine, installs what
          it needs and zoo-node, which joins this control plane and dials out to
          it, so the machine needs no inbound port and can sit behind NAT.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <Step n={1} title="Pick the machine's OS">
          <div className="grid gap-2 sm:grid-cols-3">
            {HOSTS.map((h) => (
              <button
                key={h.value}
                type="button"
                onClick={() => pick(h.value)}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  host === h.value
                    ? "border-primary bg-muted"
                    : "border-border hover:bg-muted/50"
                }`}
              >
                <div className="text-sm font-medium">{h.label}</div>
                <div className="text-xs text-muted-foreground">
                  Runs {h.runs}
                </div>
              </button>
            ))}
          </div>
        </Step>
        <Step n={2} title="Name it">
          <form
            className="flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault()
              if (name.trim())
                token.mutate({ name: name.trim(), platform: host })
            }}
          >
            <Input
              placeholder="gpu-box-1"
              value={name}
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
              className="sm:w-64"
            />
            <Button type="submit" disabled={!name.trim() || token.isPending}>
              <Plus />
              {token.isPending ? "Creating…" : "Get the command"}
            </Button>
          </form>
          {token.error && (
            <p className="text-xs text-destructive">{token.error.message}</p>
          )}
        </Step>
        {token.data && (
          <Step
            n={3}
            title={
              host === "windows"
                ? "Run this in an elevated PowerShell"
                : "Run this on the machine"
            }
          >
            <CopyLine text={token.data.install_command} />
            <p className="text-xs text-muted-foreground">
              Already set up (Docker and Kata, zoovm or Hyper-V)? Run only
              zoo-node instead:
            </p>
            <CopyLine text={token.data.join_command} />
            <p className="text-xs text-muted-foreground">
              The command works once and expires{" "}
              {relativeTime(token.data.expires_at)}. The server shows up above
              when it joins.
            </p>
          </Step>
        )}
        <button
          type="button"
          className="self-start text-xs text-muted-foreground underline"
          onClick={() => setSsh(!ssh)}
        >
          {ssh
            ? "Hide Docker over SSH"
            : "Connect over SSH instead (supported until Zoo 2.0)"}
        </button>
        {ssh && <SshServerSteps host={host} />}
      </CardContent>
    </Card>
  )
}

/** The older way: the control plane reaches the machine over SSH, so it needs an address the API can reach. */
function SshServerSteps({ host }: { host: Platform }) {
  const create = useCreateServer()
  const command = useInstallCommand(host)
  const [join, setJoin] = useState("")
  const [manual, setManual] = useState(false)
  const [error, setError] = useState<string>()
  let joined: ServerInput | null = null
  let joinError: string | undefined
  if (join.trim()) {
    try {
      joined = parseJoinLine(join)
    } catch (e) {
      joinError = (e as Error).message
    }
  }
  const target = joined

  function add(input: ServerInput) {
    setError(undefined)
    create.mutate(input, { onSuccess: () => setJoin("") })
  }

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border p-4">
      <p className="text-xs text-muted-foreground">
        The control plane reaches the machine over SSH, so use an address it can
        reach, like a LAN or Tailscale IP.
        {command.data && ` Needs ${command.data.requirements}.`}
      </p>
      <Step
        n={1}
        title={
          host === "windows"
            ? "Run this in an elevated PowerShell"
            : "Run this on the machine"
        }
      >
        {command.isPending ? (
          <Skeleton className="h-12 w-full" />
        ) : command.error ? (
          <p className="text-sm text-destructive">{command.error.message}</p>
        ) : (
          <CopyLine text={command.data.command} />
        )}
      </Step>
      <Step n={2} title="Paste the join line it prints">
        <Input
          placeholder="zoo-join:eyJwbGF0Zm9ybSI6…"
          value={join}
          onChange={(event) => setJoin(event.target.value)}
          className="font-mono"
        />
        {joinError && <p className="text-xs text-destructive">{joinError}</p>}
        {target && (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              {target.name} · {PLATFORM_LABELS[target.platform]} ·{" "}
              {target.docker_url}
            </p>
            <Button
              type="button"
              disabled={create.isPending}
              onClick={() => add(target)}
            >
              <Plus />
              {create.isPending ? "Connecting…" : "Add server"}
            </Button>
          </div>
        )}
      </Step>
      {(error ?? create.error) && (
        <p className="text-sm text-destructive">
          {error ?? create.error?.message}
        </p>
      )}
      <button
        type="button"
        className="self-start text-xs text-muted-foreground underline"
        onClick={() => setManual(!manual)}
      >
        {manual ? "Hide manual setup" : "Set up manually instead"}
      </button>
      {manual && (
        <ManualServerForm
          onAdd={add}
          pending={create.isPending}
          onError={setError}
        />
      )}
    </div>
  )
}

function ManualServerForm({
  onAdd,
  pending,
  onError,
}: {
  onAdd: (input: ServerInput) => void
  pending: boolean
  onError: (message?: string) => void
}) {
  const [form, setForm] = useState<ServerInput>(EMPTY)

  function field(key: "name" | "docker_url" | "bind_address") {
    return {
      value: form[key],
      onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
        setForm({ ...form, [key]: event.target.value }),
    }
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = serverInputSchema.safeParse(form)
    if (!parsed.success) {
      onError(parsed.error.issues[0]?.message)
      return
    }
    onAdd(parsed.data)
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2 lg:flex-row">
      <Select
        items={PLATFORMS}
        value={form.platform}
        onValueChange={(next) => next && setForm({ ...form, platform: next })}
      >
        <SelectTrigger className="lg:w-32" aria-label="Platform">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PLATFORMS.map((p) => (
            <SelectItem key={p.value} value={p.value}>
              {p.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input placeholder="Name" className="lg:w-40" {...field("name")} />
      <Input
        placeholder="ssh://user@10.0.0.5"
        className="flex-1"
        {...field("docker_url")}
      />
      <Input
        placeholder="10.0.0.5"
        className="lg:w-40"
        {...field("bind_address")}
      />
      <Button type="submit" disabled={pending}>
        <Plus />
        Add server
      </Button>
      {form.platform === "macos" && (
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={() =>
            onAdd({
              name: "This Mac",
              docker_url: "local://",
              bind_address: "127.0.0.1",
              platform: "macos",
            })
          }
        >
          Use this Mac
        </Button>
      )}
    </form>
  )
}
