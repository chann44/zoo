package main

import (
	"bytes"
	"image"
	"image/draw"
	"image/png"
	"os"
	"testing"

	"github.com/klauspost/compress/zlib"
)

func screenshotFixture(tb testing.TB) *image.RGBA {
	path := os.Getenv("ZOO_SCREENSHOT")
	if path == "" {
		img := image.NewRGBA(image.Rect(0, 0, 37, 23))
		for i := range img.Pix {
			img.Pix[i] = byte(i * 7)
		}
		for i := 3; i < len(img.Pix); i += 4 {
			img.Pix[i] = 0xff
		}
		return img
	}
	f, err := os.Open(path)
	if err != nil {
		tb.Fatal(err)
	}
	defer f.Close()
	decoded, err := png.Decode(f)
	if err != nil {
		tb.Fatal(err)
	}
	img := image.NewRGBA(decoded.Bounds())
	draw.Draw(img, img.Bounds(), decoded, decoded.Bounds().Min, draw.Src)
	return img
}

func TestEncodePNGRoundTrips(t *testing.T) {
	img := screenshotFixture(t)
	data, err := encodePNG(img, zlib.BestSpeed)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := png.Decode(bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	b := img.Bounds()
	for y := b.Min.Y; y < b.Max.Y; y++ {
		for x := b.Min.X; x < b.Max.X; x++ {
			r1, g1, b1, _ := img.At(x, y).RGBA()
			r2, g2, b2, _ := decoded.At(x, y).RGBA()
			if r1 != r2 || g1 != g2 || b1 != b2 {
				t.Fatalf("pixel %d,%d differs", x, y)
			}
		}
	}
}

func BenchmarkStdPNG(b *testing.B) {
	img := screenshotFixture(b)
	for b.Loop() {
		var out bytes.Buffer
		(&png.Encoder{CompressionLevel: png.BestSpeed}).Encode(&out, img)
		b.ReportMetric(float64(out.Len()), "bytes")
	}
}

func BenchmarkFastPNG(b *testing.B) {
	img := screenshotFixture(b)
	for _, level := range []int{zlib.BestSpeed, 2, 3} {
		b.Run(string(rune('0'+level)), func(b *testing.B) {
			for b.Loop() {
				data, _ := encodePNG(img, level)
				b.ReportMetric(float64(len(data)), "bytes")
			}
		})
	}
}
