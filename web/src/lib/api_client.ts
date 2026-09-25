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

export type LoginInput = z.infer<typeof loginSchema>
export type RegisterInput = z.infer<typeof registerSchema>
export type TokenResponse = z.infer<typeof tokenSchema>
export type User = z.infer<typeof userSchema>
export type Sandbox = z.infer<typeof sandboxSchema>
export type SandboxStatus = z.infer<typeof sandboxStatusSchema>
export type CreateSandboxInput = z.infer<typeof createSandboxSchema>
export type ExecResult = z.infer<typeof execResultSchema>

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
    exec: (id: string, command: string) =>
      request(`/sandboxes/${id}/exec`, execResultSchema, {
        method: "POST",
        body: JSON.stringify({ command }),
      }),
  },
}

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

export function useSandbox(id: string) {
  return useQuery({
    queryKey: queryKeys.sandbox(id),
    queryFn: () => api.sandboxes.get(id),
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
