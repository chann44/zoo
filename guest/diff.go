package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"image"
	"sync"
	"time"

	"github.com/jezek/xgb"
	"golang.org/x/image/draw"
)

// tile is the side of the squares frames are compared in; a changed region is reported in whole tiles.
const tile = 16

// lastFrames holds each diff session's previous frame, so screen_diff only sends what changed since that caller
// last looked.
var (
	lastFrames   = map[string]*image.RGBA{}
	lastFramesMu sync.Mutex
)

const maxSessions = 16

// changes compares two frames tile by tile and returns the fraction of tiles that differ and their bounding box.
// Frames of different sizes differ everywhere.
func changes(prev, cur *image.RGBA) (float64, image.Rectangle) {
	b := cur.Bounds()
	if prev == nil || prev.Bounds() != b {
		return 1, b
	}
	var box image.Rectangle
	changed, total := 0, 0
	for ty := b.Min.Y; ty < b.Max.Y; ty += tile {
		for tx := b.Min.X; tx < b.Max.X; tx += tile {
			r := image.Rect(tx, ty, min(tx+tile, b.Max.X), min(ty+tile, b.Max.Y))
			total++
			if !sameTile(prev, cur, r) {
				changed++
				box = box.Union(r)
			}
		}
	}
	return float64(changed) / float64(max(total, 1)), box
}

func sameTile(a, b *image.RGBA, r image.Rectangle) bool {
	for y := r.Min.Y; y < r.Max.Y; y++ {
		i, j := a.PixOffset(r.Min.X, y), a.PixOffset(r.Max.X, y)
		if !bytes.Equal(a.Pix[i:j], b.Pix[i:j]) {
			return false
		}
	}
	return true
}

type diffArgs struct {
	screenArgs
	Session string `json:"session"`
}

// diffOp returns the region that changed since the session's last frame, as a box in screen pixels and an image
// of just that box. The first call of a session returns the whole screen; an unchanged screen returns no image.
func diffOp(c call) (any, []byte, error) {
	a := diffArgs{screenArgs: screenArgs{Display: ":1", Format: "png", Scale: 1, Quality: 80}, Session: "default"}
	if err := json.Unmarshal(c.args, &a); err != nil {
		return nil, nil, err
	}
	if err := checkArgs(a.screenArgs); err != nil {
		return nil, nil, err
	}
	img, err := capture(a.Display)
	if err != nil {
		return nil, nil, err
	}
	key := a.Display + "\x00" + a.Session
	lastFramesMu.Lock()
	prev := lastFrames[key]
	if prev == nil && len(lastFrames) >= maxSessions {
		for k := range lastFrames {
			delete(lastFrames, k)
			break
		}
	}
	lastFrames[key] = img
	lastFramesMu.Unlock()

	b := img.Bounds()
	fraction, box := changes(prev, img)
	result := map[string]any{"width": b.Dx(), "height": b.Dy(), "changed": fraction, "format": a.Format, "box": nil}
	if box.Empty() {
		return result, nil, nil
	}
	crop := image.NewRGBA(image.Rect(0, 0, box.Dx(), box.Dy()))
	draw.Copy(crop, image.Point{}, img, box, draw.Src, nil)
	out, _, _, err := encodeImage(crop, a.screenArgs)
	if err != nil {
		return nil, nil, err
	}
	result["box"] = map[string]int{"x": box.Min.X, "y": box.Min.Y, "width": box.Dx(), "height": box.Dy()}
	return result, out, nil
}

type stableArgs struct {
	Display   string  `json:"display"`
	TimeoutMS int     `json:"timeout_ms"`
	QuietMS   int     `json:"quiet_ms"`
	Threshold float64 `json:"threshold"`
}

const pollEvery = 100 * time.Millisecond

// stableOp polls the screen at about 10 fps until no more than `threshold` of it has changed for `quiet_ms`, or
// `timeout_ms` passes. The polling stays in the guest, so waiting costs no network round-trips.
func stableOp(c call) (any, []byte, error) {
	a := stableArgs{Display: ":1", TimeoutMS: 5000, QuietMS: 500}
	if err := json.Unmarshal(c.args, &a); err != nil {
		return nil, nil, err
	}
	if a.TimeoutMS <= 0 || a.TimeoutMS > 60000 {
		return nil, nil, errors.New("timeout_ms must be in (0, 60000]")
	}
	if a.QuietMS <= 0 || a.Threshold < 0 || a.Threshold >= 1 {
		return nil, nil, errors.New("quiet_ms must be positive and threshold in [0, 1)")
	}
	conn, err := xgb.NewConnDisplay(a.Display)
	if err != nil {
		return nil, nil, err
	}
	defer conn.Close()
	start := time.Now()
	deadline, quiet := start.Add(time.Duration(a.TimeoutMS)*time.Millisecond), time.Duration(a.QuietMS)*time.Millisecond
	prev, err := grab(conn)
	if err != nil {
		return nil, nil, err
	}
	lastChange := start
	ticker := time.NewTicker(pollEvery)
	defer ticker.Stop()
	for {
		if time.Since(lastChange) >= quiet {
			return map[string]any{"stable": true, "waited_ms": time.Since(start).Milliseconds()}, nil, nil
		}
		if time.Now().After(deadline) {
			return map[string]any{"stable": false, "waited_ms": time.Since(start).Milliseconds()}, nil, nil
		}
		select {
		case <-c.ctx.Done():
			return nil, nil, c.ctx.Err()
		case <-ticker.C:
		}
		cur, err := grab(conn)
		if err != nil {
			return nil, nil, err
		}
		if fraction, _ := changes(prev, cur); fraction > a.Threshold {
			lastChange = time.Now()
		}
		prev = cur
	}
}
