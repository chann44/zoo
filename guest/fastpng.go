package main

import (
	"bytes"
	"encoding/binary"
	"hash/crc32"
	"image"

	"github.com/klauspost/compress/zlib"
)

// encodePNG writes an opaque RGB PNG. It is several times faster than image/png at BestSpeed: rows use the Sub
// filter, which suits screenshots' flat runs of colour, and klauspost's deflate is much faster than the stdlib's.
func encodePNG(img *image.RGBA, level int) ([]byte, error) {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	var out bytes.Buffer
	out.WriteString("\x89PNG\r\n\x1a\n")
	ihdr := make([]byte, 13)
	binary.BigEndian.PutUint32(ihdr[0:], uint32(w))
	binary.BigEndian.PutUint32(ihdr[4:], uint32(h))
	ihdr[8], ihdr[9] = 8, 2 // 8-bit RGB
	chunk(&out, "IHDR", ihdr)

	var idat bytes.Buffer
	z, err := zlib.NewWriterLevel(&idat, level)
	if err != nil {
		return nil, err
	}
	row := make([]byte, 1+w*3)
	row[0] = 1 // Sub
	for y := range h {
		src := img.Pix[y*img.Stride:]
		var pr, pg, pb byte
		for x := range w {
			r, g, bl := src[x*4], src[x*4+1], src[x*4+2]
			row[1+x*3], row[2+x*3], row[3+x*3] = r-pr, g-pg, bl-pb
			pr, pg, pb = r, g, bl
		}
		if _, err := z.Write(row); err != nil {
			return nil, err
		}
	}
	if err := z.Close(); err != nil {
		return nil, err
	}
	chunk(&out, "IDAT", idat.Bytes())
	chunk(&out, "IEND", nil)
	return out.Bytes(), nil
}

func chunk(out *bytes.Buffer, kind string, data []byte) {
	var n [4]byte
	binary.BigEndian.PutUint32(n[:], uint32(len(data)))
	out.Write(n[:])
	crc := crc32.NewIEEE()
	crc.Write([]byte(kind))
	crc.Write(data)
	out.WriteString(kind)
	out.Write(data)
	binary.BigEndian.PutUint32(n[:], crc.Sum32())
	out.Write(n[:])
}
