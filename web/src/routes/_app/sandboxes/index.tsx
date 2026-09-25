import { createFileRoute, Link } from "@tanstack/react-router"
import { ExternalLink, Plus, Trash2 } from "lucide-react"
import { useState } from "react"

import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  createSandboxSchema,
  useCreateSandbox,
  useDeleteSandbox,
  useSandboxes,
} from "@/lib/api_client"

export const Route = createFileRoute("/_app/sandboxes/")({
  component: SandboxesPage,
})

function SandboxesPage() {
  const sandboxes = useSandboxes()
  const create = useCreateSandbox()
  const remove = useDeleteSandbox()
  const [name, setName] = useState("")

  function onCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = createSandboxSchema.safeParse({ name: name || undefined })
    if (!parsed.success) return
    create.mutate(parsed.data, { onSuccess: () => setName("") })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Sandboxes</h1>
          <p className="text-sm text-muted-foreground">
            Disposable GUI desktops you can open in the browser.
          </p>
        </div>
        <form onSubmit={onCreate} className="flex gap-2">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (optional)"
            maxLength={100}
            className="h-8 w-48"
          />
          <Button type="submit" disabled={create.isPending}>
            <Plus />
            {create.isPending ? "Creating…" : "New sandbox"}
          </Button>
        </form>
      </div>

      {(create.error || remove.error) && (
        <p className="text-sm text-destructive">
          {(create.error ?? remove.error)?.message}
        </p>
      )}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-40" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sandboxes.isPending && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-6 text-center text-sm text-muted-foreground"
                  >
                    Loading sandboxes…
                  </TableCell>
                </TableRow>
              )}
              {sandboxes.error && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-6 text-center text-sm text-destructive"
                  >
                    {sandboxes.error.message}
                  </TableCell>
                </TableRow>
              )}
              {sandboxes.data?.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-6 text-center text-sm text-muted-foreground"
                  >
                    No sandboxes yet. Spin one up to get started.
                  </TableCell>
                </TableRow>
              )}
              {sandboxes.data?.map((sandbox) => (
                <TableRow key={sandbox.id}>
                  <TableCell>
                    <div className="font-medium">{sandbox.name}</div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {sandbox.id.slice(0, 8)}
                    </div>
                    {sandbox.error_message && (
                      <div className="text-xs text-destructive">
                        {sandbox.error_message}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={sandbox.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(`${sandbox.created_at}Z`).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={sandbox.status !== "running"}
                        render={
                          <Link
                            to="/view/$sandboxId"
                            params={{ sandboxId: sandbox.id }}
                            target="_blank"
                          />
                        }
                      >
                        <ExternalLink />
                        Open
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Delete sandbox"
                        disabled={
                          remove.isPending && remove.variables === sandbox.id
                        }
                        onClick={() => remove.mutate(sandbox.id)}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
