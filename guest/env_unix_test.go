//go:build !windows

package main

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestSecretChangesReachNewCommands(t *testing.T) {
	dir := t.TempDir()
	secretsFile, unsetFile = filepath.Join(dir, "env.json"), filepath.Join(dir, "unset.json")
	t.Setenv("BOOTED_TOKEN", "from-boot")
	t.Setenv("KEPT", "yes")

	if env := secretEnv(); env != nil {
		t.Fatalf("no secrets file should mean no secrets, got %v", env)
	}
	if !slices.Contains(baseEnv(), "BOOTED_TOKEN=from-boot") {
		t.Fatal("without an unset list the environment stays whole")
	}

	os.WriteFile(secretsFile, []byte(`{"NEW_TOKEN":"fresh"}`), 0o600)
	os.WriteFile(unsetFile, []byte(`["BOOTED_TOKEN"]`), 0o600)
	if got := secretEnv(); !slices.Equal(got, []string{"NEW_TOKEN=fresh"}) {
		t.Fatalf("secretEnv = %v", got)
	}
	env := baseEnv()
	if slices.Contains(env, "BOOTED_TOKEN=from-boot") || !slices.Contains(env, "KEPT=yes") {
		t.Fatalf("baseEnv should drop only the removed secret, got %v", env)
	}

	// a half-written file is no secrets rather than garbage
	os.WriteFile(secretsFile, []byte(`{"NEW_TO`), 0o600)
	if env := secretEnv(); env != nil {
		t.Fatalf("a torn file should read as none, got %v", env)
	}
}

func TestWithoutNames(t *testing.T) {
	got := withoutNames([]string{"A=1", "AB=2", "B=x=y", "C"}, []string{"A", "B"})
	if !slices.Equal(got, []string{"AB=2", "C"}) {
		t.Fatalf("withoutNames = %v", got)
	}
}
