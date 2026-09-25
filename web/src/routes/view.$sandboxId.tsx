import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"

import type RFB from "@novnc/novnc"
import { sandboxSocketUrl, useMe, useSandbox } from "@/lib/api_client"

export const Route = createFileRoute("/view/$sandboxId")({
  component: SandboxView,
})

function SandboxView() {
  const { sandboxId } = Route.useParams()
  const navigate = useNavigate()
  const { data: user, isPending } = useMe()
  const sandbox = useSandbox(sandboxId)
  const screenRef = useRef<HTMLDivElement>(null)
  const [connected, setConnected] = useState(false)

  const running = !!user && sandbox.data?.status === "running"

  useEffect(() => {
    if (!isPending && !user) {
      navigate({ to: "/login", replace: true })
    }
  }, [isPending, user, navigate])

  useEffect(() => {
    const screen = screenRef.current
    if (!running || !screen) return

    let rfb: RFB | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let closed = false

    async function connect() {
      const { default: RFBClient } = await import("@novnc/novnc")
      if (closed || !screen) return
      rfb = new RFBClient(screen, sandboxSocketUrl(sandboxId))
      rfb.scaleViewport = true
      rfb.background = "#000"
      rfb.addEventListener("connect", () => {
        setConnected(true)
        rfb?.focus()
      })
      rfb.addEventListener("disconnect", () => {
        setConnected(false)
        if (!closed) retry = setTimeout(connect, 1500)
      })
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      rfb?.disconnect()
    }
  }, [running, sandboxId])

  const message = sandbox.error
    ? sandbox.error.message
    : sandbox.data?.status === "failed"
      ? (sandbox.data.error_message ?? "Sandbox failed to start.")
      : sandbox.data && sandbox.data.status !== "running"
        ? `Sandbox is ${sandbox.data.status}…`
        : !connected
          ? "Connecting…"
          : null

  return (
    <div className="relative h-svh w-screen overflow-hidden bg-black">
      <div ref={screenRef} className="h-full w-full" />
      {message && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-400">
          {message}
        </div>
      )}
    </div>
  )
}
