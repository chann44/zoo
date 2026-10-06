package main

import (
	"image"
	"testing"
)

func TestChanges(t *testing.T) {
	a := image.NewRGBA(image.Rect(0, 0, 100, 50))
	b := image.NewRGBA(a.Bounds())
	if f, box := changes(a, b); f != 0 || !box.Empty() {
		t.Fatalf("identical frames: %v %v", f, box)
	}
	b.Pix[b.PixOffset(40, 20)] = 1
	f, box := changes(a, b)
	if box != image.Rect(32, 16, 48, 32) || f <= 0 || f >= 1 {
		t.Fatalf("one pixel: %v %v", f, box)
	}
	b.Pix[b.PixOffset(99, 49)] = 1
	if _, box := changes(a, b); box != image.Rect(32, 16, 100, 50) {
		t.Fatalf("edge tile: %v", box)
	}
	if f, box := changes(nil, b); f != 1 || box != b.Bounds() {
		t.Fatalf("first frame: %v %v", f, box)
	}
}
