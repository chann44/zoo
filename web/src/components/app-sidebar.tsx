import { Link, useLocation } from "@tanstack/react-router"
import {
  ChevronRight,
  LayoutDashboard,
  Network,
  Server,
  Settings,
  SquareStack,
} from "lucide-react"

import { NavUser } from "@/components/nav-user"
import { StatusDot } from "@/components/status-badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
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
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar"
import { computers, workspaces } from "@/lib/mock-data"
import type { User } from "@/lib/api_client"

export function AppSidebar({ user }: { user: User }) {
  const pathname = useLocation({ select: (location) => location.pathname })

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link to="/" />}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <SquareStack className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold">zoo</span>
                <span className="truncate text-xs text-muted-foreground">
                  Fleet console
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Overview</SidebarGroupLabel>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/"}
                tooltip="Analytics"
                render={<Link to="/" />}
              >
                <LayoutDashboard />
                <span>Analytics</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Fleet</SidebarGroupLabel>
          <SidebarMenu>
            <Collapsible
              defaultOpen
              className="group/collapsible"
              render={<SidebarMenuItem />}
            >
              <CollapsibleTrigger
                render={
                  <SidebarMenuButton
                    isActive={pathname.startsWith("/computers")}
                    tooltip="Computers"
                  />
                }
              >
                <Server />
                <span>Computers</span>
                <ChevronRight className="ml-auto transition-transform group-data-[panel-open]/collapsible:rotate-90" />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <SidebarMenuSub>
                  {computers.map((computer) => (
                    <SidebarMenuSubItem key={computer.id}>
                      <SidebarMenuSubButton
                        isActive={pathname === `/computers/${computer.id}`}
                        render={
                          <Link
                            to="/computers/$computerId"
                            params={{ computerId: computer.id }}
                          />
                        }
                      >
                        <span className="truncate">{computer.name}</span>
                        <StatusDot
                          status={computer.status}
                          className="ml-auto shrink-0"
                        />
                      </SidebarMenuSubButton>
                    </SidebarMenuSubItem>
                  ))}
                  <SidebarMenuSubItem>
                    <SidebarMenuSubButton
                      isActive={pathname === "/computers"}
                      render={<Link to="/computers" />}
                    >
                      View all computers
                    </SidebarMenuSubButton>
                  </SidebarMenuSubItem>
                </SidebarMenuSub>
              </CollapsibleContent>
            </Collapsible>

            <Collapsible
              defaultOpen
              className="group/collapsible"
              render={<SidebarMenuItem />}
            >
              <CollapsibleTrigger
                render={
                  <SidebarMenuButton
                    isActive={pathname.startsWith("/workspaces")}
                    tooltip="Workspaces"
                  />
                }
              >
                <SquareStack />
                <span>Workspaces</span>
                <ChevronRight className="ml-auto transition-transform group-data-[panel-open]/collapsible:rotate-90" />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <SidebarMenuSub>
                  {workspaces.map((workspace) => (
                    <SidebarMenuSubItem key={workspace.id}>
                      <SidebarMenuSubButton
                        isActive={pathname === `/workspaces/${workspace.id}`}
                        render={
                          <Link
                            to="/workspaces/$workspaceId"
                            params={{ workspaceId: workspace.id }}
                          />
                        }
                      >
                        <span className="truncate">{workspace.name}</span>
                        <StatusDot
                          status={workspace.status}
                          className="ml-auto shrink-0"
                        />
                      </SidebarMenuSubButton>
                    </SidebarMenuSubItem>
                  ))}
                  <SidebarMenuSubItem>
                    <SidebarMenuSubButton
                      isActive={pathname === "/workspaces"}
                      render={<Link to="/workspaces" />}
                    >
                      View all workspaces
                    </SidebarMenuSubButton>
                  </SidebarMenuSubItem>
                </SidebarMenuSub>
              </CollapsibleContent>
            </Collapsible>

            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/network"}
                tooltip="Network"
                render={<Link to="/network" />}
              >
                <Network />
                <span>Network</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>

        <SidebarGroup className="mt-auto">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={pathname === "/settings"}
                tooltip="Settings"
                render={<Link to="/settings" />}
              >
                <Settings />
                <span>Settings</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <NavUser user={user} />
      </SidebarFooter>
    </Sidebar>
  )
}
