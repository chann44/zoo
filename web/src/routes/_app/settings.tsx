import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { LogOut, UserRound } from "lucide-react"

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
import { useLogout, useMe } from "@/lib/api_client"

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
    </Page>
  )
}
