//go:build !windows

package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"os/user"
	"strconv"
	"syscall"
	"time"
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

// secretsFile holds the sandbox's secrets when it was claimed from the warm pool (pooled containers boot before they
// have an owner, so their secrets aren't in the container's environment) and every secret change made while it runs.
var secretsFile = "/run/zoo/env.json"

// unsetFile lists secrets removed while the sandbox runs that are still in the container's environment from boot.
var unsetFile = "/run/zoo/unset.json"

// readJSON reads a file the API may be rewriting this moment: a read that catches it half-written is retried.
func readJSON(path string, into any) bool {
	for attempt := 0; attempt < 3; attempt++ {
		data, err := os.ReadFile(path)
		if err != nil {
			return false
		}
		if json.Unmarshal(data, into) == nil {
			return true
		}
		time.Sleep(20 * time.Millisecond)
	}
	return false
}

// secretEnv is read on every command, so secrets written after the guest started still reach it.
func secretEnv() []string {
	var values map[string]string
	if !readJSON(secretsFile, &values) {
		return nil
	}
	env := make([]string, 0, len(values))
	for k, v := range values {
		env = append(env, k+"="+v)
	}
	return env
}

// baseEnv is the guest's own environment without the secrets that were removed since the sandbox booted.
func baseEnv() []string {
	var unset []string
	if !readJSON(unsetFile, &unset) || len(unset) == 0 {
		return os.Environ()
	}
	return withoutNames(os.Environ(), unset)
}
