"""Two SVGs for the README: when hardware pays, and what it costs.

python/bench_report.py builds the full interactive report - every format,
every opcode, every configuration. This builds the two pictures a reader
should see before deciding whether any of that applies to them, and it
answers ONE question: at which format, and from which problem size, does
this card beat the thing you would otherwise run?

WHAT "THE THING YOU WOULD OTHERWISE RUN" MEANS, because the answer
changes by an order of magnitude depending on the choice.

libcft's software backend is a bit-exact softfloat that DEFINES the
contract. It is the reference implementation, not a competitor: MPFR
beats it by 6-19x on add/mul/fma and by 94-316x on div/sqrt. Charting
the card against it produces speedups that are true, meaningless, and
the reason nobody believes accelerator benchmarks. So the baseline here is the fastest
REAL implementation measured at each (format, op, n) by
host/tools/cft_bench_peers.c - the CPU's own FPU where the format has
one, __float128 where the compiler has it, MPFR otherwise - and the
softfloat line is drawn faint beside it so the difference is visible
rather than quietly dropped.

The consequence is that the card LOSES at binary32 and binary64 on one
tile, which the README should say plainly; a chart that only showed wins
would not be worth publishing.

    python python/readme_charts.py sweep.csv \\
        --peers x86-64=peers-ladder.csv --peers arm64=peers-mac.csv \\
        --out docs/img/bench

Writes <name>-light.svg and <name>-dark.svg for each chart. Reference
them from Markdown with <picture> so GitHub picks the reader's theme:

    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="...-dark.svg">
      <img alt="..." src="...-light.svg">
    </picture>

No external fonts, no scripts, no CSS variables: GitHub sanitises SVG
and serves it from a separate origin, so anything that is not inline
literal geometry and colour will not survive.
"""
import argparse
import csv
import math
import pathlib
import sys

FORMAT_ORDER = ["fp32", "fp64", "fp128", "fp256"]
FORMAT_LABEL = {"fp32": "binary32", "fp64": "binary64",
                "fp128": "binary128", "fp256": "binary256"}
# libcft is the contract, not a competitor - never a candidate for "best".
NOT_A_PEER = "libcft"
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif")
MONO = ("ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace")

THEMES = {
    "light": {
        "bg": "#ffffff", "fg": "#1f2328", "muted": "#656d76",
        "grid": "#d8dee4", "axis": "#8c959f", "panel": "#f6f8fa",
        "win": "#1a7f37", "lose": "#cf222e", "parity": "#8c959f",
    },
    "dark": {
        "bg": "#0d1117", "fg": "#e6edf3", "muted": "#9198a1",
        "grid": "#30363d", "axis": "#6e7681", "panel": "#161b22",
        "win": "#3fb950", "lose": "#f85149", "parity": "#6e7681",
    },
}
SERIES = [
    ("sw",      "best available software", {"light": "#8250df", "dark": "#a371f7"}),
    ("soft",    "libcft softfloat (the reference, not a rival)",
                                           {"light": "#afb8c1", "dark": "#484f58"}),
    ("pcie",    "1 tile, over PCIe",       {"light": "#cf222e", "dark": "#f85149"}),
    ("res1",    "1 tile, resident",        {"light": "#bc4c00", "dark": "#db6d28"}),
    ("res4",    "4 tiles, resident",       {"light": "#0969da", "dark": "#54aeff"}),
]


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# --------------------------------------------------------------- loading
def load_sweep(path):
    """-> {(backend,path,tiles,format,op): {n: ns}}"""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                n, ns = int(r["n"]), float(r["ns_per_elem"])
            except (KeyError, ValueError):
                continue
            k = (r["backend"], r["path"], r["tiles"], r["format"], r["op"])
            out.setdefault(k, {})[n] = ns
    return out


def load_peers(path):
    """-> {(impl,format,op): {n: ns}}"""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                n, ns = int(r["n"]), float(r["ns_per_elem"])
            except (KeyError, ValueError):
                continue
            out.setdefault((r["impl"], r["format"], r["op"]), {})[n] = ns
    return out


def best_software(peers, fmt, op):
    """Fastest real implementation at each n, and who won there.

    Per-n rather than per-format on purpose: at binary128 __float128 beats
    MPFR on multiply and loses to it on fma by forty times, because fmaq is
    a soft routine. Taking a single winner per format would hide that.
    """
    curves, who = {}, {}
    for (impl, f, o), pts in peers.items():
        if f != fmt or o != op or impl == NOT_A_PEER:
            continue
        for n, ns in pts.items():
            if n not in curves or ns < curves[n]:
                curves[n], who[n] = ns, impl
    return curves, who


