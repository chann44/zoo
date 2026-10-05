import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  Activity,
  AppWindow,
  Bot,
  Box,
  Cpu,
  Download,
  Cog,
  ExternalLink,
  KeyRound,
  Globe,
  Loader2,
  MemoryStick,
  MessagesSquare,
  MousePointerClick,
  Play,
  Plus,
  RotateCcw,
  Send,
  ShieldCheck,
  Square,
  Trash2,
  Vault,
  Workflow,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { z } from "zod"

import { EmptyState, Page } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { StatCard } from "@/components/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  agentChannelInputSchema,
  agentSettingsInputSchema,
  api,
  apiUrl,
  displayStatus,
  queryKeys,
  useAddAgentChannel,
  useAgent,
  useAgentChannels,
  useAgentSettings,
  useIntegrations,
  useRemoveAgentChannel,
  useResetAgent,
  useSaveAgentSettings,
  useStopAgent,
  downloadBackup,
  networkRuleInputSchema,
  secretInputSchema,
  useAddRule,
  useApps,
  useDeleteSandbox,
  useExecutions,
  useRemoveSecret,
  useSandboxAction,
  useSecrets,
  useAttachedSecrets,
  useToggleAttachedSecret,
  useVaultSecrets,
  useSetSecret,
  useMonitoring,
  useNetwork,
  usePermissions,
  useRemoveRule,
  useSandbox,
  useSetApp,
  useSetNetwork,
  useSetPermission,
  useApplyProfile,
  useCaptureProfile,
  useMoveSandbox,
  useProfileApps,
  useProfiles,
  useServers,
} from "@/lib/api_client"
import type {
  AgentEvent,
  AgentProviderId,
  ChatPlatform,
  NetworkRuleInput,
  Sandbox,
} from "@/lib/api_client"
import { formatBytes, timeAgo } from "@/lib/utils"

export const Route = createFileRoute("/_app/sandboxes/$sandboxId")({
  component: SandboxDetailPage,
})

const RULE_TYPES = [
  { value: "domain", label: "Domain" },
  { value: "ip", label: "IP" },
  { value: "cidr", label: "CIDR" },
]

const EFFECTS = [
  { value: "allow", label: "Allow" },
  { value: "deny", label: "Deny" },
]

function SandboxDetailPage() {
  const { sandboxId } = Route.useParams()
  const navigate = useNavigate()
  const sandbox = useSandbox(sandboxId)
  const remove = useDeleteSandbox()
  const start = useSandboxAction("start")
  const stop = useSandboxAction("stop")

  if (sandbox.isPending) {
    return (
      <Page icon={Box} title={<Skeleton className="h-6 w-40" />}>
        <Skeleton className="h-64 rounded-xl" />
      </Page>
    )
  }

  if (sandbox.error) {
    return (
      <Page icon={Box} title="Sandbox">
        <EmptyState
          icon={Box}
          title="Sandbox not found"
          description={sandbox.error.message}
          action={
            <Button variant="outline" render={<Link to="/sandboxes" />}>
              Back to sandboxes
            </Button>
          }
        />
      </Page>
    )
  }

  const data = sandbox.data
  const running = data.status === "running"
  const failed = data.status === "failed"
  const startable = data.status === "stopped" || failed
  const busy = data.job !== null

  return (
    <Page
      icon={Box}
      title={
        <>
          {data.name}
          <StatusBadge
            status={remove.isPending ? "deleting" : displayStatus(data)}
          />
        </>
      }
      description={<span className="font-mono">{data.id}</span>}
      action={
        <>
          {running ? (
            <Button
              variant="outline"
              disabled={stop.isPending || busy}
              onClick={() => stop.mutate(data.id)}
            >
              <Square />
              Stop
            </Button>
          ) : (
            <Button
              variant="outline"
              disabled={!startable || start.isPending || busy}
              onClick={() => start.mutate(data.id)}
            >
              {failed ? <RotateCcw /> : <Play />}
              {failed ? "Retry" : "Start"}
            </Button>
          )}
          <Button
            variant="outline"
            disabled={!running}
            onClick={() => void downloadBackup(data.id, data.name)}
          >
            <Download />
            Backup
          </Button>
          <Button
            variant="outline"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(data.id, {
                onSuccess: () => navigate({ to: "/sandboxes" }),
              })
            }
          >
            <Trash2 />
            Delete
          </Button>
          <Button
            disabled={!running || data.kind === "code"}
            render={
              <Link
                to="/view/$sandboxId"
                params={{ sandboxId: data.id }}
                target="_blank"
              />
            }
          >
            <ExternalLink />
            Open desktop
          </Button>
        </>
      }
    >
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          {data.kind !== "code" && (
            <TabsTrigger value="agent">Agent</TabsTrigger>
          )}
          <TabsTrigger value="permissions">Permissions</TabsTrigger>
          <TabsTrigger value="network">Network</TabsTrigger>
          <TabsTrigger value="apps">Apps</TabsTrigger>
          <TabsTrigger value="secrets">Secrets</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          {data.kind !== "code" && (
            <TabsTrigger value="profiles">Profiles</TabsTrigger>
          )}
          <TabsTrigger value="server">Server</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-4">
          <OverviewTab sandbox={data} />
        </TabsContent>
        <TabsContent value="agent" className="mt-4">
          <AgentTab sandbox={data} />
        </TabsContent>
        <TabsContent value="permissions" className="mt-4">
          <PermissionsTab sandboxId={data.id} />
        </TabsContent>
        <TabsContent value="network" className="mt-4">
          <NetworkTab sandboxId={data.id} />
        </TabsContent>
        <TabsContent value="apps" className="mt-4">
          <AppsTab sandboxId={data.id} running={running} />
        </TabsContent>
        <TabsContent value="secrets" className="mt-4 flex flex-col gap-4">
          <VaultSecretsCard sandboxId={data.id} />
          <SecretsTab sandboxId={data.id} />
        </TabsContent>
        <TabsContent value="activity" className="mt-4">
          <ActivityTab sandboxId={data.id} />
        </TabsContent>
        <TabsContent value="profiles" className="mt-4">
          <ProfilesTab sandboxId={data.id} running={running} />
        </TabsContent>
        <TabsContent value="server" className="mt-4">
          <ServerTab sandbox={data} />
        </TabsContent>
      </Tabs>
    </Page>
  )
}

