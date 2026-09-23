import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router"
import { useEffect, useState } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { getSession, type Session } from "@/lib/session"

export const Route = createFileRoute("/_app")({ component: AppLayout })

function AppLayout() {
  const navigate = useNavigate()
  // Session lives in localStorage only, so it can't be read during SSR — check on mount instead.
  const [session, setSession] = useState<Session | null | undefined>(undefined)

  useEffect(() => {
    const current = getSession()
    if (!current) {
      navigate({ to: "/login", replace: true })
      return
    }
    setSession(current)
  }, [navigate])

  if (!session) {
    return <div className="flex min-h-svh items-center justify-center bg-background" />
  }

  return (
    <SidebarProvider>
      <AppSidebar session={session} />
      <SidebarInset>
        <SiteHeader />
        <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
