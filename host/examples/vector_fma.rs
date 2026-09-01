// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The same program as vector_fma.c, in Rust, through a hand-declared
// extern block. No cargo, no crate, no bindgen - one file, one
// command, deliberately the same shape as the C example's:
//
//     rustc --edition 2021 -L native=host host/examples/vector_fma.rs -o host/vector-fma-rs
//     ./host/vector-fma-rs
//
// It must print exactly what the C program prints - every line, every
// digit. `make -C host examples-lang` diffs the two rather than
// trusting either.
//
// The extern block below is the entire binding: seven declarations
// transcribed from cft.h. That a transcription this small is enough
// is the reason the library speaks a C ABI, and that the
// transcription is faithful is what the checksum diff proves - which
// is why this file declares by hand instead of shipping generated
// bindings nobody diffs.
//
// Linking: host/libcft.a, statically, on every toolchain. That this
// holds even for x86_64-pc-windows-msvc rustc against the MinGW-built
// archive is not luck and is worth recording: plain COFF objects that
// want only ucrt names (malloc, memcpy, fopen...) link fine, and the
// one member that leans on the MinGW runtime - conformance.o, which
// wants ___chkstk_ms and __mingw_vsnprintf from libgcc/libmingwex -
// is never pulled, because nothing here references cft_conformance.
// If a later revision of this example calls it, expect the MSVC link
// to break with those two names, and either link the MinGW runtime
// archives or split the attribute to kind = "raw-dylib" against
// cft.dll for that toolchain.

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};

// cft_op and cft_round - the values are normative (cft.h), so a
// caller writes the names and never the register layout behind them.
const FMA: c_int = 0;
const RNE: c_int = 0;

const N: usize = 4096;

// size_t is usize on every target rustc has - both are defined as the
// pointer width - so the n and cft_format_size signatures below need
// no conversion layer.
#[link(name = "cft", kind = "static")]
extern "C" {
    fn cft_open(artifact: *const c_char, index: c_int,
                out: *mut *mut c_void) -> c_int;
    fn cft_close(dev: *mut c_void);
    fn cft_supports(dev: *mut c_void, op: c_int, fmt: c_int) -> c_int;
    fn cft_format_size(fmt: c_int) -> usize;
    fn cft_format_name(fmt: c_int) -> *const c_char;
    fn cft_strerror(status: c_int) -> *const c_char;
    fn cft_run(dev: *mut c_void, op: c_int, fmt: c_int, rnd: c_int,
               a: *const c_void, b: *const c_void, c: *const c_void,
               d: *mut c_void, n: usize,
               flags_out: *mut u32, bus_out: *mut u32) -> c_int;
}

// width, exp_w, man_w, bias - the geometry table vector_fma.c
// carries. Operand-stream machinery, not format knowledge the caller
// should own: element sizes and names still come from the library,
// because a size the caller guesses is a size that goes stale.
struct Geom { width: usize, exp_w: usize, man_w: usize, bias: i32 }

const GEOM: [Geom; 4] = [
    Geom { width: 32,  exp_w: 8,  man_w: 23,  bias: 127 },
    Geom { width: 64,  exp_w: 11, man_w: 52,  bias: 1023 },
    Geom { width: 128, exp_w: 15, man_w: 112, bias: 16383 },
    Geom { width: 256, exp_w: 19, man_w: 236, bias: 262143 },
];

// xorshift32, stepped once per byte - the stream vector_fma.c
// generates, which is what lets the two checksums be compared at
// all. Shifts and xors on u32 behave exactly as C's unsigned ops, so
// the port is line for line.
struct Rng { s: u32 }

impl Rng {
    fn new(seed: u32) -> Rng {
        Rng { s: if seed == 0 { 1 } else { seed } }
    }
    fn byte(&mut self) -> u8 {
        self.s ^= self.s << 13;
        self.s ^= self.s >> 17;
        self.s ^= self.s << 5;
        (self.s & 0xff) as u8
    }
}

