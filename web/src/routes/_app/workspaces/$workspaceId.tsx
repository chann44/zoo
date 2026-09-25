import { createFileRoute, Link, notFound } from "@tanstack/react-router"
import { Cpu, Layers, MemoryStick, Power, RotateCw } from "lucide-react"

import { Page } from "@/components/page"
import { StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { computerById, workspaceById } from "@/lib/mock-data"

export const Route = createFileRoute("/_app/workspaces/$workspaceId")({
  component: WorkspaceDetailPage,
  loader: ({ params }) => {
    const workspace = workspaceById(params.workspaceId)
    if (!workspace) throw notFound()
    return workspace
  },
})

function WorkspaceDetailPage() {
  const workspace = Route.useLoaderData()
  const computer = computerById(workspace.computerId)

  return (
    <Page
      icon={Layers}
      title={
        <>
          {workspace.name}
          <StatusBadge status={workspace.status} />
        </>
      }
      description={
        <>
          {workspace.template} ·{" "}
          {computer ? (
            <Link
              to="/computers/$computerId"
              params={{ computerId: computer.id }}
              className="underline-offset-2 hover:underline"
            >
              {computer.name}
            </Link>
          ) : (
            "unassigned"
          )}
        </>
      }
      action={
        <>
          <Button variant="outline">
            <RotateCw />
            Restart
          </Button>
          <Button variant="destructive">
            <Power />
            Stop
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="CPU" value={workspace.status === "running" ? `${workspace.cpu}%` : "—"} icon={Cpu} />
        <StatCard
          label="Memory"
          value={workspace.status === "running" ? `${workspace.memory} GB` : "—"}
          icon={MemoryStick}
        />
        <StatCard label="Uptime" value={workspace.uptime} icon={RotateCw} />
        <StatCard label="Owner" value={workspace.owner} icon={Power} hint={`created ${workspace.createdAt}`} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Desktop</CardTitle>
          <CardDescription>Stream this workspace's GUI desktop directly in the browser.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex aspect-video items-center justify-center rounded-lg border border-dashed border-border bg-muted/40 text-sm text-muted-foreground">
            {workspace.status === "running"
              ? "Desktop stream preview would render here."
              : "Workspace is not running — start it to open the desktop."}
          </div>
        </CardContent>
      </Card>
    </Page>
  )
}
