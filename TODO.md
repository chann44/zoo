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
