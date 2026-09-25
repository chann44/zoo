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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  createSandboxSchema,
  useCreateSandbox,
  useProfiles,
  useServers,
} from "@/lib/api_client"

const KINDS = [
  { value: "desktop", label: "Desktop · full XFCE desktop" },
  { value: "browser", label: "Browser · Firefox with browser tools" },
  { value: "code", label: "Code · shell, files and Claude Code, no display" },
]

const LOCAL = "local"
const AUTO = "auto"
const NO_PROFILE = "none"

function Choice({
  id,
  label,
  items,
  value,
  onChange,
}: {
  id: string
  label: string
  items: Array<{ value: string; label: string }>
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        items={items}
        value={value}
        onValueChange={(next) => next && onChange(next)}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function CreateSandboxDialog() {
  const create = useCreateSandbox()
  const [open, setOpen] = useState(false)
  const servers = useServers()
  const profiles = useProfiles()
  const [name, setName] = useState("")
  const [kind, setKind] = useState("desktop")
  const [server, setServer] = useState(LOCAL)
  const [profile, setProfile] = useState(NO_PROFILE)
  const [error, setError] = useState<string>()

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setName("")
      setKind("desktop")
      setServer(LOCAL)
      setProfile(NO_PROFILE)
      setError(undefined)
      create.reset()
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = createSandboxSchema.safeParse({
      name: name || undefined,
      kind,
      server_id: server === LOCAL ? null : server,
      profile_ids: profile === NO_PROFILE ? [] : [profile],
    })
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
              Pick what the agent needs and where it should run.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4 py-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="sandbox-name">Name</Label>
              <Input
                id="sandbox-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. research-box"
                maxLength={100}
                autoFocus
              />
            </div>
            <Choice
              id="sandbox-kind"
              label="Type"
              items={KINDS}
              value={kind}
              onChange={setKind}
            />
            <Choice
              id="sandbox-server"
              label="Server"
              items={[
                { value: LOCAL, label: "This machine" },
                ...(servers.data?.length
                  ? [{ value: AUTO, label: "Least busy server" }]
                  : []),
                ...(servers.data ?? []).map((s) => ({
                  value: s.id,
                  label: s.name,
                })),
              ]}
              value={server}
              onChange={setServer}
            />
            {kind !== "code" && (profiles.data?.length ?? 0) > 0 && (
              <Choice
                id="sandbox-profile"
                label="Profile"
                items={[
                  { value: NO_PROFILE, label: "Fresh profile" },
                  ...(profiles.data ?? []).map((p) => ({
                    value: p.id,
                    label: `${p.name} · ${p.app}`,
                  })),
                ]}
                value={profile}
                onChange={setProfile}
              />
            )}
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
