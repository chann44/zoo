# Known limitations

## Known limitations

- Linux Docker hosts with KVM only. Each microVM uses more memory than a container, beyond the 2 GB guest limit.
- Domain network rules are resolved to IPs when the rule is applied. If a site changes IPs, re-apply the policy or restart the sandbox.
- Sandboxes created before the `zoo` user and iptables were added must be stopped and started once to pick up the new image. Until then, policies and the Apps tab fail with an "outdated image" error.
- On remote servers the noVNC port is published on the address you configure. Anything that can reach that address can reach the port, but x11vnc behind it asks for the sandbox's password, which only the API has. Sandboxes started before VNC passwords were added keep a passwordless x11vnc until they are stopped and started on the rebuilt image.
- Moving a sandbox copies its whole home directory through the API host.
- SQLite with a single API process. Not built for horizontal scaling of the API itself.
