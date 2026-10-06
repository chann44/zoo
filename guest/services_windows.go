package main

import (
	"context"
	"errors"
	"os/exec"
	"syscall"
)

// The host drives the screen, mouse and keyboard over the VM's VNC server (TightVNC), so the guest offers commands,
// files, terminals and window control.
var services = []string{"exec", "pty", "files", "windows"}

// reportMetrics is never started on Windows; metrics read Linux's cgroup and /proc.
func reportMetrics(ctx context.Context, send func(any, []byte) error) {}

// dropTo is Unix only: on Windows the guest starts as the desktop user already.
func dropTo(name string) error { return errors.New("-user is not supported on Windows") }

// hideWindow keeps a console command from opening a window: the guest is a GUI-subsystem program with no console
// of its own to share.
func hideWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW
}
