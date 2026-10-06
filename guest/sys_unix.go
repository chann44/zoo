//go:build !windows

package main

import (
	"os"
	"os/exec"
	"os/user"
	"strconv"
	"syscall"
)

func dropTo(name string) error {
	u, err := user.Lookup(name)
	if err != nil {
		return err
	}
	uid, _ := strconv.Atoi(u.Uid)
	gid, _ := strconv.Atoi(u.Gid)
	var groups []int
	if ids, err := u.GroupIds(); err == nil {
		for _, id := range ids {
			if g, err := strconv.Atoi(id); err == nil {
				groups = append(groups, g)
			}
		}
	}
	if err := syscall.Setgroups(groups); err != nil {
		return err
	}
	if err := syscall.Setgid(gid); err != nil {
		return err
	}
	if err := syscall.Setuid(uid); err != nil {
		return err
	}
	os.Setenv("HOME", u.HomeDir)
	os.Setenv("USER", name)
	os.Setenv("LOGNAME", name)
	return nil
}

func hideWindow(cmd *exec.Cmd) {}
