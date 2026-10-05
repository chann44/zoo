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
  useVaultSecrets,
  useServers,
} from "@/lib/api_client"

const KINDS = [
  { value: "desktop", label: "Desktop · full XFCE desktop" },
  { value: "browser", label: "Browser · Firefox with browser tools" },
  { value: "code", label: "Code · shell, files and Claude Code, no display" },
  { value: "macos", label: "macOS · full macOS desktop on a Mac server" },
  {
    value: "windows",
    label: "Windows · full Windows desktop on a Windows server",
  },
]

// Kinds that run as VMs on a server of their own platform rather than in Docker.
const VM_KINDS = ["macos", "windows"]

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
  const vault = useVaultSecrets()
  const [secretIds, setSecretIds] = useState<Array<string>>([])
  const [name, setName] = useState("")
  const [kind, setKind] = useState("desktop")
  const [server, setServer] = useState(LOCAL)
  const [profile, setProfile] = useState(NO_PROFILE)
  const [error, setError] = useState<string>()
  const vm = VM_KINDS.includes(kind)
  const platformServers = (servers.data ?? []).filter(
    (s) => s.platform === (vm ? kind : "linux")
  )

  function changeKind(next: string) {
    setKind(next)
    setServer(VM_KINDS.includes(next) ? AUTO : LOCAL)
  }

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setName("")
      setKind("desktop")
      setServer(LOCAL)
      setProfile(NO_PROFILE)
      setSecretIds([])
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
      secret_ids: secretIds,
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
              onChange={changeKind}
            />
            <Choice
              id="sandbox-server"
              label="Server"
              items={[
                ...(vm ? [] : [{ value: LOCAL, label: "This machine" }]),
                ...(platformServers.length || vm
                  ? [{ value: AUTO, label: "Least busy server" }]
                  : []),
                ...platformServers.map((s) => ({
                  value: s.id,
                  label: s.name,
                })),
              ]}
              value={server}
              onChange={setServer}
            />
            {kind !== "code" && !vm && (profiles.data?.length ?? 0) > 0 && (
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
            {(vault.data?.length ?? 0) > 0 && (
              <div className="flex flex-col gap-1.5">
                <Label>Secrets from vault</Label>
                <div className="flex flex-wrap gap-1.5">
                  {(vault.data ?? []).map((s) => {
                    const on = secretIds.includes(s.id)
                    return (
                      <Button
                        key={s.id}
                        type="button"
                        size="sm"
                        variant={on ? "default" : "outline"}
                        className="font-mono"
                        aria-pressed={on}
                        onClick={() =>
                          setSecretIds((ids) =>
                            on ? ids.filter((i) => i !== s.id) : [...ids, s.id]
                          )
                        }
                      >
                        {s.name}
                      </Button>
                    )
                  })}
                </div>
              </div>
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
