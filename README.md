# Agent Sandbox

A lightweight, isolated Linux environment that gives AI agents a real computer they can interact with.

The idea is simple: every agent gets its own sandboxed Linux desktop with a browser, filesystem, terminal, and graphical interface that can be controlled programmatically.

```text
                 AI Agent
                    │
          ┌─────────┴─────────┐
          │                   │
       Actions             Observe
          │                   │
    click / type          screenshot
    keypress              screen
    shell                 state
          │                   │
          └─────────┬─────────┘
                    ▼
             Linux Sandbox
          ┌───────────────────┐
          │       XFCE        │
          │     Browser       │
          │     Terminal      │
          │    Filesystem     │
          └───────────────────┘
```

## Current Architecture

```text
Agent
  │
  │ control API
  ▼
Sandbox
  │
  ├── Xvfb
  ├── XFCE
  ├── x11vnc
  └── noVNC
```

The current version uses Docker to isolate each environment.

## Example

An agent could eventually do:

```python
sandbox = create_sandbox()

sandbox.open("https://example.com")

sandbox.click(500, 300)

sandbox.type("hello world")

sandbox.press("ENTER")

image = sandbox.screenshot()
```

The agent can interact with the environment just like a human using a computer.

## Goals

* Isolated environment for AI agents
* Ephemeral sandboxes
* Browser automation
* Programmatic mouse and keyboard control
* Screenshots and visual observation
* Terminal access
* Isolated filesystem
* Per-agent environments
* Simple API
* Fast startup and teardown

## Roadmap

### 1. Desktop Sandbox

```text
Docker
  ↓
Linux
  ↓
XFCE
  ↓
Xvfb
```

### 2. Computer Control

Add APIs for:

```text
click()
move()
type()
keypress()
scroll()
screenshot()
```

### 3. Browser

Give every sandbox its own browser instance.

```text
Agent
  ↓
Sandbox
  ↓
Browser
```

### 4. Sandbox API

```http
POST   /sandboxes
DELETE /sandboxes/:id

POST   /sandboxes/:id/click
POST   /sandboxes/:id/type
POST   /sandboxes/:id/key
GET    /sandboxes/:id/screenshot
```

### 5. Stronger Isolation

Move from Docker containers toward stronger isolation mechanisms such as microVMs when running untrusted agent workloads.

## Why?

AI agents increasingly need access to computers rather than just APIs.

Instead of giving an agent direct access to your infrastructure:

```text
Agent
  ↓
Production systems ❌
```

give it a disposable computer:

```text
Agent
  ↓
Sandbox
  ↓
Browser / Terminal / Files
```

The sandbox can be destroyed when the task is complete.

## Status

🚧 Early prototype

Currently focused on getting a single Linux desktop running inside an isolated container and accessible through the browser.

