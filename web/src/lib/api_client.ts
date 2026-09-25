import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000"
const TOKEN_KEY = "zoo.token"

export const loginSchema = z.object({
  email: z.email("Enter a valid email address."),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters.")
    .max(72),
})

export const registerSchema = loginSchema
  .extend({
    name: z.string().trim().min(1, "Enter your name.").max(100),
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  })

export const tokenSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  user_id: z.string(),
})

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string().nullable(),
  avatar_url: z.string().nullable(),
})

export const sandboxStatusSchema = z.enum([
  "pending",
  "provisioning",
  "running",
  "stopped",
  "failed",
  "deleting",
  "deleted",
])

export const sandboxSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: sandboxStatusSchema,
  error_message: z.string().nullable(),
  started_at: z.string().nullable(),
  created_at: z.string(),
})

export const createSandboxSchema = z.object({
  name: z.string().trim().max(100).optional(),
})

export const execResultSchema = z.object({
  sandbox_id: z.string(),
  exit_code: z.number(),
  stdout: z.string(),
  stderr: z.string(),
  timed_out: z.boolean(),
})

const deletedSchema = z.object({ deleted: z.boolean(), id: z.string() })

export const effectSchema = z.enum(["allow", "deny"])

export const permissionSchema = z.object({
  permission: z.string(),
  action: z.string(),
  label: z.string(),
  effect: effectSchema,
})

export const networkRuleSchema = z.object({
  id: z.string(),
  rule_type: z.enum(["domain", "ip", "cidr"]),
  value: z.string(),
  effect: effectSchema,
})

export const networkSchema = z.object({
  default_action: effectSchema,
  allow_dns: z.boolean(),
  rules: z.array(networkRuleSchema),
})

export const networkRuleInputSchema = z.object({
  rule_type: networkRuleSchema.shape.rule_type,
  value: z
    .string()
    .trim()
    .min(1, "Enter a domain, IP or CIDR.")
    .max(253)
    .regex(
      /^[a-zA-Z0-9.*:/-]+$/,
      "Only letters, digits, dots, colons, / and *."
    ),
  effect: effectSchema,
})

export const appSchema = z.object({
  name: z.string(),
  binary: z.string(),
  effect: effectSchema,
})

export const monitoringSchema = z.object({
  host: z.object({
    name: z.string(),
    os: z.string(),
    architecture: z.string(),
    docker_version: z.string(),
    cpus: z.number(),
    memory_total: z.number(),
    containers_running: z.number(),
    images: z.number(),
  }),
  sandboxes: z.partialRecord(z.string(), z.number()),
  cpu_percent: z.number(),
  memory_usage: z.number(),
  usage: z.array(
    z.object({
      sandbox_id: z.string(),
      name: z.string(),
      status: z.string(),
      cpu_percent: z.number(),
      memory_usage: z.number(),
      memory_limit: z.number(),
      memory_percent: z.number(),
      network_rx: z.number(),
      network_tx: z.number(),
      pids: z.number(),
    })
  ),
  collected_at: z.string(),
})

export const secretSchema = z.object({
  id: z.string(),
  name: z.string(),
  enabled: z.boolean(),
  created_at: z.string(),
})

export const secretInputSchema = z.object({
  name: z
    .string()
    .trim()
    .regex(
      /^[A-Za-z_][A-Za-z0-9_]{0,63}$/,
      "Use an env var name like API_TOKEN."
    ),
  value: z.string().min(1, "Enter a value.").max(8192),
})

export const executionSchema = z.object({
  id: z.string(),
  tool_name: z.string(),
  status: z.string(),
  input: z.string(),
  error_message: z.string().nullable(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
})

export const apiKeySchema = z.object({
  id: z.string(),
  name: z.string(),
  key_prefix: z.string(),
  last_used_at: z.string().nullable(),
  revoked_at: z.string().nullable(),
  created_at: z.string(),
})

export const createdApiKeySchema = apiKeySchema.extend({ key: z.string() })

export type LoginInput = z.infer<typeof loginSchema>
export type RegisterInput = z.infer<typeof registerSchema>
export type TokenResponse = z.infer<typeof tokenSchema>
export type User = z.infer<typeof userSchema>
export type Sandbox = z.infer<typeof sandboxSchema>
export type SandboxStatus = z.infer<typeof sandboxStatusSchema>
export type CreateSandboxInput = z.infer<typeof createSandboxSchema>
export type ExecResult = z.infer<typeof execResultSchema>
export type Effect = z.infer<typeof effectSchema>
export type Permission = z.infer<typeof permissionSchema>
export type Network = z.infer<typeof networkSchema>
export type NetworkRuleInput = z.infer<typeof networkRuleInputSchema>
export type App = z.infer<typeof appSchema>
export type Monitoring = z.infer<typeof monitoringSchema>
export type SecretInput = z.infer<typeof secretInputSchema>
export type ApiKey = z.infer<typeof apiKeySchema>

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token)
}

function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

const errorSchema = z.object({
  detail: z.union([z.string(), z.array(z.object({ msg: z.string() }))]),
})

