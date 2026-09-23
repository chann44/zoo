export type ComputerStatus = "online" | "offline" | "degraded"

export type Computer = {
  id: string
  name: string
  host: string
  os: string
  status: ComputerStatus
  cpu: number
  memory: number
  disk: number
  containers: number
  workspaces: number
  region: string
  lastSeen: string
}

export const computers: Computer[] = [
  {
    id: "cmp_atlas",
    name: "atlas",
    host: "10.0.4.12",
    os: "Ubuntu 24.04 LTS",
    status: "online",
    cpu: 42,
    memory: 61,
    disk: 38,
    containers: 12,
    workspaces: 3,
    region: "sfo-home-rack",
    lastSeen: "just now",
  },
  {
    id: "cmp_forge",
    name: "forge",
    host: "10.0.4.18",
    os: "Ubuntu 24.04 LTS",
    status: "online",
    cpu: 78,
    memory: 84,
    disk: 55,
    containers: 20,
    workspaces: 5,
    region: "sfo-home-rack",
    lastSeen: "just now",
  },
  {
    id: "cmp_nimbus",
    name: "nimbus",
    host: "192.168.1.42",
    os: "Debian 12",
    status: "degraded",
    cpu: 91,
    memory: 88,
    disk: 72,
    containers: 8,
    workspaces: 2,
    region: "office-closet",
    lastSeen: "2 min ago",
  },
  {
    id: "cmp_relay",
    name: "relay",
    host: "192.168.1.51",
    os: "Ubuntu 22.04 LTS",
    status: "offline",
    cpu: 0,
    memory: 0,
    disk: 47,
    containers: 0,
    workspaces: 0,
    region: "office-closet",
    lastSeen: "3 hours ago",
  },
]

export type WorkspaceStatus = "running" | "stopped" | "provisioning" | "error"

export type Workspace = {
  id: string
  name: string
  template: string
  computerId: string
  status: WorkspaceStatus
  cpu: number
  memory: number
  owner: string
  uptime: string
  createdAt: string
}

export const workspaces: Workspace[] = [
  {
    id: "ws_design",
    name: "design-desktop",
    template: "GNOME Desktop · GIMP, Inkscape",
    computerId: "cmp_atlas",
    status: "running",
    cpu: 24,
    memory: 3.1,
    owner: "chan",
    uptime: "4d 6h",
    createdAt: "2026-09-10",
  },
  {
    id: "ws_render",
    name: "render-farm-1",
    template: "Ubuntu Desktop · Blender",
    computerId: "cmp_forge",
    status: "running",
    cpu: 88,
    memory: 11.4,
    owner: "chan",
    uptime: "1d 2h",
    createdAt: "2026-09-19",
  },
  {
    id: "ws_browser",
    name: "sandbox-browser",
    template: "XFCE Desktop · Firefox",
    computerId: "cmp_forge",
    status: "provisioning",
    cpu: 6,
    memory: 0.6,
    owner: "chan",
    uptime: "—",
    createdAt: "2026-09-23",
  },
  {
    id: "ws_dev",
    name: "dev-box",
    template: "Ubuntu Desktop · VS Code",
    computerId: "cmp_nimbus",
    status: "stopped",
    cpu: 0,
    memory: 0,
    owner: "chan",
    uptime: "—",
    createdAt: "2026-08-30",
  },
  {
    id: "ws_ci",
    name: "ci-runner",
    template: "Alpine · headless",
    computerId: "cmp_relay",
    status: "error",
    cpu: 0,
    memory: 0,
    owner: "chan",
    uptime: "—",
    createdAt: "2026-09-02",
  },
]

export const usageHistory = [
  { time: "00:00", cpu: 32, memory: 48, network: 12 },
  { time: "04:00", cpu: 28, memory: 46, network: 9 },
  { time: "08:00", cpu: 54, memory: 58, network: 24 },
  { time: "12:00", cpu: 71, memory: 66, network: 41 },
  { time: "16:00", cpu: 66, memory: 70, network: 37 },
  { time: "20:00", cpu: 49, memory: 61, network: 22 },
  { time: "23:59", cpu: 40, memory: 57, network: 18 },
]

export type ActivityEvent = {
  id: string
  message: string
  target: string
  time: string
  kind: "deploy" | "start" | "stop" | "error" | "join"
}

export const recentActivity: ActivityEvent[] = [
  { id: "a1", message: "Workspace deployed", target: "design-desktop on atlas", time: "5 min ago", kind: "deploy" },
  { id: "a2", message: "Workspace provisioning", target: "sandbox-browser on forge", time: "18 min ago", kind: "start" },
  { id: "a3", message: "Computer went offline", target: "relay", time: "3 hours ago", kind: "error" },
  { id: "a4", message: "Workspace stopped", target: "dev-box on nimbus", time: "6 hours ago", kind: "stop" },
  { id: "a5", message: "Computer joined fleet", target: "nimbus", time: "1 day ago", kind: "join" },
]

export type NetworkLink = {
  id: string
  source: string
  destination: string
  protocol: "TCP" | "UDP"
  port: number
  status: "open" | "closed"
  latency: string
}

export const networkLinks: NetworkLink[] = [
  { id: "n1", source: "atlas", destination: "forge", protocol: "TCP", port: 51820, status: "open", latency: "0.4ms" },
  { id: "n2", source: "atlas", destination: "nimbus", protocol: "TCP", port: 51820, status: "open", latency: "1.1ms" },
  { id: "n3", source: "forge", destination: "nimbus", protocol: "TCP", port: 51820, status: "open", latency: "0.9ms" },
  { id: "n4", source: "atlas", destination: "relay", protocol: "TCP", port: 51820, status: "closed", latency: "—" },
  { id: "n5", source: "forge", destination: "relay", protocol: "UDP", port: 41641, status: "closed", latency: "—" },
]

export function computerById(id: string) {
  return computers.find((c) => c.id === id)
}

export function workspaceById(id: string) {
  return workspaces.find((w) => w.id === id)
}

export function workspacesForComputer(computerId: string) {
  return workspaces.filter((w) => w.computerId === computerId)
}
