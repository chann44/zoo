import { Link, useLocation } from "@tanstack/react-router"
import { Search } from "lucide-react"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { computerById, workspaceById } from "@/lib/mock-data"

const SECTION_LABELS: Record<string, string> = {
  computers: "Computers",
  workspaces: "Workspaces",
  network: "Network",
  settings: "Settings",
}

function useBreadcrumbs() {
  const pathname = useLocation({ select: (location) => location.pathname })
  const segments = pathname.split("/").filter(Boolean)

  if (segments.length === 0) {
    return [{ label: "Analytics", href: "/" }]
  }

  const [section, detail] = segments
  const crumbs = [{ label: SECTION_LABELS[section] ?? section, href: `/${section}` }]
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
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 h-4" />
      <Breadcrumb>
        <BreadcrumbList>
          {crumbs.map((crumb, index) => (
            <span key={crumb.href} className="flex items-center gap-1.5">
              <BreadcrumbItem>
                {index === crumbs.length - 1 ? (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink render={<Link to={crumb.href} />}>{crumb.label}</BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {index < crumbs.length - 1 && <BreadcrumbSeparator />}
            </span>
          ))}
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto flex items-center gap-2">
        <div className="relative hidden sm:block">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Search…" className="h-8 w-56 pl-8 text-sm" />
          <kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            ⌘K
          </kbd>
        </div>
      </div>
    </header>
  )
}