async function request<T extends z.ZodType>(
  path: string,
  schema: T,
  init: RequestInit = {}
): Promise<z.infer<T>> {
  const headers = new Headers(init.headers)
  headers.set("Content-Type", "application/json")
  const token = getToken()
  if (token) headers.set("Authorization", `Bearer ${token}`)

  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the API running?")
  }

  const body: unknown = await res.json().catch(() => null)

  if (!res.ok) {
    const parsed = errorSchema.safeParse(body)
    const message = !parsed.success
      ? `Request failed (${res.status})`
      : typeof parsed.data.detail === "string"
        ? parsed.data.detail
        : parsed.data.detail.map((d) => d.msg).join(", ")
    throw new ApiError(res.status, message)
  }

  return schema.parse(body)
}

export const api = {
  auth: {
    login: (input: LoginInput) =>
      request("/auth/login", tokenSchema, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    register: ({ confirmPassword: _, ...input }: RegisterInput) =>
      request("/auth/signup", tokenSchema, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    me: () => request("/auth/me", userSchema),
  },
  sandboxes: {
    list: () => request("/sandboxes", z.array(sandboxSchema)),
    get: (id: string) => request(`/sandboxes/${id}`, sandboxSchema),
    create: (input: CreateSandboxInput) =>
      request("/sandboxes", sandboxSchema, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    remove: (id: string) =>
      request(`/sandboxes/${id}`, deletedSchema, { method: "DELETE" }),
    start: (id: string) =>
      request(`/sandboxes/${id}/start`, sandboxSchema, { method: "POST" }),
    stop: (id: string) =>
      request(`/sandboxes/${id}/stop`, sandboxSchema, { method: "POST" }),
    secrets: (id: string) =>
      request(`/sandboxes/${id}/secrets`, z.array(secretSchema)),
    setSecret: (id: string, input: SecretInput) =>
      request(`/sandboxes/${id}/secrets`, z.array(secretSchema), {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    removeSecret: (id: string, secretId: string) =>
      request(`/sandboxes/${id}/secrets/${secretId}`, z.array(secretSchema), {
        method: "DELETE",
      }),
    executions: (id: string) =>
      request(`/sandboxes/${id}/executions`, z.array(executionSchema)),
    exec: (id: string, command: string) =>
      request(`/sandboxes/${id}/exec`, execResultSchema, {
        method: "POST",
        body: JSON.stringify({ command }),
      }),
    permissions: (id: string) =>
      request(`/sandboxes/${id}/permissions`, z.array(permissionSchema)),
    setPermission: (
      id: string,
      input: Pick<Permission, "permission" | "action" | "effect">
    ) =>
      request(`/sandboxes/${id}/permissions`, z.array(permissionSchema), {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    network: (id: string) => request(`/sandboxes/${id}/network`, networkSchema),
    setNetwork: (id: string, input: Omit<Network, "rules">) =>
      request(`/sandboxes/${id}/network`, networkSchema, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    addRule: (id: string, input: NetworkRuleInput) =>
      request(`/sandboxes/${id}/network/rules`, networkSchema, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    removeRule: (id: string, ruleId: string) =>
      request(`/sandboxes/${id}/network/rules/${ruleId}`, networkSchema, {
        method: "DELETE",
      }),
    apps: (id: string) => request(`/sandboxes/${id}/apps`, z.array(appSchema)),
    setApp: (id: string, binary: string, effect: Effect) =>
      request(
        `/sandboxes/${id}/apps/${encodeURIComponent(binary)}`,
        z.array(appSchema),
        { method: "PUT", body: JSON.stringify({ effect }) }
      ),
  },
  monitoring: () => request("/monitoring", monitoringSchema),
  apiKeys: {
    list: () => request("/api-keys", z.array(apiKeySchema)),
    create: (name: string) =>
      request("/api-keys", createdApiKeySchema, {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    revoke: (id: string) =>
      request(`/api-keys/${id}`, z.array(apiKeySchema), { method: "DELETE" }),
  },
}

export function sandboxBackupUrl(id: string) {
  return `${API_URL}/sandboxes/${id}/backup`
}

export const MCP_URL = `${API_URL}/mcp/`

export function sandboxSocketUrl(id: string) {
  const url = new URL(`/sandboxes/${id}/ws`, API_URL)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  url.searchParams.set("token", getToken() ?? "")
  return url.toString()
}

export const queryKeys = {
  me: ["auth", "me"] as const,
  sandboxes: ["sandboxes"] as const,
  sandbox: (id: string) => ["sandboxes", id] as const,
  permissions: (id: string) => ["sandboxes", id, "permissions"] as const,
  network: (id: string) => ["sandboxes", id, "network"] as const,
  apps: (id: string) => ["sandboxes", id, "apps"] as const,
  secrets: (id: string) => ["sandboxes", id, "secrets"] as const,
  executions: (id: string) => ["sandboxes", id, "executions"] as const,
  monitoring: ["monitoring"] as const,
  apiKeys: ["api-keys"] as const,
}

const isSettling = (status: SandboxStatus) =>
  status === "pending" || status === "provisioning" || status === "deleting"

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async (): Promise<User | null> => {
      if (!getToken()) return null
      try {
        return await api.auth.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          clearToken()
          return null
        }
        throw error
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

function useAuthMutation<TInput>(
  fn: (input: TInput) => Promise<TokenResponse>
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async (data) => {
      setToken(data.access_token)
      await queryClient.invalidateQueries({ queryKey: queryKeys.me })
    },
  })
}

export function useLogin() {
  return useAuthMutation(api.auth.login)
}

export function useRegister() {
  return useAuthMutation(api.auth.register)
}

export function useLogout() {
  const queryClient = useQueryClient()
  return () => {
    clearToken()
    queryClient.setQueryData(queryKeys.me, null)
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" })
  }
}

export function useSandboxes() {
  return useQuery({
    queryKey: queryKeys.sandboxes,
    queryFn: api.sandboxes.list,
    refetchInterval: (query) =>
      query.state.data?.some((s) => isSettling(s.status)) ? 1500 : false,
  })
}

export function useSandbox(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.sandbox(id),
    queryFn: () => api.sandboxes.get(id),
    enabled,
    refetchInterval: (query) =>
      query.state.data && isSettling(query.state.data.status) ? 1500 : false,
    retry: false,
  })
}

export function useCreateSandbox() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.sandboxes.create,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes })
    },
  })
}

export function useDeleteSandbox() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.sandboxes.remove,
    onSuccess: async (_, id) => {
      queryClient.removeQueries({ queryKey: queryKeys.sandbox(id) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes })
    },
  })
}

