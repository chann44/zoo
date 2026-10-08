---
title: Run Claude Code inside a code sandbox
description: Code sandboxes ship with Claude Code preinstalled — give it a repo, a key and a task.
---

A `code` sandbox is headless — no desktop — with Python 3.12, Node, git, ripgrep and
**Claude Code preinstalled**. The sandbox is its own microVM, so whatever the agent does
to the machine stays in the machine.

## The short version

```python
from zoo_sdk import Zoo

zoo = Zoo()
box = zoo.create("coder", kind="code", wait=False)
box.set_secret("ANTHROPIC_API_KEY", "sk-ant-...")
box.wait()
box.stop()
box.start()  # restart so the secret is injected
box.exec("git clone https://github.com/you/repo ~/work/repo", timeout=120)
result = box.claude("fix the failing test", cwd="~/work/repo", timeout=900)
print(result["result"])
```

Why the stop and start: secrets are injected as environment variables when the sandbox
starts, so a secret attached after creation needs one restart.

`box.claude()` runs `claude -p ... --output-format json --dangerously-skip-permissions` as
the `zoo` user and returns the parsed JSON. The full example lives in
`examples/claude_code.py`.

## Keep it on a short leash

The example ships with a **deny-by-default network policy** that only allows Anthropic,
GitHub, PyPI and npm:

```python
box.set_network("deny")
box.add_rule("domain", "api.anthropic.com")
box.add_rule("domain", "github.com")
box.add_rule("domain", "pypi.org")
box.add_rule("domain", "registry.npmjs.org")
```

Network policy is enforced on the host, outside the sandbox — even root inside can't change
or get around it. See [Network and app policies](/docs/guides/policies/) for the whole
model, including DNS rules and CIDR allowlists.

:::note
`--dangerously-skip-permissions` is what makes the loop autonomous inside the sandbox. The
sandbox's own isolation — unprivileged user, no host access, host-enforced network policy —
is what makes that acceptable.
:::

## When you want a desktop instead

For tasks that need a browser or GUI apps, create a `desktop` sandbox and hand it to the
[built-in agent](/docs/guides/chat-channels/) — same registry, same permissions, screenshot
driven.
