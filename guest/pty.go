package main

import (
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"sync"
	"syscall"

	"github.com/creack/pty"
)

type terminal struct {
	f     *os.File
	cmd   *exec.Cmd
	input chan []byte
	done  chan struct{}
}

var (
	terminals   = map[string]*terminal{}
	terminalsMu sync.Mutex
)

type ptyArgs struct {
	Stream string            `json:"stream"`
	Argv   []string          `json:"argv"`
	Env    map[string]string `json:"env"`
	Cwd    string            `json:"cwd"`
	Cols   uint16            `json:"cols"`
	Rows   uint16            `json:"rows"`
	Signal int               `json:"signal"`
}

func loginShell() []string {
	for _, shell := range []string{os.Getenv("SHELL"), "/bin/bash", "/bin/sh"} {
		if shell != "" {
			if _, err := os.Stat(shell); err == nil {
				return []string{shell, "-l"}
			}
		}
	}
	return []string{"/bin/sh", "-l"}
}

// ptyOpen starts a command on a new pseudo-terminal. The API names the stream, so output that arrives before the
// reply already has somewhere to go. Output streams as pty_data frames and ends with one pty_exit frame.
func ptyOpen(c call) (any, []byte, error) {
	a := ptyArgs{Cols: 80, Rows: 24}
	if err := json.Unmarshal(c.args, &a); err != nil {
		return nil, nil, err
	}
	if a.Stream == "" {
		return nil, nil, errors.New("stream is required")
	}
	if len(a.Argv) == 0 {
		a.Argv = loginShell()
	}
	cmd := exec.Command(a.Argv[0], a.Argv[1:]...)
	cmd.Dir = a.Cwd
	cmd.Env = append(os.Environ(), "TERM=xterm-256color")
	for k, v := range a.Env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	f, err := pty.StartWithSize(cmd, &pty.Winsize{Cols: a.Cols, Rows: a.Rows})
	if err != nil {
		return nil, nil, err
	}
	t := &terminal{f: f, cmd: cmd, input: make(chan []byte, 256), done: make(chan struct{})}
	terminalsMu.Lock()
	if _, taken := terminals[a.Stream]; taken {
		terminalsMu.Unlock()
		f.Close()
		cmd.Process.Kill()
		cmd.Wait()
		return nil, nil, errors.New("stream already open")
	}
	terminals[a.Stream] = t
	terminalsMu.Unlock()

	go func() {
		for {
			select {
			case data := <-t.input:
				if _, err := f.Write(data); err != nil {
					return
				}
			case <-t.done:
				return
			}
		}
	}()
	go func() {
		buf := make([]byte, 32<<10)
		for {
			n, err := f.Read(buf)
			if n > 0 {
				c.send(map[string]any{"op": "pty_data", "stream": a.Stream}, append([]byte(nil), buf[:n]...))
			}
			if err != nil {
				break
			}
		}
		code := 0
		if err := cmd.Wait(); err != nil {
			var exit *exec.ExitError
			if errors.As(err, &exit) {
				code = exitCode(exit)
			} else {
				code = -1
			}
		}
		terminalsMu.Lock()
		delete(terminals, a.Stream)
		terminalsMu.Unlock()
		close(t.done)
		f.Close()
		c.send(map[string]any{"op": "pty_exit", "stream": a.Stream, "exit_code": code}, nil)
	}()
	return map[string]any{"stream": a.Stream, "pid": cmd.Process.Pid}, nil, nil
}

func openTerminal(raw json.RawMessage) (*terminal, ptyArgs, error) {
	var a ptyArgs
	if err := json.Unmarshal(raw, &a); err != nil {
		return nil, a, err
	}
	terminalsMu.Lock()
	defer terminalsMu.Unlock()
	t, ok := terminals[a.Stream]
	if !ok {
		return nil, a, errors.New("no such terminal " + a.Stream)
	}
	return t, a, nil
}

func ptyInput(c call) (any, []byte, error) {
	t, _, err := openTerminal(c.args)
	if err != nil {
		return nil, nil, err
	}
	select {
	case t.input <- c.payload:
	case <-t.done:
	}
	return nil, nil, nil
}

func ptyResize(c call) (any, []byte, error) {
	t, a, err := openTerminal(c.args)
	if err != nil {
		return nil, nil, err
	}
	return nil, nil, pty.Setsize(t.f, &pty.Winsize{Cols: a.Cols, Rows: a.Rows})
}

// ptyKill signals the terminal's process group (SIGHUP unless told otherwise), as closing a terminal window does.
func ptyKill(c call) (any, []byte, error) {
	t, a, err := openTerminal(c.args)
	if err != nil {
		return nil, nil, err
	}
	sig := syscall.SIGHUP
	if a.Signal > 0 {
		sig = syscall.Signal(a.Signal)
	}
	return nil, nil, syscall.Kill(-t.cmd.Process.Pid, sig)
}

// closeTerminals hangs up every terminal when the API connection drops; nobody can reach them any more.
func closeTerminals() {
	terminalsMu.Lock()
	defer terminalsMu.Unlock()
	for _, t := range terminals {
		syscall.Kill(-t.cmd.Process.Pid, syscall.SIGHUP)
	}
}
