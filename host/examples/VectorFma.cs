// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The same program as vector_fma.c, in C#, through P/Invoke.
//
//     dotnet run --project host/examples/vector_fma_cs.csproj
//     dotnet run --project host/examples/vector_fma_cs.csproj -- artifact.xclbin
//
// It must print exactly what the C program prints - every line, every
// digit. Nothing beyond the .NET SDK is used: no NuGet package, no
// binding generator, no unsafe block. The extern declarations below
// are the entire binding - the claim cft.h makes about its ABI, paid
// out in another language.
//
// [DllImport] names the library "cft" and never a path. Left alone,
// the runtime would probe the operating system's search path for it,
// which looks tolerant and is not - the same trap the ctypes and
// Julia ports refuse: a loader that searches will happily find a
// stale or foreign library and fail somewhere far from the real
// problem. The resolver installed in Main therefore maps "cft" to
// exactly one candidate file - CFT_LIB if set, else the platform's
// name beside host/ - and anything else is "build it first", said
// before the runtime gets a chance to go looking.
//
// As in the other ports, the arithmetic is not reimplemented here.
// Only the operand stream and the checksum are, because they are the
// test harness rather than the product; everything the library
// guarantees still happens inside the library.
//
// Verified 2026-09-01: dotnet SDK 8.0.130 on Linux (the cft2204 WSL
// distro) and 10.0.301 on Windows, each byte-identical to the C
// example on the same machine - stdout, both error paths' stderr,
// and the exit codes. Windows needs no \r concession: .NET's console
// and msvcrt's text mode agree, so cmp passes where examples-lang
// only asks diff --strip-trailing-cr to.

using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;

static class VectorFma
{
    // cft_op and cft_round - the values are normative (cft.h), so a
    // caller writes the names and never the register layout behind
    // them.
    const int FMA = 0;
    const int RNE = 0;

    const int N = 4096;

    // width, exp_w, man_w, bias - the geometry table vector_fma.c
    // carries. Operand-stream machinery, not format knowledge the
    // caller should own: element sizes and names below still come
    // from the library, because a size the caller guesses is a size
    // that goes stale.
    static readonly (int Width, int ExpW, int ManW, int Bias)[] Geom =
    {
        (32, 8, 23, 127),
        (64, 11, 52, 1023),
        (128, 15, 112, 16383),
        (256, 19, 236, 262143),
    };

    // The binding. Cdecl is stated rather than defaulted because
    // 32-bit Windows would otherwise assume stdcall; byte[] marshals
    // as a pinned pointer to the first element, no copy in either
    // direction, so cft_run writes d in place; nuint is size_t on
    // every runtime .NET has, the way usize is in the Rust port. The
    // C names are kept as written so the declarations can be read
    // against cft.h line by line - that they transcribe faithfully is
    // what the checksum diff proves.
    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern int cft_open(byte[] artifact, int index, out IntPtr dev);

    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern void cft_close(IntPtr dev);

    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern int cft_supports(IntPtr dev, int op, int fmt);

    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern nuint cft_format_size(int fmt);

    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern IntPtr cft_format_name(int fmt);

    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern IntPtr cft_strerror(int status);

    [DllImport("cft", CallingConvention = CallingConvention.Cdecl)]
    static extern int cft_run(IntPtr dev, int op, int fmt, int rnd,
                              byte[] a, byte[] b, byte[] c, byte[] d,
                              nuint n, ref uint flagsOut, IntPtr busOut);

    // The one candidate, loaded in Main after the existence check.
    // The resolver hands this handle to every [DllImport("cft")] and
    // answers zero for any other name, which lets the runtime's
    // default resolution keep handling a name this file never uses.
    static IntPtr Lib = IntPtr.Zero;

    static IntPtr Resolve(string name, Assembly asm,
                          DllImportSearchPath? searchPath) =>
        name == "cft" ? Lib : IntPtr.Zero;

    // Exactly one candidate, chosen by platform - the same policy as
    // vector_fma_ctypes.py, for the same reason: listing every name
    // and taking the first that exists means a tree built from two
    // platforms loads the foreign library and fails with a loader
    // error instead of "build it first". [CallerFilePath] is this
    // language's __file__ - the compiler burns the source path in at
    // the call site, and under `dotnet run` that is the checkout
    // being run; the built binary's own location is a bin/ subtree
    // that says nothing about where host/ is.
    static string SourceDir([CallerFilePath] string src = "") =>
        Path.GetDirectoryName(src);

    static string LibraryPath()
    {
        string overridePath = Environment.GetEnvironmentVariable("CFT_LIB");
        if (!string.IsNullOrEmpty(overridePath))
            return overridePath;
        string name = OperatingSystem.IsWindows() ? "cft.dll"
                    : OperatingSystem.IsMacOS()   ? "libcft.dylib"
                    : "libcft.so";
        string root = Path.GetFullPath(Path.Combine(SourceDir(), "..", ".."));
        return Path.Combine(root, "host", name);
    }

    // cft_strerror and cft_format_name return static storage (cft.h
    // says so): read it, never free it.
    static string CStr(IntPtr p) => Marshal.PtrToStringUTF8(p);
    static string StrError(int st) => CStr(cft_strerror(st));

