import { Link, useLocation } from "@tanstack/react-router"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { computerById, workspaceById } from "@/lib/mock-data"

const SECTION_LABELS: Record<string, string> = {
  sandboxes: "Sandboxes",
  monitoring: "Monitoring",
  computers: "Computers",
  workspaces: "Workspaces",
  network: "Network",
  settings: "Profile",
}

function useBreadcrumbs() {
  const pathname = useLocation({ select: (location) => location.pathname })
  const [section = "sandboxes", detail] = pathname.split("/").filter(Boolean)

  const crumbs = [
    { label: SECTION_LABELS[section] ?? section, href: `/${section}` },
  ]
  if (detail) {
    const label =
      section === "computers"
        ? (computerById(detail)?.name ?? detail)
        : section === "workspaces"
          ? (workspaceById(detail)?.name ?? detail)
          : detail
    crumbs.push({ label, href: pathname })
  }
  return crumbs
}

export function SiteHeader() {
  const crumbs = useBreadcrumbs()

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-4">
      <SidebarTrigger className="-ml-1" />
      <div className="mr-2 h-4 w-px bg-border" />
      <Breadcrumb>
        <BreadcrumbList>
          {crumbs.map((crumb, index) => (
            <span key={crumb.href} className="flex items-center gap-1.5">
              <BreadcrumbItem>
                {index === crumbs.length - 1 ? (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink render={<Link to={crumb.href} />}>
                    {crumb.label}
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {index < crumbs.length - 1 && <BreadcrumbSeparator />}
            </span>
          ))}
        </BreadcrumbList>
      </Breadcrumb>
    </header>
  )
}
