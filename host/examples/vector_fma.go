// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The same program as vector_fma.c, in Go, through cgo. One file, no
// module, no go.mod, nothing beyond the standard library:
//
//     go build -o host/vector-fma-go host/examples/vector_fma.go
//     ./host/vector-fma-go
//
// (or `go run host/examples/vector_fma.go`, which builds and runs in
// one step; either way `make -C host` must have produced libcft.a
// first, and cgo needs the C compiler that build already proved is
// on PATH).
//
// It must print exactly what the C program prints - every line, every
// digit. `make -C host examples-lang` diffs the two rather than
// trusting either.
//
// This port differs from the Rust and Julia ones in a way worth
// stating: there is no transcription. The #cgo lines below hand the
// real cft.h to a real C compiler, so the prototypes, CFT_FMA and
// CFT_RNE arrive from the header itself, and the binding cannot
// drift from the library because it is not a copy of anything. The
// geometry table is the only thing carried by hand, and it is
// operand-stream machinery, not format knowledge: element sizes and
// names still come from the library, because a size the caller
// guesses is a size that goes stale.
//
// Linking: LDFLAGS names host/libcft.a as a direct linker input
// rather than saying -L host -lcft, because -l prefers the shared
// library when both are present, and an example that silently linked
// libcft.so would fail at launch on any machine without
// LD_LIBRARY_PATH pointed at the tree - a build-time choice
// surfacing as somebody else's run-time mystery. ${SRCDIR} is this
// file's directory, expanded by cgo, so the commands above work from
// any cwd.
//
// Verified 2026-09-01: go1.18.1 (Ubuntu's golang-go) on Linux, the
// cft2204 WSL distro - byte-identical to the C example on the same
// machine, the fma lines and the missing-artifact stderr path both,
// through `go build` and `go run` alike, and the four checksums are
// the canonical set the other ports print.

package main

/*
#cgo CFLAGS: -I${SRCDIR}/../include
#cgo LDFLAGS: ${SRCDIR}/../libcft.a
#include <stdlib.h>
#include "cft.h"
*/
import "C"

import (
	"fmt"
	"hash/fnv"
	"os"
	"unsafe"
)

const n = 4096

// width, exp_w, man_w, bias - the geometry table vector_fma.c
// carries, and the one hand-carried table in this file (see the
// header comment for why it is allowed to be).
type geom struct{ width, expW, manW, bias int }

var geoms = [4]geom{
	{32, 8, 23, 127},
	{64, 11, 52, 1023},
	{128, 15, 112, 16383},
	{256, 19, 236, 262143},
}

// xorshift32, stepped once per byte - the stream vector_fma.c
// generates, which is what lets the two checksums be compared at
// all. Go's uint32 shifts and wraps exactly as C's unsigned int
// does, so the port is line for line.
type rng struct{ s uint32 }

func newRng(seed uint32) *rng {
	if seed == 0 {
		seed = 1
	}
	return &rng{s: seed}
}

func (r *rng) byte() byte {
	r.s ^= r.s << 13
	r.s ^= r.s >> 17
	r.s ^= r.s << 5
	return byte(r.s & 0xff)
}

// One element: a normal with a fraction from the stream and an
// exponent within 32 of 1.0, so that products stay in range and the
// run exercises rounding rather than overflow. vector_fma.c line for
// line.
func makeElement(e []byte, r *rng, g geom) {
	nb := g.width / 8
	kb := g.manW / 8
	rb := g.manW % 8

	for j := 0; j < nb; j++ {
		e[j] = r.byte()
	}
	ef := uint32(g.bias - 32 + int(r.byte()&63))

	e[kb] &= byte((uint32(1) << rb) - 1)
	for j := kb + 1; j < nb; j++ {
		e[j] = 0
	}
	for j := 0; j < g.expW; j++ {
		if (ef>>j)&1 != 0 {
			bit := g.manW + j
			e[bit/8] |= byte(1) << (bit % 8)
		}
	}
	if r.byte()&1 != 0 {
		e[nb-1] |= 0x80
	}
}

// FNV-1a, 64-bit. The other ports restate the two constants in hex -
// the base they are specified in - and vector_fma.c explains why. Go
// does not get to make that mistake at all: the standard library
// ships FNV-1a as hash/fnv, so the checksum here is an
// implementation nobody in this repository typed, which doubles as
// an outside witness that what the examples share really is FNV-1a
// and not something FNV-flavored.
func checksum(p []byte) uint64 {
	h := fnv.New64a()
	h.Write(p)
	return h.Sum64()
}

// cft_strerror returns static storage (cft.h says so), so copying it
// into a Go string right away is the entire lifetime story.
func strerror(st C.cft_status) string {
	return C.GoString(C.cft_strerror(st))
}

func main() {
	backend := "software"
	var cArtifact *C.char
	if len(os.Args) > 1 {
		backend = os.Args[1]
		cArtifact = C.CString(os.Args[1])
	}

	var dev *C.cft_device
	st := C.cft_open(cArtifact, 0, &dev)
	if cArtifact != nil {
		C.free(unsafe.Pointer(cArtifact))
	}
	if st != C.CFT_OK {
		fmt.Fprintf(os.Stderr, "cft_open(%s): %s\n", backend, strerror(st))
		os.Exit(1)
	}
	fmt.Printf("cft-fp256 vector fma, %s backend\n", backend)

	for f := 0; f < 4; f++ {
		g := geoms[f]
		cfmt := C.cft_format(f)

		// The name comes from the library, not a local table -
		// cft.h provides cft_format_name precisely so a binding, a
		// log line and a conformance report all say the same thing.
		name := C.GoString(C.cft_format_name(cfmt))

		if C.cft_supports(dev, C.CFT_FMA, cfmt) == 0 {
			fmt.Printf("%-6s not available on this device\n", name)
			continue
		}
		esz := int(C.cft_format_size(cfmt))

		a := make([]byte, n*esz)
		b := make([]byte, n*esz)
		c := make([]byte, n*esz)
		d := make([]byte, n*esz)

		// Seeded per format, so each line is independent of the
		// ones before it and can be reproduced on its own.
		r := newRng(0x1234567 + uint32(f))
		for i := 0; i < n; i++ {
			makeElement(a[i*esz:(i+1)*esz], r, g)
			makeElement(b[i*esz:(i+1)*esz], r, g)
			makeElement(c[i*esz:(i+1)*esz], r, g)
		}

		var flags C.uint32_t
		st = C.cft_run(dev, C.CFT_FMA, cfmt, C.CFT_RNE,
			unsafe.Pointer(&a[0]), unsafe.Pointer(&b[0]),
			unsafe.Pointer(&c[0]), unsafe.Pointer(&d[0]),
			C.size_t(n), &flags, nil)
		if st != C.CFT_OK {
			fmt.Fprintf(os.Stderr, "cft_run %s: %s\n", name, strerror(st))
			C.cft_close(dev)
			os.Exit(1)
		}

		fmt.Printf("%-6s n=%d rne  checksum 0x%016x  flags 0x%02x\n",
			name, n, checksum(d), uint32(flags))
	}

	C.cft_close(dev)
}
