import { cn } from "@/lib/utils"

const STATUS_STYLES: Record<string, string> = {
  online: "bg-emerald-50 text-emerald-700 border-emerald-200",
  running: "bg-emerald-50 text-emerald-700 border-emerald-200",
  open: "bg-emerald-50 text-emerald-700 border-emerald-200",
  degraded: "bg-amber-50 text-amber-700 border-amber-200",
  provisioning: "bg-amber-50 text-amber-700 border-amber-200",
  offline: "bg-zinc-100 text-zinc-600 border-zinc-200",
  stopped: "bg-zinc-100 text-zinc-600 border-zinc-200",
  closed: "bg-zinc-100 text-zinc-600 border-zinc-200",
  error: "bg-red-50 text-red-700 border-red-200",
  failed: "bg-red-50 text-red-700 border-red-200",
  pending: "bg-amber-50 text-amber-700 border-amber-200",
  deleting: "bg-amber-50 text-amber-700 border-amber-200",
}

const STATUS_DOT: Record<string, string> = {
  online: "bg-emerald-500",
  running: "bg-emerald-500",
  open: "bg-emerald-500",
  degraded: "bg-amber-500",
  provisioning: "bg-amber-500",
  offline: "bg-zinc-400",
  stopped: "bg-zinc-400",
  closed: "bg-zinc-400",
  error: "bg-red-500",
  failed: "bg-red-500",
  pending: "bg-amber-500",
  deleting: "bg-amber-500",
}

export function StatusDot({ status, className }: { status: string; className?: string }) {
  return <span className={cn("size-2 rounded-full", STATUS_DOT[status] ?? "bg-zinc-400", className)} />
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
        STATUS_STYLES[status] ?? "bg-zinc-100 text-zinc-600 border-zinc-200",
        className
      )}
    >
      <span className={cn("size-1.5 rounded-full", STATUS_DOT[status] ?? "bg-zinc-400")} />
      {status}
    </span>
  )
}
