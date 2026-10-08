package main

import (
	"bufio"
	"strings"
	"testing"
)

func TestParseMeminfo(t *testing.T) {
	total, available := parseMeminfo(bufio.NewScanner(strings.NewReader(
		"MemTotal:       16318492 kB\nMemFree:         1048576 kB\nMemAvailable:    8159246 kB\nbogus\n")))
	if total != 16318492*1024 || available != 8159246*1024 {
		t.Fatal(total, available)
	}
}
