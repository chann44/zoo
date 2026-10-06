package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"image"
	"image/jpeg"
	"io"
	"log"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"github.com/klauspost/compress/zlib"
	"golang.org/x/image/draw"
)

type screenArgs struct {
	Display string  `json:"display"`
	Format  string  `json:"format"`
	Scale   float64 `json:"scale"`
	Quality int     `json:"quality"`
}

func init() {
	// xgb logs every missing .Xauthority; connection errors are returned anyway
	xgb.Logger = log.New(io.Discard, "", 0)
}

// screenshotOp grabs the root window straight from the X server, with no process fork and no ImageMagick.
func screenshotOp(c call) (any, []byte, error) {
	a := screenArgs{Display: ":1", Format: "png", Scale: 1, Quality: 80}
	if err := json.Unmarshal(c.args, &a); err != nil {
		return nil, nil, err
	}
	if err := checkArgs(a); err != nil {
		return nil, nil, err
	}
	img, err := capture(a.Display)
	if err != nil {
		return nil, nil, err
	}
	out, w, h, err := encodeImage(img, a)
	if err != nil {
		return nil, nil, err
	}
	return map[string]any{"width": w, "height": h, "format": a.Format}, out, nil
}

// checkArgs validates the encoding options every screen op shares.
func checkArgs(a screenArgs) error {
	if a.Format != "png" && a.Format != "jpeg" {
		return errors.New("format must be png or jpeg")
	}
	if a.Scale <= 0 || a.Scale > 1 {
		return errors.New("scale must be in (0, 1]")
	}
	return nil
}

// encodeImage scales img by a.Scale and encodes it as a.Format, returning the encoded size.
func encodeImage(img *image.RGBA, a screenArgs) ([]byte, int, int, error) {
	if a.Scale < 1 {
		b := img.Bounds()
		w, h := max(1, int(float64(b.Dx())*a.Scale+0.5)), max(1, int(float64(b.Dy())*a.Scale+0.5))
		scaled := image.NewRGBA(image.Rect(0, 0, w, h))
		draw.ApproxBiLinear.Scale(scaled, scaled.Bounds(), img, b, draw.Src, nil)
		img = scaled
	}
	var out []byte
	var err error
	switch a.Format {
	case "jpeg":
		var buf bytes.Buffer
		err = jpeg.Encode(&buf, img, &jpeg.Options{Quality: min(max(a.Quality, 1), 100)})
		out = buf.Bytes()
	default:
		out, err = encodePNG(img, zlib.BestSpeed)
	}
	b := img.Bounds()
	return out, b.Dx(), b.Dy(), err
}

// capture opens a connection per screenshot, which survives X server restarts and costs well under a millisecond
// over the local socket.
func capture(name string) (*image.RGBA, error) {
	c, err := xgb.NewConnDisplay(name)
	if err != nil {
		return nil, err
	}
	defer c.Close()
	return grab(c)
}

func grab(c *xgb.Conn) (*image.RGBA, error) {
	screen := xproto.Setup(c).DefaultScreen(c)
	w, h := int(screen.WidthInPixels), int(screen.HeightInPixels)
	reply, err := xproto.GetImage(
		c, xproto.ImageFormatZPixmap, xproto.Drawable(screen.Root), 0, 0, uint16(w), uint16(h), 0xffffffff,
	).Reply()
	if err != nil {
		return nil, err
	}
	if len(reply.Data) < w*h*4 {
		return nil, errors.New("unsupported pixel format: expected 32 bits per pixel")
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	// 24-bit depth on a little-endian server arrives as B, G, R, X
	src, dst := reply.Data, img.Pix
	for i := 0; i < w*h*4; i += 4 {
		dst[i], dst[i+1], dst[i+2], dst[i+3] = src[i+2], src[i+1], src[i], 0xff
	}
	return img, nil
}
