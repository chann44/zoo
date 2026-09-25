import { Plus } from "lucide-react"
import { useState } from "react"

import { FieldError } from "@/components/auth-shell"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { createSandboxSchema, useCreateSandbox } from "@/lib/api_client"

export function CreateSandboxDialog() {
  const create = useCreateSandbox()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [error, setError] = useState<string>()

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setName("")
      setError(undefined)
      create.reset()
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = createSandboxSchema.safeParse({ name: name || undefined })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message)
      return
    }
    create.mutate(parsed.data, { onSuccess: () => handleOpenChange(false) })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button />}>
        <Plus />
        Create Sandbox
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create a sandbox</DialogTitle>
            <DialogDescription>
              Spin up a fresh desktop container from the zoo-sandbox image.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5 py-4">
            <Label htmlFor="sandbox-name">Name</Label>
            <Input
              id="sandbox-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. research-box"
              maxLength={100}
              autoFocus
            />
            <FieldError message={error ?? create.error?.message} />
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" type="button" />}>
              Cancel
            </DialogClose>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