    // xorshift32, stepped once per byte - the stream vector_fma.c
    // generates, which is what lets the two checksums be compared at
    // all. C# uint shifts drop the high bits exactly as C's unsigned
    // ops do, so the port is line for line.
    sealed class Rng
    {
        uint s;
        public Rng(uint seed) => s = seed == 0 ? 1u : seed;
        public byte NextByte()
        {
            s ^= s << 13;
            s ^= s >> 17;
            s ^= s << 5;
            return (byte)(s & 0xffu);
        }
    }

    // One element: a normal with a fraction from the stream and an
    // exponent within 32 of 1.0, so that products stay in range and
    // the run exercises rounding rather than overflow. vector_fma.c
    // line for line.
    static void MakeElement(Span<byte> e, Rng rng,
                            (int Width, int ExpW, int ManW, int Bias) g)
    {
        int nb = g.Width / 8, kb = g.ManW / 8, rb = g.ManW % 8;

        for (int j = 0; j < nb; j++)
            e[j] = rng.NextByte();
        uint ef = (uint)(g.Bias - 32 + (rng.NextByte() & 63));

        e[kb] &= (byte)((1u << rb) - 1u);
        for (int j = kb + 1; j < nb; j++)
            e[j] = 0;
        for (int j = 0; j < g.ExpW; j++)
            if (((ef >> j) & 1u) != 0)
                e[(g.ManW + j) / 8] |= (byte)(1u << ((g.ManW + j) % 8));
        if ((rng.NextByte() & 1u) != 0)
            e[nb - 1] |= 0x80;
    }

    // FNV-1a, 64-bit. The constants are written in hex because that
    // is how they are specified; transcribing them as decimal is how
    // you get a checksum that is stable, plausible, and not FNV.
    // unchecked is not pedantry either: FNV is arithmetic modulo
    // 2^64, which C's unsigned types state implicitly and C# makes
    // you state out loud - a project built with overflow checks on
    // would otherwise throw on the first product.
    static ulong Fnv1a(byte[] p)
    {
        ulong h = 0xcbf29ce484222325UL;
        foreach (byte b in p)
        {
            h ^= b;
            h = unchecked(h * 0x100000001b3UL);
        }
        return h;
    }

    static int Main(string[] args)
    {
        string artifact = args.Length > 0 ? args[0] : null;
        string backend = artifact ?? "software";

        string path = LibraryPath();
        if (!File.Exists(path))
        {
            Console.Error.WriteLine(
                $"{path} not found - run `make -C host` first");
            return 1;
        }
        Lib = NativeLibrary.Load(path);
        NativeLibrary.SetDllImportResolver(typeof(VectorFma).Assembly,
                                           Resolve);

        // NUL-terminated UTF-8, built by hand: default string
        // marshalling would consult the ANSI code page on Windows,
        // and an encoding decided by machine configuration has no
        // place here.
        byte[] cArtifact = null;
        if (artifact != null)
        {
            byte[] u = Encoding.UTF8.GetBytes(artifact);
            cArtifact = new byte[u.Length + 1];
            u.CopyTo(cArtifact, 0);
        }

        int st = cft_open(cArtifact, 0, out IntPtr dev);
        if (st != 0)
        {
            Console.Error.WriteLine($"cft_open({backend}): {StrError(st)}");
            return 1;
        }
        Console.WriteLine($"cft-fp256 vector fma, {backend} backend");

        for (int f = 0; f < 4; f++)
        {
            var g = Geom[f];

            // The name comes from the library, not a local table -
            // cft.h provides cft_format_name precisely so a binding,
            // a log line and a conformance report all say the same
            // thing.
            string name = CStr(cft_format_name(f));

            if (cft_supports(dev, FMA, f) == 0)
            {
                Console.WriteLine($"{name,-6} not available on this device");
                continue;
            }

            int esz = (int)cft_format_size(f);

            byte[] a = new byte[N * esz];
            byte[] b = new byte[N * esz];
            byte[] c = new byte[N * esz];
            byte[] d = new byte[N * esz];

            // Seeded per format, so each line is independent of the
            // ones before it and can be reproduced on its own.
            var rng = new Rng(0x1234567u + (uint)f);
            for (int i = 0; i < N; i++)
            {
                MakeElement(a.AsSpan(i * esz, esz), rng, g);
                MakeElement(b.AsSpan(i * esz, esz), rng, g);
                MakeElement(c.AsSpan(i * esz, esz), rng, g);
            }

            uint flags = 0;
            st = cft_run(dev, FMA, f, RNE, a, b, c, d, (nuint)N,
                         ref flags, IntPtr.Zero);
            if (st != 0)
            {
                Console.Error.WriteLine($"cft_run {name}: {StrError(st)}");
                cft_close(dev);
                return 1;
            }

            Console.WriteLine($"{name,-6} n={N} rne  " +
                              $"checksum 0x{Fnv1a(d):x16}  " +
                              $"flags 0x{flags:x2}");
        }

        cft_close(dev);
        return 0;
    }
}
