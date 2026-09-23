import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { SquareStack } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { getSession, setSession } from "@/lib/session"

export const Route = createFileRoute("/login")({ component: LoginPage })

function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState("admin@zoo.local")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (getSession()) {
      navigate({ to: "/", replace: true })
    }
  }, [navigate])

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!email || !password) {
      setError("Enter your email and password.")
      return
    }
    setError(null)
    setSubmitting(true)
    setSession({ email, name: "Admin" })
    navigate({ to: "/" })
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 p-6">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center justify-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <SquareStack className="size-5" />
          </div>
          <span className="text-lg font-semibold">zoo</span>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sign in to your fleet</CardTitle>
            <CardDescription>Enter your admin credentials to access the console.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="admin@zoo.local"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="mt-1 w-full" disabled={submitting}>
                Sign in
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-xs text-muted-foreground">
          Single-admin console · protect this page behind your VPN or firewall
        </p>
      </div>
    </div>
  )
}