function useSandboxMutation<TInput, TData>(
  queryKey: ReadonlyArray<string>,
  fn: (input: TInput) => Promise<TData>
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
  })
}

export function usePermissions(id: string) {
  return useQuery({
    queryKey: queryKeys.permissions(id),
    queryFn: () => api.sandboxes.permissions(id),
  })
}

export function useSetPermission(id: string) {
  return useSandboxMutation(
    queryKeys.permissions(id),
    (input: Pick<Permission, "permission" | "action" | "effect">) =>
      api.sandboxes.setPermission(id, input)
  )
}

export function useNetwork(id: string) {
  return useQuery({
    queryKey: queryKeys.network(id),
    queryFn: () => api.sandboxes.network(id),
  })
}

export function useSetNetwork(id: string) {
  return useSandboxMutation(
    queryKeys.network(id),
    (input: Omit<Network, "rules">) => api.sandboxes.setNetwork(id, input)
  )
}

export function useAddRule(id: string) {
  return useSandboxMutation(queryKeys.network(id), (input: NetworkRuleInput) =>
    api.sandboxes.addRule(id, input)
  )
}

export function useRemoveRule(id: string) {
  return useSandboxMutation(queryKeys.network(id), (ruleId: string) =>
    api.sandboxes.removeRule(id, ruleId)
  )
}

export function useApps(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.apps(id),
    queryFn: () => api.sandboxes.apps(id),
    enabled,
  })
}

export function useSetApp(id: string) {
  return useSandboxMutation(
    queryKeys.apps(id),
    ({ binary, effect }: { binary: string; effect: Effect }) =>
      api.sandboxes.setApp(id, binary, effect)
  )
}

export function useMonitoring() {
  return useQuery({
    queryKey: queryKeys.monitoring,
    queryFn: api.monitoring,
    refetchInterval: 5000,
  })
}

export function useSandboxAction(action: "start" | "stop") {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.sandboxes[action],
    onSuccess: async (data) => {
      queryClient.setQueryData(queryKeys.sandbox(data.id), data)
      await queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes })
    },
  })
}

export function useSecrets(id: string) {
  return useQuery({
    queryKey: queryKeys.secrets(id),
    queryFn: () => api.sandboxes.secrets(id),
  })
}

export function useSetSecret(id: string) {
  return useSandboxMutation(queryKeys.secrets(id), (input: SecretInput) =>
    api.sandboxes.setSecret(id, input)
  )
}

export function useRemoveSecret(id: string) {
  return useSandboxMutation(queryKeys.secrets(id), (secretId: string) =>
    api.sandboxes.removeSecret(id, secretId)
  )
}

export function useExecutions(id: string) {
  return useQuery({
    queryKey: queryKeys.executions(id),
    queryFn: () => api.sandboxes.executions(id),
    refetchInterval: 5000,
  })
}

export function useApiKeys() {
  return useQuery({ queryKey: queryKeys.apiKeys, queryFn: api.apiKeys.list })
}

export function useCreateApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.apiKeys.create,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys })
    },
  })
}

export function useRevokeApiKey() {
  return useSandboxMutation(queryKeys.apiKeys, api.apiKeys.revoke)
}

export async function downloadBackup(id: string, name: string) {
  const res = await fetch(sandboxBackupUrl(id), {
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
  })
  if (!res.ok) throw new ApiError(res.status, "Backup failed")
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = `${name}.tar`
  a.click()
  URL.revokeObjectURL(url)
}
