import { createFileRoute } from "@tanstack/react-router"
import { Plus, Server, Trash2 } from "lucide-react"
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
import { Skeleton } from "@/components/ui/skeleton"
import {
  serverInputSchema,
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
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Server}
          title="No remote servers yet"
          description="Add a Linux machine with Docker and the zoo-sandbox image. Sandboxes can then run there."
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
}: {
  id: string
  name: string
  url: string
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
            <div className="truncate text-xs text-muted-foreground">{url}</div>
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
            <dt className="text-xs text-muted-foreground">Docker</dt>
            <dd>{s.docker_version}</dd>
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

const EMPTY: ServerInput = { name: "", docker_url: "", bind_address: "" }

function AddServerCard() {
  const create = useCreateServer()
  const [form, setForm] = useState<ServerInput>(EMPTY)
  const [error, setError] = useState<string>()

  function field(key: keyof ServerInput) {
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
          The API connects to Docker over SSH with your keys. The address must
          be reachable from the API, like a LAN or Tailscale IP, because desktop
          ports are published on it.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-2 lg:flex-row">
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
