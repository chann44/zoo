import { Link, useLocation } from "@tanstack/react-router"
import { Activity, Box, Server, SquareStack, UserRound } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { NavUser } from "@/components/nav-user"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import type { User } from "@/lib/api_client"

type NavItem = { title: string; to: string; icon: LucideIcon }

const NAV: Array<{ label: string; items: Array<NavItem> }> = [
  {
    label: "Home",
    items: [
      { title: "Sandboxes", to: "/sandboxes", icon: Box },
      { title: "Monitoring", to: "/monitoring", icon: Activity },
    ],
  },
  {
    label: "Settings",
    items: [
      { title: "Remote Servers", to: "/servers", icon: Server },
      { title: "Profile", to: "/settings", icon: UserRound },
    ],
  },
]

export function AppSidebar({ user }: { user: User }) {
  const pathname = useLocation({ select: (location) => location.pathname })

  return (
    <Sidebar collapsible="icon" variant="floating">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link to="/sandboxes" />}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg border border-sidebar-border bg-sidebar-accent">
                <SquareStack className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold">zoo</span>
                <span className="truncate text-xs text-muted-foreground">
                  Personal workspace
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {NAV.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarMenu>
              {group.items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    isActive={pathname.startsWith(item.to)}
                    tooltip={item.title}
                    render={<Link to={item.to} />}
                  >
                    <item.icon />
                    <span>{item.title}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <NavUser user={user} />
        <p className="pb-1 text-center text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
          Version v0.1.0
        </p>
      </SidebarFooter>
    </Sidebar>
  )
}
