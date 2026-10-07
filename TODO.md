## TODOS

Focus only on linux for now just polish things and make linux usable first

Tools
- [x] Organize tools by category
- [x] connect tools to api
- [x] single adapter pattern to register all of the tools as well to access

DB
- [x] create schema for admin, workspaces, apps, permissions, network_permissions, file_permissions, command_permissions, runs
- [x] add crud routes for all of these
- [x] Backups

Docker
- [x] lifecycle methods for creating, stopping, starting, destroying the containers
- [x] sync the status to db
- [x] monitoring service to monitor all of the docker containers running
- [x] allow users to spin sandboxes on other machines, on the same network or another one

API
- [x] auth api
- [x] admins api
- [x] api keys
- [x] monitoring api

UI
- [x] build dashboards
- [x] move to tanstack start instead of the react version

PACKAGE
- [x] a python package for agents (sdk/python)
- [x] a package for cua agents with an agent loop

MISC
- [x] allow users to connect domains to their dashboards
- [x] rerouting and also certificates
- [x] spin up clusters on multiple machines as well
- [x] file system backups as well
- [x] open telemetry for tracing all requests, tool calls, db queries
- [x] logs with grafana
- [x] sync data to other machines as well
- [x] secret manager
- [x] embed profiles in the applications in these containers
- [x] add support for just code execution sandboxes, browser tools

Windows: making it solid
Windows stays a first-class platform. The work is the same as macOS: setup automation, recovery and parity.
- [x] Package windows/*.ps1 as a versioned release asset; the API uploads the version that matches it and checks the hash
- [x] zoo node install --windows: turns on Hyper-V and OpenSSH, installs the base VM from an ISO unattended (already partly done)
- [x] Template versioning: each frozen template gets a version, recorded on every sandbox
- [x] Differencing disks for new VMs and report clone time; target under 60 s to a usable desktop
- [x] Recovery: detect a hung VM or a stuck guest session (no VNC frames, no agent heartbeat) and restart it
- [x] Replace SSH and agent.ps1 with zoo-guest (Phase 3)
- [x] Licensing guidance in the docs (evaluation ISO, volume licensing), because teams will ask
- [x] Close matrix gaps: app profiles (Phase 4), monitoring (Phase 3), move between hosts (Phase 5), Store app blocking (Phase 4)
- [x] Host-side network policy through the Hyper-V switch (Phase 4)
- [x] Recorded-fixture tests in CI plus a nightly end-to-end run on a real Hyper-V host
- [x] Docs: supported Windows versions, Hyper-V requirements, troubleshooting
