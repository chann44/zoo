import { createFileRoute } from "@tanstack/react-router"
import { UserRound } from "lucide-react"
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
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useMe } from "@/lib/api_client"

export const Route = createFileRoute("/_app/settings")({
  component: SettingsPage,
})

function SettingsPage() {
  const { data: user } = useMe()
  const [notifyOffline, setNotifyOffline] = useState(true)
  const [notifyDeploy, setNotifyDeploy] = useState(true)
  const [autoUpdate, setAutoUpdate] = useState(false)

  return (
    <Page
      icon={UserRound}
      title="Profile"
      description="Manage your account and fleet-wide defaults."
    >

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="advanced">Advanced</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Profile</CardTitle>
              <CardDescription>
                Your admin identity for this console.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="name">Name</Label>
                  <Input id="name" defaultValue={user?.name ?? ""} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="settings-email">Email</Label>
                  <Input id="settings-email" defaultValue={user?.email} />
                </div>
              </div>
            </CardContent>
            <CardFooter className="justify-end border-t border-border pt-4">
              <Button>Save changes</Button>
            </CardFooter>
          </Card>
        </TabsContent>

        <TabsContent value="security" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Password</CardTitle>
              <CardDescription>
                Update the credentials used to sign in to this console.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="current-password">Current password</Label>
                <Input id="current-password" type="password" />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="new-password">New password</Label>
                  <Input id="new-password" type="password" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="confirm-password">Confirm password</Label>
                  <Input id="confirm-password" type="password" />
                </div>
              </div>
            </CardContent>
            <CardFooter className="justify-end border-t border-border pt-4">
              <Button>Update password</Button>
            </CardFooter>
          </Card>
        </TabsContent>

        <TabsContent value="notifications" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Alerts</CardTitle>
              <CardDescription>
                Choose what the fleet should notify you about.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col divide-y divide-border">
              <div className="flex items-center justify-between py-3 first:pt-0">
                <div>
                  <p className="text-sm font-medium">Computer goes offline</p>
                  <p className="text-xs text-muted-foreground">
                    Notify when a registered computer stops responding.
                  </p>
                </div>
                <Switch
                  checked={notifyOffline}
                  onCheckedChange={setNotifyOffline}
                />
              </div>
              <Separator className="hidden" />
              <div className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium">Workspace deploy events</p>
                  <p className="text-xs text-muted-foreground">
                    Notify on deploy, restart, and provisioning errors.
                  </p>
                </div>
                <Switch
                  checked={notifyDeploy}
                  onCheckedChange={setNotifyDeploy}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="advanced" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Fleet defaults</CardTitle>
              <CardDescription>
                Applies to newly registered computers.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Auto-update agents</p>
                  <p className="text-xs text-muted-foreground">
                    Keep the zoo agent up to date without confirmation.
                  </p>
                </div>
                <Switch checked={autoUpdate} onCheckedChange={setAutoUpdate} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </Page>
  )
}
