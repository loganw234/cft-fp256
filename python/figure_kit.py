# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The drawing kit behind python/project_figures.py: a small SVG writer and the
axes, scales and legends the figures share.

It stands on python/readme_charts.py, which draws the README's two charts and
owns the project's look: THEMES, FONT, MONO, Log, decades and human are IMPORTED
from there, not copied, so a figure here and a chart there cannot drift apart
in colour or scale. What this adds is what the README's two charts did not
need: a categorical palette that holds in both themes, a linear scale with
tick choice, dates, wrapped text, and a few mark types.

THE RULES ARE readme_charts.py's, because GitHub's are: inline literal geometry
and colour only. No external fonts, no scripts, no CSS variables, no <style>,
no <defs>, no <use>. Every element here is svg, rect, line, path, polygon,
circle, text or title, and every colour is a literal hex.

DETERMINISM IS A REQUIREMENT, NOT A HOPE. A rerun writes byte-identical files:
  - every coordinate goes through n(), which prints one decimal and never
    "-0.0";
  - text is ASCII; anything else becomes a numeric character reference;
  - nothing here reads the clock, the environment, the locale or a random
    source, and no set is ever iterated into the output;
  - files are written LF, with a final newline, whatever the platform.
The one place a float could differ between a Windows C runtime and glibc is a
last-bit difference in log10 landing exactly on a rounding tie of a one
decimal coordinate; --check is run on both, and records that they agree.
"""
import datetime
import math
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:          # python -I does not put the script's directory there
    sys.path.insert(0, str(_HERE))
import readme_charts as rc                                       # noqa: E402

FONT = rc.FONT
MONO = rc.MONO
Log = rc.Log
decades = rc.decades
human = rc.human

# The README's themes, extended. "cats" is the categorical order: the same
# nine hues in both themes, each lifted in the dark one so that it keeps its
# contrast against #0d1117 rather than being the light hue on a dark page.
THEMES = {}
for _t, _v in rc.THEMES.items():
    THEMES[_t] = dict(_v)
THEMES["light"].update(
    cats=["#0969da", "#bc4c00", "#1a7f37", "#8250df", "#cf222e", "#9a6700",
          "#0e7a86", "#bf3989", "#6e7781"],
    pale="#eaeef2", ink2="#424a53")
THEMES["dark"].update(
    cats=["#54aeff", "#db6d28", "#3fb950", "#a371f7", "#f85149", "#d29922",
          "#39c5cf", "#db61a2", "#8b949e"],
    pale="#21262d", ink2="#c9d1d9")
THEME_NAMES = ("light", "dark")

SANS_EM = 0.58      # average advance of the sans stack, in ems, for LAYOUT only
MONO_EM = 0.61


def n(v):
    """One decimal, never "-0.0": the only way a coordinate is printed."""
    s = "%.1f" % v
    return "0.0" if s == "-0.0" else s


def esc(t):
    """XML-escaped and ASCII-only (non-ASCII becomes a numeric reference)."""
    out = []
    for ch in str(t):
        o = ord(ch)
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        elif o > 126 or (o < 32 and ch not in "\n\t"):
            out.append("&#%d;" % o)
        else:
            out.append(ch)
    return "".join(out)


def tw(s, size, mono=False):
    """The width a string will take, estimated: for placing things, not for drawing."""
    return len(str(s)) * size * (MONO_EM if mono else SANS_EM)


def wrap(s, width, size, mono=False):
    """Greedy word wrap to `width` pixels by the estimate above."""
    lines, cur = [], ""
    for word in str(s).split():
        trial = word if not cur else cur + " " + word
        if cur and tw(trial, size, mono) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def footer_lines(lines, width):
    """The footer's lines as they will be drawn: each wrapped to the canvas width less its 24 px margins. A figure
    that sizes its canvas to its content asks this first, so that it leaves room for every line."""
    out = []
    for ln in lines:
        out.extend(wrap(ln, width - 48, 10) or [""])
    return out


def text_box(x, y, s, size, anchor="start", mono=False):
    """(left, top, right, bottom) a text will take, estimated as everywhere in this kit (for layout and for the
    layout lint, never for drawing): the baseline is y, the ascent 0.8 em and the descent 0.2 em."""
    w = tw(s, size, mono)
    left = x - w if anchor == "end" else x - w / 2.0 if anchor == "middle" else x
    return (left, y - 0.8 * size, left + w, y + 0.2 * size)


def mix(a, b, t):
    """Blend two #rrggbb colours; t = 0 is a, t = 1 is b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(ca, cb))


def with_commas(v):
    return "{:,}".format(int(v))


