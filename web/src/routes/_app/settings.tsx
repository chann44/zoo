import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  Globe,
  KeyRound,
  LogOut,
  Plus,
  Trash2,
  TriangleAlert,
  UserRound,
} from "lucide-react"
import { useState } from "react"

import { Page } from "@/components/page"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  ApiError,
  MCP_URL,
  domainInputSchema,
  useAddDomain,
  useDomains,
  useRemoveDomain,
  useApiKeys,
  useCreateApiKey,
  useLogout,
  useMe,
  useRevokeApiKey,
} from "@/lib/api_client"
import { timeAgo } from "@/lib/utils"

export const Route = createFileRoute("/_app/settings")({
  component: ProfilePage,
})

function ProfilePage() {
  const { data: user } = useMe()
  const logout = useLogout()
  const navigate = useNavigate()

  const fields = [
    { label: "Name", value: user?.name || "—" },
    { label: "Email", value: user?.email },
    { label: "User ID", value: user?.id, mono: true },
  ]

  return (
    <Page icon={UserRound} title="Profile" description="Your zoo account.">
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>Details you signed up with.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {fields.map((field) => (
            <div key={field.label} className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">
                {field.label}
              </span>
              <span className={field.mono ? "font-mono text-sm" : "text-sm"}>
                {field.value}
              </span>
            </div>
          ))}
        </CardContent>
        <CardFooter className="justify-end border-t border-border pt-4">
          <Button
            variant="outline"
            onClick={() => {
              logout()
              navigate({ to: "/login" })
            }}
          >
            <LogOut />
            Log out
          </Button>
        </CardFooter>
      </Card>
      <ApiKeysCard />
      <DomainsCard />
    </Page>
  )
}

function ApiKeysCard() {
  const keys = useApiKeys()
  const create = useCreateApiKey()
  const revoke = useRevokeApiKey()
  const [name, setName] = useState("")
  const [created, setCreated] = useState<string | null>(null)

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4" />
          API keys
        </CardTitle>
        <CardDescription>
          Use a key as <span className="font-mono">Authorization: Bearer</span>{" "}
          for the REST API, the Python SDK, or MCP at{" "}
          <span className="font-mono">{MCP_URL}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            create.mutate(name.trim(), {
              onSuccess: (data) => {
                setCreated(data.key)
                setName("")
              },
            })
          }}
        >
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Key name, e.g. claude-desktop"
          />
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            <Plus />
            Create key
          </Button>
        </form>
        {created && (
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2">
            <span className="flex-1 truncate font-mono text-xs">{created}</span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Copy key"
              onClick={() => navigator.clipboard.writeText(created)}
            >
              <Copy />
            </Button>
          </div>
        )}
        {created && (
          <p className="text-xs text-muted-foreground">
            Copy it now. You won't see this key again.
          </p>
        )}
        {keys.data?.length ? (
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {keys.data.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div className="flex min-w-0 flex-col">
                  <span>{k.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {k.key_prefix}…
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  {k.revoked_at
                    ? "Revoked"
                    : k.last_used_at
                      ? `Used ${timeAgo(k.last_used_at)}`
                      : "Never used"}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Revoke key"
                    disabled={!!k.revoked_at || revoke.isPending}
                    onClick={() => revoke.mutate(k.id)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No API keys yet.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function DomainsCard() {
  const domains = useDomains()
  const add = useAddDomain()
  const remove = useRemoveDomain()
  const [hostname, setHostname] = useState("")
  const [error, setError] = useState<string>()
  const forbidden =
    domains.error instanceof ApiError && domains.error.status === 403

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = domainInputSchema.safeParse(hostname)
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message)
      return
    }
    setError(undefined)
    add.mutate(parsed.data, { onSuccess: () => setHostname("") })
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="size-4" />
          Domains
        </CardTitle>
        <CardDescription>
          Serve this dashboard on your own domain. Point an A record at this
          server, add the domain here, and HTTPS is issued automatically on the
          first visit. Needs the stack running with{" "}
          <span className="font-mono">--profile domain</span>.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {forbidden ? (
          <p className="text-sm text-muted-foreground">
            Only admins can manage domains. Add your email to{" "}
            <span className="font-mono">ADMIN_EMAILS</span> on the API.
          </p>
        ) : (
          <>
            <form onSubmit={onSubmit} className="flex gap-2">
              <Input
                value={hostname}
                onChange={(event) => setHostname(event.target.value)}
                placeholder="zoo.example.com"
                className="flex-1"
              />
              <Button type="submit" disabled={add.isPending}>
                <Plus />
                Add domain
              </Button>
            </form>
            {(error ?? add.error ?? domains.error) && (
              <p className="text-sm text-destructive">
                {error ?? add.error?.message ?? domains.error?.message}
              </p>
            )}
            {domains.data?.length ? (
              <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
                {domains.data.map((d) => (
                  <div
                    key={d.id}
                    className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                  >
                    <div className="min-w-0">
                      <a
                        href={d.url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1 font-medium hover:underline"
                      >
                        {d.hostname}
                        <ExternalLink className="size-3" />
                      </a>
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        {d.points_here ? (
                          <CheckCircle2 className="size-3 text-emerald-500" />
                        ) : (
                          <TriangleAlert className="size-3 text-amber-500" />
                        )}
                        {d.addresses.length === 0
                          ? "No DNS record yet"
                          : d.points_here === false
                            ? `Points to ${d.addresses.join(", ")}, expected ${d.public_ip}`
                            : `Resolves to ${d.addresses.join(", ")}`}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove domain"
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(d.id)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              !domains.isPending && (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  No domains yet.
                </p>
              )
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
