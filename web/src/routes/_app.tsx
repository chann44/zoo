import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { useMe } from "@/lib/api_client"

export const Route = createFileRoute("/_app")({ component: AppLayout })

function AppLayout() {
  const navigate = useNavigate()
  // The token lives in localStorage, so the user is resolved on the client after mount.
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
        <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
