package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
)

// A target is something on the host the API can open a byte stream to.
type target struct {
	network, address string
}

func (t target) present() bool {
	if t.network == "unix" {
		_, err := os.Stat(t.address)
		return err == nil
	}
	return true
}

func (t target) dial(ctx context.Context) (net.Conn, error) {
	var d net.Dialer
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	return d.DialContext(ctx, t.network, t.address)
}

func (t target) check(ctx context.Context) error {
	conn, err := t.dial(ctx)
	if err != nil {
		return err
	}
	return conn.Close()
}

// hostTargets: the Docker socket wherever there is one, and the SSH server on macOS and Windows hosts, whose
// backends (server/macos.py, windows.py) work over SSH.
func hostTargets() map[string]target {
	targets := map[string]target{}
	if sock := dockerSocket(); sock != "" {
		targets["docker"] = target{"unix", sock}
	}
	if runtime.GOOS != "linux" {
		targets["ssh"] = target{"tcp", "127.0.0.1:22"}
	}
	return targets
}

func dockerSocket() string {
	if host := os.Getenv("DOCKER_HOST"); strings.HasPrefix(host, "unix://") {
		return strings.TrimPrefix(host, "unix://")
	}
	if runtime.GOOS == "windows" {
		return ""
	}
	candidates := []string{"/var/run/docker.sock"}
	if runtime.GOOS == "darwin" {
		home, _ := os.UserHomeDir()
		candidates = []string{filepath.Join(home, ".docker", "run", "docker.sock"), "/var/run/docker.sock"}
	}
	for _, path := range candidates {
		if _, err := os.Stat(path); err == nil {
			return path
		}
	}
	return ""
}

// A Driver is one of the host's sandbox runtimes. Sandboxes are created and changed by the API's backends over
// the node's tunnels; drivers tell the API which runtimes the host has and which sandboxes each is running.
type Driver interface {
	Name() string
	// Probe says whether the runtime is usable here, with its version, or why not.
	Probe(ctx context.Context) (bool, string)
	// Sandboxes are the ids of the sandboxes it is running.
	Sandboxes(ctx context.Context) ([]string, error)
}

func hostDrivers() []Driver {
	var drivers []Driver
	if sock := dockerSocket(); sock != "" {
		client := newDockerClient(sock)
		drivers = append(drivers, &dockerDriver{name: "kata", runtime: "kata", client: client},
			&dockerDriver{name: "runc", runtime: "runc", client: client})
	}
	switch runtime.GOOS {
	case "darwin":
		drivers = append(drivers, &zoovmDriver{})
	case "windows":
		drivers = append(drivers, &hypervDriver{})
	}
	return drivers
}

// Docker: Kata Containers (the containerd shim io.containerd.kata.v2, registered with Docker as "kata") and runc.

type dockerClient struct {
	http *http.Client
}

func newDockerClient(sock string) *dockerClient {
	return &dockerClient{http: &http.Client{
		Timeout: 15 * time.Second,
		Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", sock)
		}},
	}}
}

