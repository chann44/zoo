package main

// A macOS VM's screen, mouse and keyboard are driven from the host over the VM's own VNC server, so the guest
// serves only what otherwise needs SSH. Its metrics would read Linux's cgroup and /proc, which macOS lacks.
var services = []string{"exec", "pty", "files"}
