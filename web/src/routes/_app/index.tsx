import { createFileRoute, Link } from "@tanstack/react-router"
import { AppWindow, Boxes, Server, Wifi } from "lucide-react"
import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"

import { StatCard } from "@/components/stat-card"
import { StatusBadge, StatusDot } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { computers, recentActivity, usageHistory, workspaces } from "@/lib/mock-data"

export const Route = createFileRoute("/_app/")({ component: AnalyticsPage })

const chartConfig = {
  cpu: { label: "CPU", color: "var(--chart-3)" },
  memory: { label: "Memory", color: "var(--chart-2)" },
  network: { label: "Network", color: "var(--chart-1)" },
} satisfies ChartConfig

function AnalyticsPage() {
  const online = computers.filter((c) => c.status === "online").length
  const running = workspaces.filter((w) => w.status === "running").length
  const totalContainers = computers.reduce((sum, c) => sum + c.containers, 0)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Analytics</h1>
          <p className="text-sm text-muted-foreground">Fleet-wide overview across every registered computer.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" render={<Link to="/computers" />}>
            View computers
          </Button>
          <Button render={<Link to="/workspaces" />}>View workspaces</Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Computers online"
          value={`${online} / ${computers.length}`}
          icon={Server}
          hint="registered in this fleet"
        />
        <StatCard
          label="Workspaces running"
          value={`${running} / ${workspaces.length}`}
          icon={AppWindow}
          hint="GUI desktops active"
        />
        <StatCard label="Containers" value={String(totalContainers)} icon={Boxes} hint="across all computers" />
        <StatCard label="Network links" value="5" icon={Wifi} trend={{ direction: "up", label: "3 open" }} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Resource usage</CardTitle>
            <CardDescription>Aggregate CPU, memory and network across the fleet, last 24h.</CardDescription>
          </CardHeader>
          <CardContent>
            <ChartContainer config={chartConfig} className="h-64 w-full">
              <AreaChart data={usageHistory} margin={{ left: -20, right: 12 }}>
                <defs>
                  <linearGradient id="fillCpu" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-cpu)" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="var(--color-cpu)" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="fillMemory" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-memory)" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="var(--color-memory)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="time" tickLine={false} axisLine={false} tickMargin={8} fontSize={12} />
                <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                <Area
                  dataKey="cpu"
                  type="monotone"
                  fill="url(#fillCpu)"
                  stroke="var(--color-cpu)"
                  strokeWidth={2}
                />
                <Area
                  dataKey="memory"
                  type="monotone"
                  fill="url(#fillMemory)"
                  stroke="var(--color-memory)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Computers</CardTitle>
            <CardDescription>Live status per host.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {computers.map((computer) => (
              <Link
                key={computer.id}
                to="/computers/$computerId"
                params={{ computerId: computer.id }}
                className="flex items-center justify-between rounded-lg border border-border p-2.5 text-sm transition-colors hover:bg-muted/60"
              >
                <div className="flex items-center gap-2">
                  <StatusDot status={computer.status} />
                  <div>
                    <div className="font-medium">{computer.name}</div>
                    <div className="text-xs text-muted-foreground">{computer.host}</div>
                  </div>
                </div>
                <StatusBadge status={computer.status} />
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
          <CardDescription>Deployments, restarts and connectivity events across the fleet.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col divide-y divide-border">
          {recentActivity.map((event) => (
            <div key={event.id} className="flex items-center justify-between py-2.5 text-sm first:pt-0 last:pb-0">
              <div>
                <span className="font-medium">{event.message}</span>
                <span className="text-muted-foreground"> · {event.target}</span>
              </div>
              <span className="text-xs text-muted-foreground">{event.time}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
