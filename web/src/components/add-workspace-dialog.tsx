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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { Computer, Workspace } from "@/lib/mock-data"

const TEMPLATES = [
  "Ubuntu Desktop · VS Code",
  "GNOME Desktop · GIMP, Inkscape",
  "XFCE Desktop · Firefox",
  "Ubuntu Desktop · Blender",
]

export function AddWorkspaceDialog({
  computers,
  onAdd,
}: {
  computers: Computer[]
  onAdd: (workspace: Workspace) => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [computerId, setComputerId] = useState(computers[0]?.id ?? "")
  const [template, setTemplate] = useState(TEMPLATES[0])

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!name || !computerId) return
    onAdd({
      id: `ws_${name.toLowerCase().replace(/\s+/g, "-")}`,
      name,
      template,
      computerId,
      status: "provisioning",
      cpu: 0,
      memory: 0,
      owner: "admin",
      uptime: "—",
      createdAt: new Date().toISOString().slice(0, 10),
    })
    setName("")
    setOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus />
        Add workspace
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Deploy a workspace</DialogTitle>
            <DialogDescription>Spin up a containerized GUI desktop on one of your computers.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4 py-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="workspace-name">Name</Label>
              <Input
                id="workspace-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. video-edit-box"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Computer</Label>
              <Select value={computerId} onValueChange={(value) => value && setComputerId(value)}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Choose a computer" />
                </SelectTrigger>
                <SelectContent>
                  {computers.map((computer) => (
                    <SelectItem key={computer.id} value={computer.id}>
                      {computer.name} · {computer.host}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Template</Label>
              <Select value={template} onValueChange={(value) => value && setTemplate(value)}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Choose a template" />
                </SelectTrigger>
                <SelectContent>
                  {TEMPLATES.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" type="button" />}>Cancel</DialogClose>
            <Button type="submit">Deploy workspace</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
