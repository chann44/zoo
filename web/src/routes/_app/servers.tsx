import { createFileRoute } from "@tanstack/react-router"
import { Server } from "lucide-react"

import { EmptyState, Page } from "@/components/page"
import { StatusBadge } from "@/components/status-badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useMonitoring } from "@/lib/api_client"
import { formatBytes } from "@/lib/utils"

export const Route = createFileRoute("/_app/servers")({
  component: ServersPage,
})

function ServersPage() {
  const monitoring = useMonitoring()
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
      <EmptyState
        icon={Server}
        title="No remote servers yet"
        description="Sandboxes run on this machine's Docker. Connecting remote servers over SSH is coming next."
      />
    </Page>
  )
}
