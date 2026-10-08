package main

import (
	"bufio"
	"os"
	"runtime"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

func hostStats() stats {
	var s stats
	if f, err := os.Open("/proc/meminfo"); err == nil {
		s.memoryTotal, s.memoryAvailable = parseMeminfo(bufio.NewScanner(f))
		f.Close()
	}
	if data, err := os.ReadFile("/proc/loadavg"); err == nil {
		if fields := strings.Fields(string(data)); len(fields) > 0 {
			if load, err := strconv.ParseFloat(fields[0], 64); err == nil {
				s.load = load / float64(runtime.NumCPU())
			}
		}
	}
	var fs unix.Statfs_t
	if unix.Statfs(diskPath(), &fs) == nil {
		s.diskTotal = fs.Blocks * uint64(fs.Bsize)
		s.diskFree = fs.Bavail * uint64(fs.Bsize)
	}
	return s
}

// parseMeminfo returns MemTotal and MemAvailable in bytes.
func parseMeminfo(scanner *bufio.Scanner) (total, available uint64) {
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 {
			continue
		}
		kb, err := strconv.ParseUint(fields[1], 10, 64)
		if err != nil {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			total = kb * 1024
		case "MemAvailable:":
			available = kb * 1024
		}
	}
	return total, available
}
