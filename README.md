# Zoo

Zoo is a self-hostable sandbox platform that gives AI agents real computers: isolated Linux desktops they can drive over an API, with a live VNC view for humans.

![Zoo](assets/screenshot.png)

## ✨ Features

Zoo includes multiple features to make your agents' lives easier.

- **Sandboxes**: Spin up isolated Linux desktops (XFCE, browser, terminal, filesystem) in Docker, one per agent.
- **Computer Control**: Drive the mouse, keyboard, windows, and apps programmatically.
- **Shell**: Run commands inside any sandbox.
- **Filesystem**: List, read, write, upload, download, move, copy, and delete files.
- **Screenshots & Live View**: Capture screenshots or watch the desktop live over noVNC.
- **Actions API**: Manage everything through REST and WebSocket.
- **MCP Server**: Expose sandbox actions as MCP tools for Claude, Cursor, and other MCP clients.
- **Real-time Monitoring**: Monitor CPU, memory, and network usage for every sandbox.
- **Multi Server**: Run sandboxes on remote machines over SSH.
- **Integrations**: Drive sandboxes from Slack, Discord, and WhatsApp.
- **Web App**: Manage sandboxes and computers from a dashboard.
- **Self-Hosted**: Run Zoo on your own machine or VPS.

## Architecture

![Zoo architecture](assets/architecture.png)
