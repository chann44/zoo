import { createFileRoute, Link, notFound } from "@tanstack/react-router"
import { Cpu, HardDrive, MemoryStick, Network, Server } from "lucide-react"

import { Page } from "@/components/page"
import { StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { computerById, workspacesForComputer } from "@/lib/mock-data"

export const Route = createFileRoute("/_app/computers/$computerId")({
  component: ComputerDetailPage,
  loader: ({ params }) => {
    const computer = computerById(params.computerId)
    if (!computer) throw notFound()
    return computer
  },
})

function ComputerDetailPage() {
  const computer = Route.useLoaderData()
  const hostWorkspaces = workspacesForComputer(computer.id)

  return (
    <Page
      icon={Server}
      title={
        <>
          {computer.name}
          <StatusBadge status={computer.status} />
        </>
      }
      description={`${computer.host} · ${computer.os} · ${computer.region}`}
      action={
        <>
          <Button variant="outline">Restart agent</Button>
          <Button variant="destructive">Remove</Button>
        </>
      }
    >

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="CPU" value={`${computer.cpu}%`} icon={Cpu} />
        <StatCard label="Memory" value={`${computer.memory}%`} icon={MemoryStick} />
        <StatCard label="Disk" value={`${computer.disk}%`} icon={HardDrive} />
        <StatCard label="Containers" value={String(computer.containers)} icon={Network} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspaces on this computer</CardTitle>
          <CardDescription>Containerized GUI desktops currently deployed here.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Template</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>CPU</TableHead>
                <TableHead>Memory</TableHead>
                <TableHead>Uptime</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {hostWorkspaces.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-sm text-muted-foreground">
                    No workspaces deployed on this computer yet.
                  </TableCell>
                </TableRow>
              )}
              {hostWorkspaces.map((workspace) => (
                <TableRow key={workspace.id}>
                  <TableCell>
                    <Link
                      to="/workspaces/$workspaceId"
                      params={{ workspaceId: workspace.id }}
                      className="font-medium hover:underline"
                    >
                      {workspace.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{workspace.template}</TableCell>
                  <TableCell>
                    <StatusBadge status={workspace.status} />
                  </TableCell>
                  <TableCell>{workspace.cpu}%</TableCell>
                  <TableCell>{workspace.memory} GB</TableCell>
                  <TableCell className="text-muted-foreground">{workspace.uptime}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </Page>
  )
}
