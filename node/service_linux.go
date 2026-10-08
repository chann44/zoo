package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

const (
	unitPath    = "/etc/systemd/system/zoo-node.service"
	installPath = "/usr/local/bin/zoo-node"
)

func unit(bin, home string) string {
	return fmt.Sprintf(`[Unit]
Description=Zoo node: links this host to the Zoo control plane
After=network-online.target docker.service
Wants=network-online.target

[Service]
ExecStart=%s run --dir %s
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
`, bin, home)
}

func installService(home string) error {
	if os.Geteuid() != 0 {
		return errors.New("installing the service needs root; run it with sudo")
	}
	if err := installBinary(installPath); err != nil {
		return err
	}
	if err := os.WriteFile(unitPath, []byte(unit(installPath, home)), 0o644); err != nil {
		return err
	}
	for _, args := range [][]string{{"daemon-reload"}, {"enable", "zoo-node"}, {"restart", "zoo-node"}} {
		if out, err := exec.Command("systemctl", args...).CombinedOutput(); err != nil {
			return fmt.Errorf("systemctl %s: %s", strings.Join(args, " "), strings.TrimSpace(string(out)))
		}
	}
	return nil
}

func runAsService(string) bool { return false }