# ----------------------------------------------------------------- scales
class Log:
    def __init__(self, lo, hi, a, b):
        lo = max(lo, 1e-12)
        hi = max(hi, lo * 10)
        self.l0, self.l1, self.a, self.b = math.log10(lo), math.log10(hi), a, b

    def __call__(self, v):
        v = max(v, 1e-12)
        t = (math.log10(v) - self.l0) / (self.l1 - self.l0)
        return self.a + t * (self.b - self.a)


def decades(lo, hi):
    out, d = [], math.floor(math.log10(max(lo, 1e-12)))
    while 10 ** d <= hi * 1.0000001:
        if 10 ** d >= lo * 0.9999999:
            out.append(10 ** d)
        d += 1
    return out


def human(v):
    if v >= 1e9:
        return "%gG" % (v / 1e9)
    if v >= 1e6:
        return "%gM" % (v / 1e6)
    if v >= 1e3:
        return "%gk" % (v / 1e3)
    return "%g" % v


def ns_label(v):
    if v >= 1000:
        return "%g us" % (v / 1000.0)
    if v >= 1:
        return "%g ns" % v
    return "%g ns" % v


# ------------------------------------------------------------- chart one
def chart_when(sweep, peers_by_arch, theme, min_n=65536):
    """Speedup against the best real software, per format, at the top of the
    ladder. A bar chart because the question is categorical: which formats
    is this for? The parity line is the whole message."""
    T = THEMES[theme]
    W, H = 900, 470
    L, R, TOP, BOT = 92, 28, 78, 132
    op = "mul"

    # The comparison happens at the largest element count BOTH sides
    # measured, and that point has to be big enough to mean anything: below
    # a few thousand elements a device call is mostly fixed overhead, so a
    # partially-collected peer ladder would show the card losing by 100x at
    # binary128 and the chart would be confidently wrong. Formats without a
    # large shared point are dropped and named, never drawn small.
    groups, thin = [], []
    for fmt in FORMAT_ORDER:
        bars = []
        for arch, peers in peers_by_arch:
            sw, who = best_software(peers, fmt, op)
            if not sw:
                continue
            for tiles, tag in (("1", "1 tile"), ("4", "4 tiles")):
                dev = sweep.get(("device", "resident", tiles, fmt, op))
                if not dev:
                    continue
                shared = [n for n in sorted(set(sw) & set(dev)) if n >= min_n]
                if not shared:
                    continue
                n = shared[-1]
                bars.append(("%s vs %s" % (tag, arch), sw[n] / dev[n],
                             who[n], n, tiles))
        if bars:
            groups.append((fmt, bars))
        else:
            thin.append(fmt)
    if thin:
        sys.stderr.write("chart_when: no shared point at n>=%d for %s - "
                         "omitted rather than drawn from small-n data\n"
                         % (min_n, ", ".join(thin)))
    if not groups:
        return None

    ratios = [b[1] for _f, bs in groups for b in bs]
    lo, hi = min(ratios + [0.5]), max(ratios + [2.0])
    y = Log(10 ** math.floor(math.log10(lo)), 10 ** math.ceil(math.log10(hi)),
            H - BOT, TOP)

    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'viewBox="0 0 %d %d" role="img" aria-label="Speedup against the '
         'best available software, by format">' % (W, H, W, H)]
    s.append('<rect width="%d" height="%d" fill="%s"/>' % (W, H, T["bg"]))
    s.append('<text x="%d" y="30" font-family="%s" font-size="17" '
             'font-weight="600" fill="%s">Where hardware starts to pay</text>'
             % (L - 60, FONT, T["fg"]))
    s.append('<text x="%d" y="52" font-family="%s" font-size="12.5" fill="%s">'
             'Resident tiles against the fastest real software, each at the '
             'largest element count both sides measured. Above the line, the '
             'card wins.</text>' % (L - 60, FONT, T["muted"]))

    for g in decades(10 ** math.floor(math.log10(lo)),
                     10 ** math.ceil(math.log10(hi))):
        yy = y(g)
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
                 'stroke-width="1"/>' % (L, yy, W - R, yy, T["grid"]))
        s.append('<text x="%d" y="%.1f" font-family="%s" font-size="11" '
                 'fill="%s" text-anchor="end">%sx</text>'
                 % (L - 8, yy + 4, MONO, T["muted"], human(g)))
    yp = y(1.0)
    s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
             'stroke-width="1.75" stroke-dasharray="6 4"/>'
             % (L, yp, W - R, yp, T["parity"]))
    s.append('<text x="%d" y="%.1f" font-family="%s" font-size="11" '
             'fill="%s">parity</text>' % (L + 6, yp - 7, FONT, T["muted"]))

    span = (W - R - L) / float(len(groups))
    for gi, (fmt, bars) in enumerate(groups):
        gx = L + gi * span
        bw = min(38.0, (span - 30) / max(len(bars), 1))
        total = bw * len(bars)
        x0 = gx + (span - total) / 2.0
        for bi, (lab, ratio, who, n, tiles) in enumerate(bars):
            bx = x0 + bi * bw
            top, base = (y(ratio), yp) if ratio >= 1 else (yp, y(ratio))
            col = T["win"] if ratio >= 1 else T["lose"]
            s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                     'fill="%s" opacity="%s"/>'
                     % (bx + 2, top, bw - 4, max(base - top, 1), col,
                        "1" if tiles == "4" else "0.62"))
            txt = ("%.1fx" % ratio) if ratio >= 1 else ("/%.1f" % (1 / ratio))
            ty = (top - 5) if ratio >= 1 else min(base + 13, H - BOT - 5)
            s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="10.5" '
                     'fill="%s" text-anchor="middle">%s</text>'
                     % (bx + bw / 2, ty, MONO, T["fg"], txt))
            s.append('<text x="%.1f" y="%d" font-family="%s" font-size="9.5" '
                     'fill="%s" text-anchor="end" transform="rotate(-34 '
                     '%.1f %d)">%s</text>'
                     % (bx + bw / 2, H - BOT + 20, FONT, T["muted"],
                        bx + bw / 2, H - BOT + 20, esc(lab)))
        s.append('<text x="%.1f" y="%d" font-family="%s" font-size="13" '
                 'font-weight="600" fill="%s" text-anchor="middle">%s</text>'
                 % (gx + span / 2, H - 30, FONT, T["fg"], FORMAT_LABEL[fmt]))
        beat, gn = bars[0][2], max(b[3] for b in bars)
        s.append('<text x="%.1f" y="%d" font-family="%s" font-size="10.5" '
                 'fill="%s" text-anchor="middle">vs %s at n = %s</text>'
                 % (gx + span / 2, H - 14, FONT, T["muted"], esc(beat),
                    "{:,}".format(gn)))
    s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s"/>'
             % (L, H - BOT, W - R, H - BOT, T["axis"]))
    s.append("</svg>")
    return "\n".join(s)


