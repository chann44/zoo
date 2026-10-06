package main

import (
	"encoding/json"
	"errors"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"github.com/jezek/xgb/xtest"
)

// xtestConn connects to a display with the XTest extension ready. A connection per call survives X server
// restarts and costs well under a millisecond over the local socket.
func xtestConn(display string) (*xgb.Conn, xproto.Window, error) {
	x, err := xgb.NewConnDisplay(display)
	if err != nil {
		return nil, 0, err
	}
	if err := xtest.Init(x); err != nil {
		x.Close()
		return nil, 0, err
	}
	return x, xproto.Setup(x).DefaultScreen(x).Root, nil
}

// A step is one pointer action; the API composes clicks, scrolls and drags from them.
type step struct {
	Move    *[2]int16 `json:"move"`
	Press   byte      `json:"press"`
	Release byte      `json:"release"`
	SleepMs int       `json:"sleep"`
}

type mouseArgs struct {
	Display string `json:"display"`
	Steps   []step `json:"steps"`
}

// mouseOp injects pointer events with XTest. Each event is checked, so the server has applied it before the
// reply, and any button still down when a step fails is released.
func mouseOp(c call) (any, []byte, error) {
	a := mouseArgs{Display: ":1"}
	if err := json.Unmarshal(c.args, &a); err != nil {
		return nil, nil, err
	}
	x, root, err := xtestConn(a.Display)
	if err != nil {
		return nil, nil, err
	}
	defer x.Close()
	held := map[byte]bool{}
	defer func() {
		for button := range held {
			xtest.FakeInputChecked(x, xproto.ButtonRelease, button, 0, root, 0, 0, 0).Check()
		}
	}()
	for _, s := range a.Steps {
		switch {
		case s.Move != nil:
			err = xtest.FakeInputChecked(x, xproto.MotionNotify, 0, 0, root, s.Move[0], s.Move[1], 0).Check()
		case s.Press != 0:
			err = xtest.FakeInputChecked(x, xproto.ButtonPress, s.Press, 0, root, 0, 0, 0).Check()
			held[s.Press] = true
		case s.Release != 0:
			err = xtest.FakeInputChecked(x, xproto.ButtonRelease, s.Release, 0, root, 0, 0, 0).Check()
			delete(held, s.Release)
		case s.SleepMs > 0:
			time.Sleep(time.Duration(s.SleepMs) * time.Millisecond)
		default:
			err = errors.New("empty step")
		}
		if err != nil {
			return nil, nil, err
		}
	}
	pointer, err := xproto.QueryPointer(x, root).Reply()
	if err != nil {
		return nil, nil, err
	}
	return map[string]any{"x": pointer.RootX, "y": pointer.RootY}, nil, nil
}
