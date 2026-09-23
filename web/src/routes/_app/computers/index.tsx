import { createFileRoute, Link } from "@tanstack/react-router"
import { MoreHorizontal } from "lucide-react"
import { useState } from "react"

import { AddComputerDialog } from "@/components/add-computer-dialog"
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
import { computers as initialComputers, type Computer } from "@/lib/mock-data"

export const Route = createFileRoute("/_app/computers/")({ component: ComputersPage })

function ComputersPage() {
  const [computers, setComputers] = useState<Computer[]>(initialComputers)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Computers</h1>
          <p className="text-sm text-muted-foreground">Hosts registered to run workspaces and containers.</p>
        </div>
        <AddComputerDialog onAdd={(computer) => setComputers((prev) => [computer, ...prev])} />
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>OS</TableHead>
                <TableHead>CPU</TableHead>
                <TableHead>Memory</TableHead>
                <TableHead>Containers</TableHead>
                <TableHead>Workspaces</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {computers.map((computer) => (
                <TableRow key={computer.id}>
                  <TableCell>
                    <Link
                      to="/computers/$computerId"
                      params={{ computerId: computer.id }}
                      className="font-medium hover:underline"
                    >
                      {computer.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{computer.host}</div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={computer.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">{computer.os}</TableCell>
                  <TableCell>{computer.status === "offline" ? "—" : `${computer.cpu}%`}</TableCell>
                  <TableCell>{computer.status === "offline" ? "—" : `${computer.memory}%`}</TableCell>
                  <TableCell>{computer.containers}</TableCell>
                  <TableCell>{computer.workspaces}</TableCell>
                  <TableCell className="text-muted-foreground">{computer.lastSeen}</TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" />}>
                        <MoreHorizontal />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          render={<Link to="/computers/$computerId" params={{ computerId: computer.id }} />}
                        >
                          View details
                        </DropdownMenuItem>
                        <DropdownMenuItem>Restart agent</DropdownMenuItem>
                        <DropdownMenuItem variant="destructive">Remove computer</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
