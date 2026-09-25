import { createFileRoute } from "@tanstack/react-router"
import { Activity, Link2, Network, ShieldCheck, Wifi } from "lucide-react"

import { Page } from "@/components/page"
import { StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { networkLinks } from "@/lib/mock-data"

export const Route = createFileRoute("/_app/network")({ component: NetworkPage })

function NetworkPage() {
  const openLinks = networkLinks.filter((link) => link.status === "open").length

  return (
    <Page icon={Network} title="Network" description="Mesh connectivity between your computers.">

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Mesh links" value={String(networkLinks.length)} icon={Link2} />
        <StatCard label="Open links" value={String(openLinks)} icon={Wifi} />
        <StatCard label="Encryption" value="WireGuard" icon={ShieldCheck} hint="all links encrypted" />
        <StatCard label="Avg latency" value="0.8ms" icon={Activity} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Links</CardTitle>
          <CardDescription>Point-to-point tunnels between computers on the fleet mesh.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Destination</TableHead>
                <TableHead>Protocol</TableHead>
                <TableHead>Port</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {networkLinks.map((link) => (
                <TableRow key={link.id}>
                  <TableCell className="font-medium">{link.source}</TableCell>
                  <TableCell className="font-medium">{link.destination}</TableCell>
                  <TableCell className="text-muted-foreground">{link.protocol}</TableCell>
                  <TableCell className="text-muted-foreground">{link.port}</TableCell>
                  <TableCell className="text-muted-foreground">{link.latency}</TableCell>
                  <TableCell>
                    <StatusBadge status={link.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </Page>
  )
}