// One element: a normal with a fraction from the stream and an
// exponent within 32 of 1.0, so that products stay in range and the
// run exercises rounding rather than overflow. vector_fma.c line for
// line.
fn make_element(e: &mut [u8], rng: &mut Rng, g: &Geom) {
    let nb = g.width / 8;
    let kb = g.man_w / 8;
    let rb = g.man_w % 8;

    for j in 0..nb {
        e[j] = rng.byte();
    }
    let ef = (g.bias - 32 + (rng.byte() & 63) as i32) as u32;

    e[kb] &= ((1u32 << rb) - 1) as u8;
    for j in kb + 1..nb {
        e[j] = 0;
    }
    for j in 0..g.exp_w {
        if ((ef >> j) & 1) != 0 {
            e[(g.man_w + j) / 8] |= 1u8 << ((g.man_w + j) % 8);
        }
    }
    if (rng.byte() & 1) != 0 {
        e[nb - 1] |= 0x80;
    }
}

// FNV-1a, 64-bit. The constants are written in hex because that is
// how they are specified; transcribing them as decimal is how you
// get a checksum that is stable, plausible, and not FNV.
// wrapping_mul is not pedantry either: FNV is arithmetic modulo
// 2^64, which C's unsigned types state implicitly and Rust makes you
// state out loud - a debug build would otherwise panic on the first
// overflow, and be right to.
fn fnv1a(p: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for &b in p {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

// cft_strerror and cft_format_name return static storage (cft.h says
// so), so borrowing just long enough to copy into a String is sound.
unsafe fn cstr(p: *const c_char) -> String {
    CStr::from_ptr(p).to_string_lossy().into_owned()
}

fn strerror(st: c_int) -> String {
    unsafe { cstr(cft_strerror(st)) }
}

fn main() {
    let artifact = std::env::args().nth(1);
    // The CString owns the NUL-terminated copy; it is bound here, not
    // inlined at the call, so the pointer cft_open receives outlives
    // the call instead of dangling off a dropped temporary.
    let c_artifact = artifact.as_deref()
        .map(|s| CString::new(s).expect("artifact path contains NUL"));
    let backend = artifact.as_deref().unwrap_or("software");

    let mut dev: *mut c_void = std::ptr::null_mut();
    let st = unsafe {
        cft_open(c_artifact.as_ref().map_or(std::ptr::null(), |s| s.as_ptr()),
                 0, &mut dev)
    };
    if st != 0 {
        eprintln!("cft_open({}): {}", backend, strerror(st));
        std::process::exit(1);
    }
    println!("cft-fp256 vector fma, {} backend", backend);

    for fmt in 0..4 {
        let g = &GEOM[fmt as usize];
        let name = unsafe { cstr(cft_format_name(fmt)) };

        if unsafe { cft_supports(dev, FMA, fmt) } == 0 {
            println!("{:<6} not available on this device", name);
            continue;
        }
        let esz = unsafe { cft_format_size(fmt) };

        let mut a = vec![0u8; N * esz];
        let mut b = vec![0u8; N * esz];
        let mut c = vec![0u8; N * esz];
        let mut d = vec![0u8; N * esz];

        // Seeded per format, so each line is independent of the ones
        // before it and can be reproduced on its own.
        let mut rng = Rng::new(0x1234567 + fmt as u32);
        for i in 0..N {
            make_element(&mut a[i * esz..(i + 1) * esz], &mut rng, g);
            make_element(&mut b[i * esz..(i + 1) * esz], &mut rng, g);
            make_element(&mut c[i * esz..(i + 1) * esz], &mut rng, g);
        }

        let mut flags: u32 = 0;
        let st = unsafe {
            cft_run(dev, FMA, fmt, RNE,
                    a.as_ptr() as *const c_void,
                    b.as_ptr() as *const c_void,
                    c.as_ptr() as *const c_void,
                    d.as_mut_ptr() as *mut c_void,
                    N, &mut flags, std::ptr::null_mut())
        };
        if st != 0 {
            eprintln!("cft_run {}: {}", name, strerror(st));
            unsafe { cft_close(dev) };
            std::process::exit(1);
        }

        println!("{:<6} n={} rne  checksum 0x{:016x}  flags 0x{:02x}",
                 name, N, fnv1a(&d), flags);
    }

    unsafe { cft_close(dev) };
}