# ------------------------------------------------------------- chart two
def chart_cost(sweep, peers, theme):
    """Cost per element against problem size, one panel per format."""
    T = THEMES[theme]
    W, H = 900, 700
    op = "mul"
    cols, rows_n = 2, 2
    LEGEND_H = 74                      # reserved; panels never enter it
    PW = (W - 70) / cols
    PH = (H - 78 - LEGEND_H - 56) / rows_n

    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'viewBox="0 0 %d %d" role="img" aria-label="Nanoseconds per element '
         'against problem size, by format">' % (W, H, W, H)]
    s.append('<rect width="%d" height="%d" fill="%s"/>' % (W, H, T["bg"]))
    s.append('<text x="24" y="30" font-family="%s" font-size="17" '
             'font-weight="600" fill="%s">What it costs, by problem size</text>'
             % (FONT, T["fg"]))
    s.append('<text x="24" y="52" font-family="%s" font-size="12.5" fill="%s">'
             'Nanoseconds per element, multiply. Both axes logarithmic; lower '
             'is faster. Where two lines cross is where the choice changes.'
             '</text>' % (FONT, T["muted"]))

    for i, fmt in enumerate(FORMAT_ORDER):
        cx, cy = 24 + (i % cols) * (PW + 22), 78 + (i // cols) * (PH + 56)
        px0, py0 = cx + 58, cy + 26
        px1, py1 = cx + PW - 12, cy + PH - 34

        curves = []
        sw, who = best_software(peers, fmt, op)
        if sw:
            curves.append(("sw", sw))
        soft = sweep.get(("software", "host", "0", fmt, op))
        if soft:
            curves.append(("soft", soft))
        for tag, key in (("pcie", ("device", "host", "1", fmt, op)),
                         ("res1", ("device", "resident", "1", fmt, op)),
                         ("res4", ("device", "resident", "4", fmt, op))):
            c = sweep.get(key)
            if c:
                curves.append((tag, c))
        if not curves:
            continue

        xs = [n for _t, c in curves for n in c]
        ys = [v for _t, c in curves for v in c.values()]
        X = Log(min(xs), max(xs), px0, px1)
        Y = Log(min(ys), max(ys), py1, py0)

        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                 % (px0, py0, px1 - px0, py1 - py0, T["panel"]))
        for g in decades(min(ys), max(ys)):
            yy = Y(g)
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                     % (px0, yy, px1, yy, T["grid"]))
            s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="9.5" '
                     'fill="%s" text-anchor="end">%s</text>'
                     % (px0 - 6, yy + 3.5, MONO, T["muted"], ns_label(g)))
        for g in decades(min(xs), max(xs)):
            xx = X(g)
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                     % (xx, py0, xx, py1, T["grid"]))
            s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="9.5" '
                     'fill="%s" text-anchor="middle">%s</text>'
                     % (xx, py1 + 14, MONO, T["muted"], human(g)))

        colours = {t: c[theme] for t, _l, c in SERIES}
        for tag, curve in curves:
            colour = colours[tag]
            pts = sorted(curve.items())
            d = " ".join("%s%.1f,%.1f" % ("M" if j == 0 else "L", X(n), Y(v))
                         for j, (n, v) in enumerate(pts))
            dash = ' stroke-dasharray="4 3"' if tag == "soft" else ""
            s.append('<path d="%s" fill="none" stroke="%s" stroke-width="%s"%s '
                     'stroke-linejoin="round"/>'
                     % (d, colour, "1.6" if tag == "soft" else "2.2", dash))

        s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="13" '
                 'font-weight="600" fill="%s">%s</text>'
                 % (px0, cy + 16, FONT, T["fg"], FORMAT_LABEL[fmt]))
        if sw:
            names = sorted({who[n] for n in who})
            s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="10" '
                     'fill="%s" text-anchor="end">best software: %s</text>'
                     % (px1, cy + 16, FONT, T["muted"], esc(", ".join(names))))
        s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="10" '
                 'fill="%s" text-anchor="middle">elements per call</text>'
                 % ((px0 + px1) / 2, py1 + 30, FONT, T["muted"]))

    # Three fixed columns. The previous version advanced x by a guess at
    # the rendered text width and wrapped into the panels above it.
    COLW, y0 = (W - 48) / 3.0, H - LEGEND_H + 24
    for i, (tag, lab, cols_) in enumerate(SERIES):
        lx = 24 + (i % 3) * COLW
        ly = y0 + (i // 3) * 22
        s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                 'stroke-width="2.4"%s/>'
                 % (lx, ly, lx + 22, ly, cols_[theme],
                    ' stroke-dasharray="4 3"' if tag == "soft" else ""))
        s.append('<text x="%.1f" y="%.1f" font-family="%s" font-size="11" '
                 'fill="%s">%s</text>'
                 % (lx + 28, ly + 4, FONT, T["fg"], esc(lab)))
    s.append("</svg>")
    return "\n".join(s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", help="sweep.csv from hw/bench-sweep.sh")
    ap.add_argument("--peers", action="append", default=[], metavar="ARCH=FILE",
                    help="cft-bench-peers CSV for one machine; repeatable")
    ap.add_argument("--out", default="docs/img/bench")
    a = ap.parse_args(argv)

    sweep = load_sweep(a.csv)
    if not sweep:
        sys.stderr.write("no usable rows in %s\n" % a.csv)
        return 1

    peers_by_arch = []
    for spec in a.peers:
        arch, sep, fname = spec.partition("=")
        if not sep:
            sys.stderr.write("--peers wants ARCH=FILE, got %r\n" % spec)
            return 1
        p = load_peers(fname)
        if not p:
            sys.stderr.write("no usable peer rows in %s\n" % fname)
            return 1
        peers_by_arch.append((arch, p))
    if not peers_by_arch:
        sys.stderr.write("at least one --peers is required: the whole point "
                         "is not to chart against our own softfloat\n")
        return 1

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    primary = peers_by_arch[0][1]

    made = []
    for theme in ("light", "dark"):
        for name, svg in (("when-hardware-pays",
                           chart_when(sweep, peers_by_arch, theme)),
                          ("cost-by-size",
                           chart_cost(sweep, primary, theme))):
            if svg is None:
                sys.stderr.write("%s: no data, skipped\n" % name)
                continue
            f = out / ("%s-%s.svg" % (name, theme))
            # newline="" so these are LF on every platform. They are
            # committed artifacts and .gitattributes normalises them at
            # commit anyway; writing CRLF here only makes the working tree
            # disagree with the blob and warns on every `git add`.
            f.write_text(svg + "\n", encoding="utf-8", newline="")
            made.append(f)
    for f in made:
        print("  %s  (%d bytes)" % (f, f.stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
