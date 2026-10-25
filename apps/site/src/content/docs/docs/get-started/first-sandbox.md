---
title: Your first sandbox
description: Create, view and operate an isolated sandbox through the dashboard and external clients.
---

Open the printed dashboard URL and sign up. Emails in `ADMIN_EMAILS` have administrator
abilities; an API key is shown only once.

## Choose a kind

| Kind | What you get |
| --- | --- |
| `desktop` | Linux XFCE desktop with screen/input, shell and file tools |
| `browser` | Firefox-only Linux view with tabs and an address bar |
| `code` | Linux shell and files, no graphical desktop |
| `macos` / `windows` | The native OS on a prepared, enrolled VM host |

```bash
zoo create --kind browser --name research-box
```

Linux kinds run on the selected Linux Docker engine or Kubernetes runtime. Docker
isolation follows `ZOO_ISOLATION`: Kata gives each sandbox its own guest kernel, ordinary
containers share their engine kernel. Homes persist on the runtime's home volume; don't
assume a Linux home path, UID or resource default applies to every OS.

## Watch and share the screen

`zoo view SANDBOX_ID` opens the live screen in your browser. To let someone without a Zoo
account watch — or drive — it:

```python
link = box.viewer_link(mode="view", expires_in=60)  # "control" can also type and click
print(link["url"])  # open in a browser or an iframe; expires in 60 minutes
```

## Run commands and move files

```bash
zoo shell SANDBOX_ID                       # interactive shell (Linux)
zoo cp ./report.md SANDBOX_ID:work/        # in; reverse to copy out
zoo logs SANDBOX_ID -f                     # tool calls and state changes
```

```python
result = box.exec("python -c 'print(2 ** 64)'")  # exit code and output
for chunk in box.exec("make test", stream=True):  # output as it arrives
    print(chunk.data, end="")

box.write_file("work/main.py", b"print('hi')")  # makes folders too
data = box.read_file("work/out.csv")
```

The terminal and in-sandbox tools need zoo-guest; when it isn't reachable the call fails —
Zoo doesn't silently fall back to another execution path. Permissions and
[network policy](/docs/guides/policies/) apply to every request.

## Track and label

**Activity** shows tool records, **Monitoring** measured resource use, **Snapshots**
runtime data snapshots, **Profiles** portable app data. Labels group sandboxes for
listings, events and usage:

```python
box.set_labels({"team": "support", "end_user": "acme"})
for box in zoo.sandboxes(labels={"team": "support"}):
    print(box.id(), box.status())
```

## Stop, resume, delete

```python
box.stop()   # a supported VM pause can leave it resumable until a deadline
box.start()  # cold start otherwise; home data survives
box.delete()
```

A stopped sandbox marked resumable stays that way until the configured deadline
(`ZOO_PAUSE_MINUTES`, default 30); later teardown keeps home data for a cold start.
Deleting removes the sandbox's data according to its runtime's lifecycle.
