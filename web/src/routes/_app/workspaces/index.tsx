import { createFileRoute, Link } from "@tanstack/react-router"
import { MoreHorizontal } from "lucide-react"
import { useState } from "react"

import { AddWorkspaceDialog } from "@/components/add-workspace-dialog"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { computers, computerById, workspaces as initialWorkspaces, type Workspace } from "@/lib/mock-data"

export const Route = createFileRoute("/_app/workspaces/")({ component: WorkspacesPage })

function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>(initialWorkspaces)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Workspaces</h1>
          <p className="text-sm text-muted-foreground">Containerized GUI desktops deployed across your computers.</p>
        </div>
        <AddWorkspaceDialog computers={computers} onAdd={(workspace) => setWorkspaces((prev) => [workspace, ...prev])} />
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Computer</TableHead>
                <TableHead>Template</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>CPU</TableHead>
                <TableHead>Memory</TableHead>
                <TableHead>Uptime</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspaces.map((workspace) => {
                const computer = computerById(workspace.computerId)
                return (
                  <TableRow key={workspace.id}>
                    <TableCell>
                      <Link
                        to="/workspaces/$workspaceId"
                        params={{ workspaceId: workspace.id }}
                        className="font-medium hover:underline"
                      >
                        {workspace.name}
                      </Link>
                      <div className="text-xs text-muted-foreground">{workspace.owner}</div>
                    </TableCell>
                    <TableCell>
                      {computer ? (
                        <Link
                          to="/computers/$computerId"
                          params={{ computerId: computer.id }}
                          className="text-muted-foreground hover:text-foreground hover:underline"
                        >
                          {computer.name}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{workspace.template}</TableCell>
                    <TableCell>
                      <StatusBadge status={workspace.status} />
                    </TableCell>
                    <TableCell>{workspace.status === "running" ? `${workspace.cpu}%` : "—"}</TableCell>
                    <TableCell>{workspace.status === "running" ? `${workspace.memory} GB` : "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{workspace.uptime}</TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" />}>
                          <MoreHorizontal />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            render={<Link to="/workspaces/$workspaceId" params={{ workspaceId: workspace.id }} />}
                          >
                            Open desktop
                          </DropdownMenuItem>
                          <DropdownMenuItem>Restart</DropdownMenuItem>
                          <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
