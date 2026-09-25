import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { useMe } from "@/lib/api_client"

export const Route = createFileRoute("/_app")({ component: AppLayout })

function AppLayout() {
  const navigate = useNavigate()
  const { data: user, isPending } = useMe()

  useEffect(() => {
    if (!isPending && !user) {
      navigate({ to: "/login", replace: true })
    }
  }, [isPending, user, navigate])

  if (!user) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-background" />
    )
  }

  return (
    <SidebarProvider>
      <AppSidebar user={user} />
      <SidebarInset>
        <SiteHeader />
        <main className="flex flex-1 flex-col px-2 pb-2 md:px-4 md:pb-4">
          <div className="flex flex-1 flex-col rounded-xl border border-border bg-sidebar/40 p-1.5">
            <div className="flex flex-1 flex-col rounded-lg border border-border bg-background">
              <Outlet />
            </div>
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