function OverviewTab({ sandbox }: { sandbox: Sandbox }) {
  const monitoring = useMonitoring()
  const usage = monitoring.data?.usage.find((u) => u.sandbox_id === sandbox.id)

  const details = [
    { label: "Status", value: <StatusBadge status={displayStatus(sandbox)} /> },
    { label: "Runtime", value: "Docker · zoo-sandbox:latest" },
    { label: "Created", value: timeAgo(sandbox.created_at) },
    {
      label: "Started",
      value: sandbox.started_at ? timeAgo(sandbox.started_at) : "—",
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      {sandbox.error_message && !sandbox.job && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {sandbox.error_message}
        </p>
      )}
      {sandbox.job?.last_error && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-400">
          Attempt {sandbox.job.attempts} of {sandbox.job.max_attempts} failed,
          retrying: {sandbox.job.last_error}
        </p>
      )}
      {sandbox.unreachable && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-400">
          The host running this sandbox isn't answering. The sandbox may still
          be running; Zoo keeps checking.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="CPU"
          value={usage ? `${usage.cpu_percent.toFixed(1)}%` : "—"}
          icon={Cpu}
          hint="of 2 vCPU limit"
        />
        <StatCard
          label="Memory"
          value={usage ? formatBytes(usage.memory_usage) : "—"}
          icon={MemoryStick}
          hint={usage ? `of ${formatBytes(usage.memory_limit)}` : undefined}
        />
        <StatCard
          label="Processes"
          value={usage ? String(usage.pids) : "—"}
          icon={Workflow}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {details.map((item) => (
            <div key={item.label} className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">
                {item.label}
              </span>
              <span className="text-sm">{item.value}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

type ChatItem = { kind: string; text: string; source?: string }

const PLATFORMS: Array<{
  value: ChatPlatform
  label: string
  placeholder: string
  env: string
}> = [
  {
    value: "slack",
    label: "Slack",
    placeholder: "Channel ID, e.g. C0123ABCD",
    env: "SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET",
  },
  {
    value: "discord",
    label: "Discord",
    placeholder: "Channel ID",
    env: "DISCORD_BOT_TOKEN",
  },
  {
    value: "whatsapp",
    label: "WhatsApp",
    placeholder: "Phone number, e.g. +15551234567",
    env: "WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN and WHATSAPP_APP_SECRET",
  },
]

function AgentTab({ sandbox }: { sandbox: Sandbox }) {
  return (
    <div className="flex flex-col gap-4">
      <AgentChat sandbox={sandbox} />
      <AgentModel />
      <AgentChannels sandboxId={sandbox.id} />
    </div>
  )
}

function AgentChat({ sandbox }: { sandbox: Sandbox }) {
  const queryClient = useQueryClient()
  // A run being followed live: `cutoff` is how many stored messages precede it, `events` what it has streamed.
  const [live, setLive] = useState<{
    cutoff: number
    events: Array<ChatItem>
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const agent = useAgent(sandbox.id, live === null)
  const stop = useStopAgent(sandbox.id)
  const reset = useResetAgent(sandbox.id)
  const controller = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const running = sandbox.status === "running"

  async function follow(
    cutoff: number,
    open: (
      onEvent: (event: AgentEvent) => void,
      signal: AbortSignal
    ) => Promise<void>
  ) {
    const abort = new AbortController()
    controller.current = abort
    setError(null)
    setLive({ cutoff, events: [] })
    try {
      await open((event) => {
        if (event.type === "done") return
        setLive(
          (l) =>
            l && {
              ...l,
              events: [...l.events, { kind: event.type, text: event.text }],
            }
        )
      }, abort.signal)
    } catch (e) {
      if (!abort.signal.aborted) {
        setError(e instanceof Error ? e.message : "The agent stream failed")
      }
    } finally {
      if (!abort.signal.aborted) {
        await queryClient.refetchQueries({
          queryKey: queryKeys.agent(sandbox.id),
        })
        await queryClient.invalidateQueries({
          queryKey: queryKeys.executions(sandbox.id),
        })
        setLive(null)
      }
    }
  }

  const messages = agent.data?.messages
  const busy = live !== null || agent.data?.running === true

  // Follow runs started elsewhere (another tab, the API, Slack, Discord or WhatsApp).
  useEffect(() => {
    if (!agent.data?.running || live !== null || !messages) return
    const lastUser = messages.map((m) => m.kind).lastIndexOf("user")
    void follow(Math.max(lastUser, 0), (onEvent, signal) =>
      api.agent.attach(sandbox.id, onEvent, signal)
    )
  }, [agent.data?.running])

  useEffect(() => () => controller.current?.abort(), [])

  const items: Array<ChatItem> = [
    ...(messages ?? [])
      .slice(0, live ? live.cutoff : undefined)
      .map((m) => ({ kind: m.kind, text: m.content, source: m.source })),
    ...(live?.events ?? []),
  ]

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" })
  }, [items.length])

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = draft.trim()
    if (!message || busy) return
    setDraft("")
    void follow(messages?.length ?? 0, (onEvent, signal) =>
      api.agent.send(sandbox.id, message, onEvent, signal)
    )
  }

  const last = items.at(-1)

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="flex flex-col gap-1.5">
          <CardTitle className="flex items-center gap-2">
            <Bot className="size-4" />
            Computer-use agent
          </CardTitle>
          <CardDescription>
            A{" "}
            <a
              href="https://github.com/trycua/cua"
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
            >
              CUA
            </a>{" "}
            agent that sees and drives this sandbox's screen
            {agent.data && (
              <>
                {" "}
                with <span className="font-mono">{agent.data.model}</span>
              </>
            )}
            . Watch it live with Open desktop.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy || reset.isPending || !messages?.length}
          onClick={() => reset.mutate()}
        >
          <Trash2 />
          Clear
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex h-[28rem] flex-col gap-2 overflow-y-auto rounded-lg border border-border p-3">
          {agent.isPending ? (
            <Skeleton className="h-16" />
          ) : items.length === 0 ? (
            <p className="m-auto max-w-sm text-center text-sm text-muted-foreground">
              Describe a task, like "open Firefox and find the weather in
              Paris". The agent takes screenshots and clicks and types until
              it's done.
            </p>
          ) : (
            items.map((item, i) => <ChatLine key={i} item={item} />)
          )}
          {busy && last?.kind !== "text" && (
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              Working…
            </span>
          )}
          <div ref={bottom} />
        </div>
        {(error ?? agent.error?.message ?? reset.error?.message) && (
          <p className="text-sm text-destructive">
            {error ?? agent.error?.message ?? reset.error?.message}
          </p>
        )}
        <form onSubmit={onSubmit} className="flex gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              running
                ? "Tell the agent what to do…"
                : "Start the sandbox to chat"
            }
            disabled={!running || busy}
            className="flex-1"
          />
          {busy ? (
            <Button
              type="button"
              variant="outline"
              disabled={stop.isPending}
              onClick={() => stop.mutate()}
            >
              <Square />
              Stop
            </Button>
          ) : (
            <Button type="submit" disabled={!running || !draft.trim()}>
              <Send />
              Send
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  )
}

function ChatLine({ item }: { item: ChatItem }) {
  const external =
    item.source && PLATFORMS.find((p) => p.value === item.source)?.label
  switch (item.kind) {
    case "user":
      return (
        <div className="flex flex-col items-end gap-1 self-end">
          {external && <Badge variant="outline">{external}</Badge>}
          <p className="max-w-[80%] rounded-lg bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
            {item.text}
          </p>
        </div>
      )
    case "text":
      return (
        <p className="max-w-[80%] self-start rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap">
          {item.text}
        </p>
      )
    case "action":
      return (
        <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
          <MousePointerClick className="size-3 shrink-0" />
          {item.text}
        </span>
      )
    case "reasoning":
      return (
        <p className="text-xs whitespace-pre-wrap text-muted-foreground italic">
          {item.text}
        </p>
      )
    default:
      return <p className="text-xs text-destructive">{item.text}</p>
  }
}

function AgentModel() {
  const settings = useAgentSettings()
  const save = useSaveAgentSettings()
  const [provider, setProvider] = useState<AgentProviderId>("anthropic")
  const [model, setModel] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [apiBase, setApiBase] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const data = settings.data
  // Load the saved choice into the form; with none saved, start from the first provider's defaults.
  useEffect(() => {
    if (!data) return
    const current =
      data.providers.find((p) => p.id === data.provider) ?? data.providers[0]
    setProvider(current.id)
    setModel(data.provider ? data.model : current.default_model)
    setApiBase(data.api_base ?? "")
    setApiKey("")
  }, [data])

  if (!data) {
    return settings.error ? null : <Skeleton className="h-48" />
  }

  const providers = data.providers.map((p) => ({ value: p.id, label: p.label }))
  const selected = data.providers.find((p) => p.id === provider)!
  const keySaved = data.has_api_key && data.provider === provider

  function onProviderChange(next: AgentProviderId) {
    const target = data!.providers.find((p) => p.id === next)!
    setProvider(next)
    setModel(next === data!.provider ? data!.model : target.default_model)
    setApiBase(next === data!.provider ? (data!.api_base ?? "") : "")
    setApiKey("")
    setSaved(false)
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = agentSettingsInputSchema.safeParse({
      provider,
      model,
      api_key: apiKey.trim() || undefined,
      api_base: apiBase,
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid settings")
      return
    }
    if (
      selected.needs_key &&
      !keySaved &&
      !selected.server_key &&
      !parsed.data.api_key
    ) {
      setError(`Enter your ${selected.label} API key.`)
      return
    }
    setError(null)
    save.mutate(parsed.data, { onSuccess: () => setSaved(true) })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cog className="size-4" />
          Model
        </CardTitle>
        <CardDescription>
          {data.provider ? (
            <>
              The agent uses <span className="font-mono">{data.model}</span>{" "}
              from {data.providers.find((p) => p.id === data.provider)?.label}.
            </>
          ) : (
            <>
              The agent uses the server default,{" "}
              <span className="font-mono">{data.default_model}</span>.
            </>
          )}{" "}
          Applies to the agent in all your sandboxes. Pick a model that supports
          computer use.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Select
              items={providers}
              value={provider}
              onValueChange={(value) => value && onProviderChange(value)}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {providers.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={model}
              onChange={(e) => {
                setModel(e.target.value)
                setSaved(false)
              }}
              placeholder={selected.default_model}
              aria-label="Model"
              className="min-w-48 flex-1 font-mono"
            />
          </div>
          {selected.needs_key && (
            <Input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value)
                setSaved(false)
              }}
              aria-label="API key"
              placeholder={
                keySaved
                  ? "Key saved. Enter a new one to replace it"
                  : selected.server_key
                    ? "Optional. The server's key is used if blank"
                    : `${selected.label} API key`
              }
            />
          )}
          <Input
            value={apiBase}
            onChange={(e) => {
              setApiBase(e.target.value)
              setSaved(false)
            }}
            aria-label="Base URL"
            placeholder={
              selected.default_base
                ? `Base URL, default ${selected.default_base}`
                : "Base URL (optional, for a proxy or gateway)"
            }
            className="font-mono"
          />
          {(error ?? save.error?.message) && (
            <p className="text-sm text-destructive">
              {error ?? save.error?.message}
            </p>
          )}
          <div className="flex items-center justify-end gap-2">
            {saved && !save.isPending && (
              <span className="text-xs text-muted-foreground">Saved</span>
            )}
            {data.provider && (
              <Button
                type="button"
                variant="ghost"
                disabled={save.isPending}
                onClick={() => {
                  setSaved(false)
                  save.mutate(null)
                }}
              >
                Use server default
              </Button>
            )}
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" />}
              Save
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function AgentChannels({ sandboxId }: { sandboxId: string }) {
  const channels = useAgentChannels(sandboxId)
  const integrations = useIntegrations()
  const add = useAddAgentChannel(sandboxId)
  const remove = useRemoveAgentChannel(sandboxId)
  const [platform, setPlatform] = useState<ChatPlatform>("slack")
  const [externalId, setExternalId] = useState("")
  const [error, setError] = useState<string | null>(null)

  const selected = PLATFORMS.find((p) => p.value === platform)!
  const integration = integrations.data?.find((i) => i.platform === platform)

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = agentChannelInputSchema.safeParse({
      platform,
      external_id: externalId,
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid channel")
      return
    }
    setError(null)
    add.mutate(parsed.data, { onSuccess: () => setExternalId("") })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessagesSquare className="size-4" />
          Chat channels
        </CardTitle>
        <CardDescription>
          Messages in a linked Slack or Discord channel, or from a linked
          WhatsApp number, go to this sandbox's agent and its progress streams
          back. Anyone who can post there can control this sandbox. Send{" "}
          <span className="font-mono">stop</span> to cancel a task or{" "}
          <span className="font-mono">reset</span> to clear the conversation.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={onSubmit} className="flex flex-wrap gap-2">
          <Select
            items={PLATFORMS}
            value={platform}
            onValueChange={(value) => value && setPlatform(value)}
          >
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PLATFORMS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            placeholder={selected.placeholder}
            className="min-w-48 flex-1"
          />
          <Button type="submit" disabled={add.isPending}>
            <Plus />
            Link
          </Button>
        </form>
        {integration && !integration.configured && (
          <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            {selected.label} isn't set up on this server yet. Set{" "}
            <span className="font-mono">{selected.env}</span> on the API
            {integration.webhook_path && (
              <>
                {" "}
                and point the webhook at{" "}
                <span className="font-mono break-all">
                  {apiUrl(integration.webhook_path)}
                </span>
              </>
            )}
            .
          </p>
        )}
        {(error ?? add.error?.message ?? remove.error?.message) && (
          <p className="text-sm text-destructive">
            {error ?? add.error?.message ?? remove.error?.message}
          </p>
        )}
        {channels.data?.length ? (
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {channels.data.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">
                    {PLATFORMS.find((p) => p.value === c.platform)?.label}
                  </Badge>
                  <span className="font-mono">{c.external_id}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  Linked {timeAgo(c.created_at)}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Unlink channel"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(c.id)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No linked channels.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function PolicyNotice() {
  return (
    <p className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <ShieldCheck className="size-4 shrink-0" />
      Applied live to the running sandbox and re-applied on every start. Domains
      are resolved to IPs when the rule is applied.
    </p>
  )
}

function PermissionsTab({ sandboxId }: { sandboxId: string }) {
  const permissions = usePermissions(sandboxId)
  const setPermission = useSetPermission(sandboxId)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4" />
          Agent permissions
        </CardTitle>
        <CardDescription>
          What agents and API clients may do in this sandbox. Enforced by the
          zoo API.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col divide-y divide-border">
        {permissions.isPending && <Skeleton className="h-24" />}
        {permissions.error && (
          <p className="text-sm text-destructive">
            {permissions.error.message}
          </p>
        )}
        {permissions.data?.map((p) => (
          <div
            key={`${p.permission}.${p.action}`}
            className="flex items-center justify-between py-3 first:pt-0 last:pb-0"
          >
            <div>
              <p className="text-sm font-medium">{p.label}</p>
              <p className="font-mono text-xs text-muted-foreground">
                {p.permission}.{p.action}
              </p>
            </div>
            <Switch
              checked={p.effect === "allow"}
              disabled={setPermission.isPending}
              onCheckedChange={(checked) =>
                setPermission.mutate({
                  permission: p.permission,
                  action: p.action,
                  effect: checked ? "allow" : "deny",
                })
              }
            />
          </div>
        ))}
        {setPermission.error && (
          <p className="pt-3 text-sm text-destructive">
            {setPermission.error.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function NetworkTab({ sandboxId }: { sandboxId: string }) {
  const network = useNetwork(sandboxId)
  const setNetwork = useSetNetwork(sandboxId)
  const addRule = useAddRule(sandboxId)
  const removeRule = useRemoveRule(sandboxId)
  const [rule, setRule] = useState<NetworkRuleInput>({
    rule_type: "domain",
    value: "",
    effect: "allow",
  })
  const [ruleError, setRuleError] = useState<string>()

  function onAddRule(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = networkRuleInputSchema.safeParse(rule)
    if (!parsed.success) {
      setRuleError(z.flattenError(parsed.error).fieldErrors.value?.[0])
      return
    }
    setRuleError(undefined)
    addRule.mutate(parsed.data, {
      onSuccess: () => setRule((r) => ({ ...r, value: "" })),
    })
  }

  if (network.isPending) return <Skeleton className="h-64 rounded-xl" />
  if (network.error)
    return <p className="text-sm text-destructive">{network.error.message}</p>

  const policy = network.data
  const error = setNetwork.error ?? addRule.error ?? removeRule.error

  return (
    <div className="flex flex-col gap-4">
      <PolicyNotice />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="size-4" />
            Egress policy
          </CardTitle>
          <CardDescription>
            Default action for outbound traffic that no rule matches.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col divide-y divide-border">
          <div className="flex items-center justify-between pb-3">
            <div>
              <p className="text-sm font-medium">Block by default</p>
              <p className="text-xs text-muted-foreground">
                Only destinations allowed below are reachable.
              </p>
            </div>
            <Switch
              checked={policy.default_action === "deny"}
              disabled={setNetwork.isPending}
              onCheckedChange={(checked) =>
                setNetwork.mutate({
                  default_action: checked ? "deny" : "allow",
                  allow_dns: policy.allow_dns,
                })
              }
            />
          </div>
          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="text-sm font-medium">Allow DNS</p>
              <p className="text-xs text-muted-foreground">
                Let the sandbox resolve hostnames.
              </p>
            </div>
            <Switch
              checked={policy.allow_dns}
              disabled={setNetwork.isPending}
              onCheckedChange={(checked) =>
                setNetwork.mutate({
                  default_action: policy.default_action,
                  allow_dns: checked,
                })
              }
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Rules</CardTitle>
          <CardDescription>
            Allow or deny specific destinations.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form onSubmit={onAddRule} className="flex flex-wrap gap-2">
            <Select
              items={RULE_TYPES}
              value={rule.rule_type}
              onValueChange={(value) =>
                value && setRule((r) => ({ ...r, rule_type: value }))
              }
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RULE_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={rule.value}
              onChange={(e) =>
                setRule((r) => ({ ...r, value: e.target.value }))
              }
              placeholder={
                rule.rule_type === "domain"
                  ? "github.com"
                  : rule.rule_type === "ip"
                    ? "1.1.1.1"
                    : "10.0.0.0/8"
              }
              className="h-8 min-w-48 flex-1"
            />
            <Select
              items={EFFECTS}
              value={rule.effect}
              onValueChange={(value) =>
                value && setRule((r) => ({ ...r, effect: value }))
              }
            >
              <SelectTrigger className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EFFECTS.map((e) => (
                  <SelectItem key={e.value} value={e.value}>
                    {e.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button type="submit" disabled={addRule.isPending}>
              <Plus />
              Add rule
            </Button>
          </form>
          {(ruleError || error) && (
            <p className="text-sm text-destructive">
              {ruleError ?? error?.message}
            </p>
          )}
          {policy.rules.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No rules yet.
            </p>
          ) : (
            <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
              {policy.rules.map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span
                      className={
                        r.effect === "allow"
                          ? "w-12 text-xs font-medium text-emerald-400"
                          : "w-12 text-xs font-medium text-red-400"
                      }
                    >
                      {r.effect}
                    </span>
                    <span className="w-14 text-xs text-muted-foreground uppercase">
                      {r.rule_type}
                    </span>
                    <span className="truncate font-mono">{r.value}</span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Remove rule"
                    disabled={removeRule.isPending}
                    onClick={() => removeRule.mutate(r.id)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function AppsTab({
  sandboxId,
  running,
}: {
  sandboxId: string
  running: boolean
}) {
  const apps = useApps(sandboxId, running)
  const setApp = useSetApp(sandboxId)

  if (!running) {
    return (
      <EmptyState
        icon={AppWindow}
        title="Sandbox isn't running"
        description="Apps are read from the running desktop."
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <PolicyNotice />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AppWindow className="size-4" />
            Installed apps
          </CardTitle>
          <CardDescription>
            Desktop apps found in this sandbox and whether they may be launched.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col divide-y divide-border">
          {apps.isPending && <Skeleton className="h-48" />}
          {apps.error && (
            <p className="text-sm text-destructive">{apps.error.message}</p>
          )}
          {apps.data?.map((app) => (
            <div
              key={app.binary}
              className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0"
            >
              <div>
                <p className="text-sm font-medium">{app.name}</p>
                <p className="font-mono text-xs text-muted-foreground">
                  {app.binary}
                </p>
              </div>
              <Switch
                checked={app.effect === "allow"}
                disabled={setApp.isPending}
                onCheckedChange={(checked) =>
                  setApp.mutate({
                    binary: app.binary,
                    effect: checked ? "allow" : "deny",
                  })
                }
              />
            </div>
          ))}
          {setApp.error && (
            <p className="pt-3 text-sm text-destructive">
              {setApp.error.message}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SecretsTab({ sandboxId }: { sandboxId: string }) {
  const secrets = useSecrets(sandboxId)
  const setSecret = useSetSecret(sandboxId)
  const removeSecret = useRemoveSecret(sandboxId)
  const [error, setError] = useState<string | null>(null)

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const parsed = secretInputSchema.safeParse(
      Object.fromEntries(new FormData(form))
    )
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid secret")
      return
    }
    setError(null)
    setSecret.mutate(parsed.data, { onSuccess: () => form.reset() })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4" />
          Secrets
        </CardTitle>
        <CardDescription>
          Encrypted at rest and injected as environment variables. Changes apply
          on the next start.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row">
          <Input name="name" placeholder="API_TOKEN" className="sm:w-56" />
          <Input
            name="value"
            type="password"
            placeholder="Value"
            className="flex-1"
          />
          <Button type="submit" disabled={setSecret.isPending}>
            <Plus />
            Save secret
          </Button>
        </form>
        {(error ?? setSecret.error) && (
          <p className="text-sm text-destructive">
            {error ?? setSecret.error?.message}
          </p>
        )}
        {secrets.data?.length ? (
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {secrets.data.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <span className="font-mono">{s.name}</span>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  Added {timeAgo(s.created_at)}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Remove secret"
                    disabled={removeSecret.isPending}
                    onClick={() => removeSecret.mutate(s.id)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No secrets yet.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function VaultSecretsCard({ sandboxId }: { sandboxId: string }) {
  const vault = useVaultSecrets()
  const attached = useAttachedSecrets(sandboxId)
  const toggle = useToggleAttachedSecret(sandboxId)
  const on = new Set((attached.data ?? []).map((s) => s.id))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Vault className="size-4" />
          From vault
        </CardTitle>
        <CardDescription>
          Shared secrets from your{" "}
          <Link to="/vault" className="underline underline-offset-2">
            vault
          </Link>
          . Only the ones switched on reach this sandbox, on its next start.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {toggle.error && (
          <p className="text-sm text-destructive">{toggle.error.message}</p>
        )}
        {vault.data?.length ? (
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {vault.data.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div className="flex min-w-0 flex-col">
                  <span className="font-mono">{s.name}</span>
                  {s.description && (
                    <span className="truncate text-xs text-muted-foreground">
                      {s.description}
                    </span>
                  )}
                </div>
                <Switch
                  checked={on.has(s.id)}
                  disabled={toggle.isPending || attached.isLoading}
                  onCheckedChange={(checked) =>
                    toggle.mutate({ id: s.id, attach: checked })
                  }
                />
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-muted-foreground">
            Your vault is empty.{" "}
            <Link to="/vault" className="underline underline-offset-2">
              Add a secret
            </Link>
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function ActivityTab({ sandboxId }: { sandboxId: string }) {
  const executions = useExecutions(sandboxId)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="size-4" />
          Activity
        </CardTitle>
        <CardDescription>
          Every tool call made through the API, MCP or the agent.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {executions.data?.length ? (
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {executions.data.map((e) => (
              <div key={e.id} className="flex flex-col gap-1 px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono">{e.tool_name}</span>
                  <span className="text-xs text-muted-foreground">
                    <span
                      className={
                        e.status === "failed"
                          ? "text-red-400"
                          : e.status === "completed"
                            ? "text-emerald-400"
                            : ""
                      }
                    >
                      {e.status}
                    </span>{" "}
                    · {timeAgo(e.created_at)}
                  </span>
                </div>
                <span className="truncate font-mono text-xs text-muted-foreground">
                  {e.error_message ?? e.input}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No tool calls yet.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function ProfilesTab({
  sandboxId,
  running,
}: {
  sandboxId: string
  running: boolean
}) {
  const profiles = useProfiles()
  const apps = useProfileApps()
  const capture = useCaptureProfile(sandboxId)
  const apply = useApplyProfile(sandboxId)
  const [app, setApp] = useState("firefox")
  const [name, setName] = useState("")
  const appItems = Object.keys(apps.data ?? { firefox: "" }).map((a) => ({
    value: a,
    label: a,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle>App profiles</CardTitle>
        <CardDescription>
          Save an app's logins, cookies and settings from this sandbox, then
          load them into any sandbox. Close the app before loading a profile.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault()
            if (!name.trim()) return
            capture.mutate(
              { name: name.trim(), app },
              { onSuccess: () => setName("") }
            )
          }}
        >
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Profile name"
            className="flex-1"
          />
          <Select
            items={appItems}
            value={app}
            onValueChange={(next) => next && setApp(next)}
          >
            <SelectTrigger className="sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {appItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="submit"
            disabled={!running || capture.isPending || !name.trim()}
          >
            <Plus />
            {capture.isPending ? "Saving…" : "Save from sandbox"}
          </Button>
        </form>
        {(capture.error ?? apply.error) && (
          <p className="text-sm text-destructive">
            {(capture.error ?? apply.error)?.message}
          </p>
        )}
        {profiles.data?.length ? (
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {profiles.data.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {p.app} · {formatBytes(p.size_bytes)} ·{" "}
                    {timeAgo(p.created_at)}
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!running || apply.isPending}
                  onClick={() => apply.mutate(p.id)}
                >
                  {apply.isPending && apply.variables === p.id
                    ? "Loading…"
                    : apply.isSuccess && apply.variables === p.id
                      ? "Loaded"
                      : "Load"}
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No saved profiles yet.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function ServerTab({ sandbox }: { sandbox: Sandbox }) {
  const servers = useServers()
  const move = useMoveSandbox(sandbox.id)
  const current = sandbox.server_id ?? "local"
  const [target, setTarget] = useState(current)
  const items = [
    { value: "local", label: "This machine" },
    ...(servers.data ?? []).map((s) => ({ value: s.id, label: s.name })),
  ]
  const busy =
    sandbox.status === "running" ||
    sandbox.status === "provisioning" ||
    sandbox.job !== null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Server</CardTitle>
        <CardDescription>
          Move this sandbox and its home folder to another machine. Stop it
          first.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Select
            items={items}
            value={target}
            onValueChange={(next) => next && setTarget(next)}
          >
            <SelectTrigger className="sm:w-64">
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
          <Button
            disabled={busy || target === current || move.isPending}
            onClick={() => move.mutate(target === "local" ? null : target)}
          >
            {move.isPending ? "Moving…" : "Move sandbox"}
          </Button>
        </div>
        {busy && (
          <p className="text-sm text-muted-foreground">
            Stop the sandbox to move it.
          </p>
        )}
        {move.error && (
          <p className="text-sm text-destructive">{move.error.message}</p>
        )}
      </CardContent>
    </Card>
  )
}
