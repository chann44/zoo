//go:build !windows

package main

import (
	"encoding/json"
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

// secretsFile holds the sandbox's secrets when it was claimed from the warm pool: pooled containers boot before
// they have an owner, so their secrets aren't in the container's environment.
const secretsFile = "/run/zoo/env.json"

// secretEnv is read on every command, so secrets written after the guest started still reach it.
func secretEnv() []string {
	data, err := os.ReadFile(secretsFile)
	if err != nil {
		return nil
	}
	var values map[string]string
	if json.Unmarshal(data, &values) != nil {
		return nil
	}
	env := make([]string, 0, len(values))
	for k, v := range values {
		env = append(env, k+"="+v)
	}
	return env
}
