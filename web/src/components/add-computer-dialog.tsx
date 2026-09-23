import { Plus } from "lucide-react"
import { useState } from "react"

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
import type { Computer } from "@/lib/mock-data"

export function AddComputerDialog({ onAdd }: { onAdd: (computer: Computer) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [host, setHost] = useState("")

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!name || !host) return
    onAdd({
      id: `cmp_${name.toLowerCase().replace(/\s+/g, "-")}`,
      name,
      host,
      os: "Unknown",
      status: "offline",
      cpu: 0,
      memory: 0,
      disk: 0,
      containers: 0,
      workspaces: 0,
      region: "unassigned",
      lastSeen: "never",
    })
    setName("")
    setHost("")
    setOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus />
        Add computer
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Add a computer</DialogTitle>
            <DialogDescription>
              Register a host by its SSH-reachable address. The agent installs on first connect.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4 py-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="computer-name">Name</Label>
              <Input
                id="computer-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. basement-rig"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="computer-host">Host / IP</Label>
              <Input
                id="computer-host"
                value={host}
                onChange={(event) => setHost(event.target.value)}
                placeholder="e.g. 192.168.1.60"
                required
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" type="button" />}>Cancel</DialogClose>
            <Button type="submit">Add computer</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