func (c *dockerClient) get(ctx context.Context, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://docker"+path, nil)
	if err != nil {
		return err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("docker %s: %s %s", path, resp.Status, strings.TrimSpace(string(body)))
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

type dockerInfo struct {
	ServerVersion   string
	OperatingSystem string
	Runtimes        map[string]json.RawMessage
}

type dockerDriver struct {
	name, runtime string
	client        *dockerClient
}

func (d *dockerDriver) Name() string { return d.name }

func (d *dockerDriver) Probe(ctx context.Context) (bool, string) {
	var info dockerInfo
	if err := d.client.get(ctx, "/info", &info); err != nil {
		return false, err.Error()
	}
	if _, ok := info.Runtimes[d.runtime]; !ok {
		return false, fmt.Sprintf("Docker %s has no %s runtime", info.ServerVersion, d.runtime)
	}
	return true, "Docker " + info.ServerVersion
}

func (d *dockerDriver) Sandboxes(ctx context.Context) ([]string, error) {
	filters, _ := json.Marshal(map[string][]string{"label": {"zoo.sandbox"}, "status": {"running"}})
	var list []struct {
		ID     string `json:"Id"`
		Labels map[string]string
	}
	if err := d.client.get(ctx, "/containers/json?filters="+url.QueryEscape(string(filters)), &list); err != nil {
		return nil, err
	}
	var ids []string
	for _, c := range list {
		var inspect struct {
			HostConfig struct{ Runtime string }
		}
		if err := d.client.get(ctx, "/containers/"+c.ID+"/json", &inspect); err != nil {
			continue // gone since the list
		}
		if inspect.HostConfig.Runtime == d.runtime && c.Labels["zoo.sandbox"] != "" {
			ids = append(ids, c.Labels["zoo.sandbox"])
		}
	}
	return ids, nil
}

// Sandbox VMs are named zoo-<sandbox id>; base VMs and templates are not sandboxes.
var vmName = regexp.MustCompile(`^zoo-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$`)

func sandboxIDs(names []string) []string {
	var ids []string
	for _, name := range names {
		if m := vmName.FindStringSubmatch(strings.TrimSpace(name)); m != nil {
			ids = append(ids, m[1])
		}
	}
	return ids
}

func output(ctx context.Context, name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).Output()
	var exit *exec.ExitError
	if errors.As(err, &exit) && len(exit.Stderr) > 0 {
		return out, fmt.Errorf("%s: %s", name, strings.TrimSpace(string(exit.Stderr)))
	}
	return out, err
}

// zoovm: macOS VMs on Apple's Virtualization framework (macos/zoovm).
type zoovmDriver struct{}

func (zoovmDriver) Name() string { return "zoovm" }

func zoovmPath() string {
	if path, err := exec.LookPath("zoovm"); err == nil {
		return path
	}
	return "/usr/local/bin/zoovm"
}

func (z zoovmDriver) list(ctx context.Context) ([]struct{ Name, State string }, error) {
	out, err := output(ctx, zoovmPath(), "list")
	if err != nil {
		return nil, err
	}
	var rows []struct{ Name, State string }
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, fmt.Errorf("zoovm list: %w", err)
	}
	return rows, nil
}

func (z zoovmDriver) Probe(ctx context.Context) (bool, string) {
	if _, err := z.list(ctx); err != nil {
		return false, err.Error()
	}
	return true, "zoovm"
}

func (z zoovmDriver) Sandboxes(ctx context.Context) ([]string, error) {
	rows, err := z.list(ctx)
	if err != nil {
		return nil, err
	}
	var names []string
	for _, r := range rows {
		if r.State == "running" {
			names = append(names, r.Name)
		}
	}
	return sandboxIDs(names), nil
}

// hyperv: Windows VMs on Hyper-V, marked with the notes zoovm.ps1 gives them.
type hypervDriver struct{}

func (hypervDriver) Name() string { return "hyperv" }

func powershell(ctx context.Context, script string) ([]byte, error) {
	return output(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script)
}

func (hypervDriver) Probe(ctx context.Context) (bool, string) {
	out, err := powershell(ctx, "(Get-Module -ListAvailable Hyper-V | Select-Object -First 1).Version.ToString()")
	if err != nil || len(strings.TrimSpace(string(out))) == 0 {
		return false, "Hyper-V's PowerShell module isn't installed"
	}
	return true, "Hyper-V " + strings.TrimSpace(string(out))
}

func (hypervDriver) Sandboxes(ctx context.Context) ([]string, error) {
	out, err := powershell(ctx, "Get-VM | Where-Object { $_.Notes -eq 'zoo' -and $_.State -eq 'Running' } | ForEach-Object Name")
	if err != nil {
		return nil, err
	}
	return sandboxIDs(strings.Split(string(out), "\n")), nil
}

// Host capacity, read by stats_<os>.go.
type stats struct {
	memoryTotal, memoryAvailable uint64
	diskTotal, diskFree          uint64
	load                         float64
}

// diskPath is where sandboxes' disks live: Docker's data on Linux, the user's home (zoovm) on a Mac.
func diskPath() string {
	switch runtime.GOOS {
	case "linux":
		if _, err := os.Stat("/var/lib/docker"); err == nil {
			return "/var/lib/docker"
		}
		return "/"
	case "windows":
		return os.Getenv("SystemDrive") + `\`
	}
	home, _ := os.UserHomeDir()
	return home
}