class Lin:
    """A linear scale from [lo, hi] to [a, b] pixels (b may be less than a)."""

    def __init__(self, lo, hi, a, b):
        if hi == lo:
            hi = lo + 1.0
        self.lo, self.hi, self.a, self.b = lo, hi, a, b

    def __call__(self, v):
        return self.a + (v - self.lo) / (self.hi - self.lo) * (self.b - self.a)


def nice_ticks(lo, hi, want=5):
    """Round tick values spanning [lo, hi]: 1, 2 or 5 times a power of ten."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / float(max(want, 1))
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        step = m * mag
        if raw <= step * 1.0000001:
            break
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + step * 1e-9:
        out.append(round(v, 10))
        v += step
    return out


# ---------------------------------------------------------------- calendar
# datetime.date arithmetic only: it never reads the clock, and the month names
# come from the table below rather than strftime, which follows the locale.
def day_number(iso):
    """'2026-10-19' -> the proleptic Gregorian ordinal (0001-01-01 is 1, a Monday)."""
    y, m, d = (int(x) for x in iso.split("-"))
    return datetime.date(y, m, d).toordinal()


def day_iso(num):
    """The inverse of day_number."""
    return datetime.date.fromordinal(num).isoformat()


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
          "Nov", "Dec")


def day_short(iso):
    """'2026-10-19' -> '19 Oct'."""
    return "%d %s" % (int(iso[8:10]), MONTHS[int(iso[5:7]) - 1])


def week_ticks(d0, d1):
    """Day numbers of the Mondays from d0 to d1 inclusive (ordinal 1 is a Monday)."""
    first = d0 + ((1 - d0) % 7)
    return list(range(first, d1 + 1, 7))


# ------------------------------------------------------------------ canvas
class Plot:
    """One SVG document, drawn in one theme."""

    def __init__(self, theme, w, h, title, subtitle, label):
        self.theme, self.T = theme, THEMES[theme]
        self.w, self.h = w, h
        self.parts = []
        self.label = label
        T = self.T
        self.parts.append('<rect width="%d" height="%d" fill="%s"/>' % (w, h, T["bg"]))
        self.text(24, 30, title, size=17, weight="600")
        y = 52
        for line in wrap(subtitle, w - 48, 12.5):
            self.text(24, y, line, size=12.5, fill=T["muted"])
            y += 17
        self.top = y - 17 + 14          # first y below the subtitle

    # -- primitives
    def rect(self, x, y, w, h, fill, opacity=None, stroke=None, sw=1, rx=None):
        s = '<rect x="%s" y="%s" width="%s" height="%s" fill="%s"' % (n(x), n(y), n(w), n(h), fill)
        if opacity is not None and opacity != 1:
            s += ' opacity="%s"' % opacity
        if stroke:
            s += ' stroke="%s" stroke-width="%s"' % (stroke, sw)
        if rx:
            s += ' rx="%s"' % rx
        self.parts.append(s + "/>")

    def line(self, x1, y1, x2, y2, stroke, sw=1, dash=None, opacity=None):
        s = '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"' % (
            n(x1), n(y1), n(x2), n(y2), stroke, sw)
        if dash:
            s += ' stroke-dasharray="%s"' % dash
        if opacity is not None:
            s += ' opacity="%s"' % opacity
        self.parts.append(s + "/>")

    def path(self, pts, stroke, sw=2, fill="none", dash=None, opacity=None, close=False):
        d = " ".join("%s%s,%s" % ("M" if i == 0 else "L", n(x), n(y)) for i, (x, y) in enumerate(pts))
        if close:
            d += " Z"
        s = '<path d="%s" fill="%s" stroke="%s" stroke-width="%s" stroke-linejoin="round"' % (
            d, fill, stroke, sw)
        if fill != "none" and stroke == "none":
            s = '<path d="%s" fill="%s" stroke="none"' % (d, fill)
        if dash:
            s += ' stroke-dasharray="%s"' % dash
        if opacity is not None:
            s += ' opacity="%s"' % opacity
        self.parts.append(s + "/>")

    def polygon(self, pts, fill, opacity=None):
        s = '<polygon points="%s" fill="%s"' % (" ".join("%s,%s" % (n(x), n(y)) for x, y in pts), fill)
        if opacity is not None:
            s += ' opacity="%s"' % opacity
        self.parts.append(s + "/>")

    def circle(self, cx, cy, r, fill, stroke=None, sw=1, opacity=None):
        s = '<circle cx="%s" cy="%s" r="%s" fill="%s"' % (n(cx), n(cy), n(r), fill)
        if stroke:
            s += ' stroke="%s" stroke-width="%s"' % (stroke, sw)
        if opacity is not None:
            s += ' opacity="%s"' % opacity
        self.parts.append(s + "/>")

    def text(self, x, y, s, size=11, fill=None, anchor="start", weight=None, mono=False,
             rotate=None, opacity=None):
        fill = fill or self.T["fg"]
        a = '<text x="%s" y="%s" font-family="%s" font-size="%s" fill="%s"' % (
            n(x), n(y), MONO if mono else FONT, size, fill)
        if weight:
            a += ' font-weight="%s"' % weight
        if anchor != "start":
            a += ' text-anchor="%s"' % anchor
        if rotate is not None:
            a += ' transform="rotate(%s %s %s)"' % (rotate, n(x), n(y))
        if opacity is not None:
            a += ' opacity="%s"' % opacity
        self.parts.append("%s>%s</text>" % (a, esc(s)))

    # -- composed
    def panel(self, x0, y0, x1, y1):
        self.rect(x0, y0, x1 - x0, y1 - y0, self.T["panel"])

    def legend(self, items, x, y, maxw, size=11, swatch=14, gap=18, line=False):
        """items: [(colour, label)] or [(colour, label, 'dash')]. Flows left to
        right and wraps at maxw. Returns the y below the last row."""
        cx, cy = x, y
        for it in items:
            colour, label = it[0], it[1]
            dash = len(it) > 2 and it[2] == "dash"
            wd = swatch + 6 + tw(label, size) + gap
            if cx > x and cx + wd - gap > x + maxw:
                cx, cy = x, cy + size + 9
            if line:
                self.line(cx, cy - 3.5, cx + swatch + 4, cy - 3.5, colour, 2.4,
                          dash="4 3" if dash else None)
            else:
                self.rect(cx, cy - size + 2, swatch, size - 1, colour, rx=2)
            self.text(cx + swatch + 6 + (4 if line else 0), cy, label, size=size)
            cx += wd + (4 if line else 0)
        return cy + 6

    def footer(self, lines, y=None):
        """Source lines, small and muted, at the bottom of the figure. A line longer than the canvas is
        wrapped, never clipped; the last line stays 8 px above the bottom edge."""
        lines = footer_lines(lines, self.w)
        y = (self.h - 8 - 13 * (len(lines) - 1)) if y is None else y
        for i, ln in enumerate(lines):
            self.text(24, y + 13 * i, ln, size=10, fill=self.T["muted"])

    def render(self):
        head = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
                'role="img" aria-label="%s">' % (self.w, self.h, self.w, self.h, esc(self.label)))
        return "\n".join([head, "<title>%s</title>" % esc(self.label)] + self.parts + ["</svg>"]) + "\n"


# --------------------------------------------------------------- axis helpers
def axis_y_lin(p, scale, x0, x1, ticks, fmt, grid=True, size=10.5):
    T = p.T
    for v in ticks:
        y = scale(v)
        if grid:
            p.line(x0, y, x1, y, T["grid"], 1)
        p.text(x0 - 7, y + 3.5, fmt(v), size=size, fill=T["muted"], anchor="end", mono=True)


def axis_y_log(p, scale, x0, x1, lo, hi, fmt, size=10.5):
    T = p.T
    for g in decades(lo, hi):
        y = scale(g)
        p.line(x0, y, x1, y, T["grid"], 1)
        p.text(x0 - 7, y + 3.5, fmt(g), size=size, fill=T["muted"], anchor="end", mono=True)


def axis_x_dates(p, scale, y0, y1, d0, d1, size=10, grid=True):
    """Monday ticks, labelled 'd Mon'; scale maps a day number to x."""
    T = p.T
    for d in week_ticks(d0, d1):
        x = scale(d)
        if grid:
            p.line(x, y0, x, y1, T["grid"], 1)
        p.text(x, y1 + 14, day_short(day_iso(d)), size=size, fill=T["muted"], anchor="middle", mono=True)


def kmg(v):
    """12345 -> '12.3k', 1.5e6 -> '1.5M', small numbers as they are."""
    a = abs(v)
    if a >= 1e12:
        return "%gT" % round(v / 1e12, 3)
    if a >= 1e9:
        return "%gG" % round(v / 1e9, 3)
    if a >= 1e6:
        return "%gM" % round(v / 1e6, 3)
    if a >= 1e3:
        return "%gk" % round(v / 1e3, 3)
    return "%g" % round(v, 6)


def write_text(path, text):
    """LF, final newline already in `text`; whatever the platform."""
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
