import { Link, createFileRoute } from "@tanstack/react-router"
import {
  Download,
  ExternalLink,
  Play,
  Plus,
  Server,
  Square,
  Terminal,
  Trash2,
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
  useCreateServer,
  useMonitoring,
  useRemoveServer,
  useServerStatus,
  useServers,
} from "@/lib/api_client"
import type { ServerInput } from "@/lib/api_client"
import { formatBytes } from "@/lib/utils"

export const Route = createFileRoute("/_app/servers")({
  component: ServersPage,
})

function ServersPage() {
  const monitoring = useMonitoring()
  const servers = useServers()
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
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Server}
          title="No remote servers yet"
          description="Add a Linux machine with Docker, an Apple Silicon Mac with zoovm for macOS sandboxes, or a Windows machine with Hyper-V for Windows sandboxes."
        />
      )}
      <AddServerCard />
    </Page>
  )
}

function RemoteServerCard({
  id,
  name,
  url,
  platform,
}: {
  id: string
  name: string
  url: string
  platform: Platform
}) {
  const status = useServerStatus(id)
  const remove = useRemoveServer()
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
      {platform !== "linux" && s?.online && (
        <BaseVmPanel id={id} platform={platform} />
      )}
      {remove.error && (
        <p className="text-xs text-destructive">{remove.error.message}</p>
      )}
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        disabled={remove.isPending}
        onClick={() => remove.mutate(id)}
      >
        <Trash2 />
        Remove
      </Button>
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

function AddServerCard() {
  const create = useCreateServer()
  const [form, setForm] = useState<ServerInput>(EMPTY)
  const [error, setError] = useState<string>()

  function field(key: Exclude<keyof ServerInput, "platform">) {
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
      setError(parsed.error.issues[0]?.message)
      return
    }
    setError(undefined)
    create.mutate(parsed.data, { onSuccess: () => setForm(EMPTY) })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add a server</CardTitle>
        <CardDescription>
          The API connects over SSH with your keys: to Docker on Linux, to zoovm
          on a Mac, or to Hyper-V on Windows. The address must be reachable from
          the API, like a LAN or Tailscale IP. If the API runs on the Mac
          itself, pick macOS and use this Mac, no SSH needed.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-2 lg:flex-row">
          <Select
            items={PLATFORMS}
            value={form.platform}
            onValueChange={(next) =>
              next && setForm({ ...form, platform: next })
            }
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
          <Button type="submit" disabled={create.isPending}>
            <Plus />
            {create.isPending ? "Connecting…" : "Add server"}
          </Button>
          {form.platform === "macos" && (
            <Button
              type="button"
              variant="outline"
              disabled={create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    name: "This Mac",
                    docker_url: "local://",
                    bind_address: "127.0.0.1",
                    platform: "macos",
                  },
                  { onSuccess: () => setForm(EMPTY) }
                )
              }
            >
              Use this Mac
            </Button>
          )}
        </form>
        {(error ?? create.error) && (
          <p className="mt-2 text-sm text-destructive">
            {error ?? create.error?.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
