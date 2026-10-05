// zoo-guest runs inside a sandbox and serves the API's tool calls over one websocket it dials itself, so tool
// calls skip docker exec and screenshots skip a process fork.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"os/user"
	"runtime"
	"strconv"
	"syscall"
	"time"

	"github.com/coder/websocket"
)

const version = 1

var services = []string{"exec", "pty", "files", "screen", "input", "metrics"}

// A call is one request: its args, its payload, and the session's send and context for ops that stream.
type call struct {
	args    json.RawMessage
	payload []byte
	send    func(any, []byte) error
	ctx     context.Context
}

type handler func(c call) (any, []byte, error)

var handlers = map[string]handler{
	"exec":       execOp,
	"read":       readOp,
	"write":      writeOp,
	"screenshot": screenshotOp,
	"mouse":      mouseOp,
	"keyboard":   keyboardOp,
	"pty_open":   ptyOpen,
}

// notifications carry no id and get no reply. They run in arrival order on the read loop, so a terminal's input
// is never reordered; each one only hands work to a terminal's own goroutine.
var notifications = map[string]handler{
	"pty_input":  ptyInput,
	"pty_resize": ptyResize,
	"pty_kill":   ptyKill,
}

func main() {
	as := flag.String("user", "", "when started as root, run as this user")
	flag.Parse()
	url, token, sandbox := os.Getenv("ZOO_GUEST_URL"), os.Getenv("ZOO_GUEST_TOKEN"), os.Getenv("ZOO_SANDBOX_ID")
	// commands the guest runs inherit its environment, which must not carry the token
	for _, name := range []string{"ZOO_GUEST_URL", "ZOO_GUEST_TOKEN", "ZOO_SANDBOX_ID"} {
		os.Unsetenv(name)
	}
	if url == "" || token == "" || sandbox == "" {
		log.Print("ZOO_GUEST_URL, ZOO_GUEST_TOKEN or ZOO_SANDBOX_ID is not set; the API uses its fallback path")
		return
	}
	if *as != "" && os.Getuid() == 0 {
		if err := dropTo(*as); err != nil {
			log.Fatalf("switching to %s: %v", *as, err)
		}
	}
	if home, err := os.UserHomeDir(); err == nil {
		os.Chdir(home)
	}
	backoff := 500 * time.Millisecond
	for {
		began := time.Now()
		err := session(context.Background(), url, token, sandbox)
		if time.Since(began) > 30*time.Second {
			backoff = 500 * time.Millisecond
		}
		log.Printf("disconnected: %v; retrying in %s", err, backoff)
		time.Sleep(backoff)
		backoff = min(backoff*2, 10*time.Second)
	}
}

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

// session serves one connection until it drops.
func session(ctx context.Context, url, token, sandbox string) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, url, &websocket.DialOptions{
		HTTPHeader: http.Header{"Authorization": {"Bearer " + token}, "X-Zoo-Sandbox": {sandbox}},
	})
	if err != nil {
		return err
	}
	defer conn.CloseNow()
	conn.SetReadLimit(256 << 20)
	send := func(header any, payload []byte) error {
		frame, err := pack(header, payload)
		if err != nil {
			return err
		}
		wctx, done := context.WithTimeout(ctx, 30*time.Second)
		defer done()
		return conn.Write(wctx, websocket.MessageBinary, frame)
	}
	hello := map[string]any{"op": "hello", "version": version, "os": runtime.GOOS, "services": services}
	if err := send(hello, nil); err != nil {
		return err
	}
	go reportMetrics(ctx, send)
	defer closeTerminals()
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return err
		}
		raw, payload, err := unpack(data)
		var req request
		if err == nil {
			err = json.Unmarshal(raw, &req)
		}
		if err != nil {
			log.Printf("bad frame: %v", err)
			continue
		}
		c := call{args: req.Args, payload: payload, send: send, ctx: ctx}
		if req.ID == 0 {
			if _, _, err := dispatch(notifications, req.Op, c); err != nil {
				log.Printf("%s: %v", req.Op, err)
			}
			continue
		}
		go serve(req, c)
	}
}

type request struct {
	ID   uint64          `json:"id"`
	Op   string          `json:"op"`
	Args json.RawMessage `json:"args"`
}

func serve(req request, c call) {
	result, out, err := dispatch(handlers, req.Op, c)
	if err != nil {
		c.send(map[string]any{"id": req.ID, "ok": false, "error": err.Error()}, nil)
		return
	}
	if err := c.send(map[string]any{"id": req.ID, "ok": true, "result": result}, out); err != nil {
		log.Printf("reply %d: %v", req.ID, err)
	}
}

func dispatch(ops map[string]handler, op string, c call) (result any, out []byte, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = errors.New("guest panic: " + strconv.Quote(toString(r)))
		}
	}()
	h, ok := ops[op]
	if !ok {
		return nil, nil, errors.New("unknown op " + op)
	}
	if len(c.args) == 0 {
		c.args = json.RawMessage("{}")
	}
	return h(c)
}

func toString(v any) string {
	if err, ok := v.(error); ok {
		return err.Error()
	}
	if s, ok := v.(string); ok {
		return s
	}
	return "unknown"
}
