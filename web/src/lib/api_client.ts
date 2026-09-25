import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000"
const TOKEN_KEY = "zoo.token"

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

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

export type LoginInput = z.infer<typeof loginSchema>
export type RegisterInput = z.infer<typeof registerSchema>
export type TokenResponse = z.infer<typeof tokenSchema>
export type User = z.infer<typeof userSchema>

// ---------------------------------------------------------------------------
// Token storage (localStorage only exists in the browser, never during SSR)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Fetch wrapper
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

// FastAPI returns `detail` as a string for HTTPException and as a list for validation errors.
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

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

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
}

// ---------------------------------------------------------------------------
// React Query hooks
// ---------------------------------------------------------------------------

export const queryKeys = {
  me: ["auth", "me"] as const,
}

/** The logged-in user. `data` is null when there is no token or it has expired. */
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
