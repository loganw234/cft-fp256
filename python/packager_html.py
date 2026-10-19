# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""packager_html: STATUS.md as one HTML page, for a reader with a browser and no Markdown viewer.

It renders only the Markdown that python/packager_status.py writes and that the README's own summary and tables
bring with them: headings, paragraphs, block quotations (holding tables, bullets and paragraphs of their own),
pipe tables, bullet lists, a picture on a line of its own, and inline code, bold, links and <sub>. It is not a
Markdown library and does not pretend to be: a construct it does not know is shown as the text it is, so nothing is
dropped, and the check below says when what it shows is not what was written.

TWO CHECKS, because a renderer is the kind of code that is wrong quietly.
  1. The page is a PURE FUNCTION of STATUS.md: no clock, no environment, no file but the text. `--verify`
     renders STATUS.md again and requires the archive's STATUS.html to be those bytes (`html-mismatch`), so the page
     cannot be edited, or made by a different renderer, without being caught.
  2. The page SAYS WHAT THE MARKDOWN SAYS: the words a reader would see in the browser (the text of the body, not
     the style, and a picture has none) are compared, in order, with the words of the Markdown once its syntax is
     taken off by a second, separate and much simpler pass (`html-text`). The tags must balance (`html-malformed`)
     and every href and src must name a file the archive holds (`html-link`).
Both are planted in python/packager_check.py.
"""
import html
import html.parser
import re

VOID = {"meta", "img", "br", "hr", "link", "input"}
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
CODE = re.compile(r"`([^`]+)`")
PICTURE = re.compile(r"!\[(.*)\]\(([^)\s]+)\)")

CSS = """
:root { color-scheme: light dark; --fg: #1f2328; --bg: #ffffff; --muted: #656d76; --line: #d0d7de; --pale: #f6f8fa; --link: #0969da; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --bg: #0d1117; --muted: #8b949e; --line: #30363d; --pale: #161b22; --link: #58a6ff; } }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
main { max-width: 56rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1, h2, h3, h4 { line-height: 1.25; margin: 2rem 0 0.75rem; }
h2 { border-bottom: 1px solid var(--line); padding-bottom: 0.3rem; }
a { color: var(--link); }
code { font: 0.9em ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; background: var(--pale); padding: 0.1em 0.3em; border-radius: 4px; }
blockquote { margin: 1rem 0; padding: 0.25rem 1rem; border-left: 4px solid var(--line); color: var(--muted); overflow-x: auto; }
blockquote p, blockquote li { color: var(--fg); }
table { border-collapse: collapse; margin: 1rem 0; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--line); padding: 0.35rem 0.7rem; vertical-align: top; text-align: left; }
th { background: var(--pale); }
p.fig { margin: 1rem 0 0.5rem; }
img { max-width: 100%; height: auto; border: 1px solid var(--line); }
"""


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain(s):
    """Inline markup outside code spans: <sub> kept, the rest escaped, then links and bold."""
    s = s.replace("<sub>", "\x01").replace("</sub>", "\x02")
    s = esc(s)
    s = s.replace("\x01", "<sub>").replace("\x02", "</sub>")
    s = LINK.sub(lambda m: '<a href="%s">%s</a>' % (m.group(2).replace('"', "&quot;"), m.group(1)), s)
    return BOLD.sub(r"<strong>\1</strong>", s)


def inline(s):
    out, pos = [], 0
    for m in CODE.finditer(s):
        out.append(plain(s[pos:m.start()]))
        out.append("<code>%s</code>" % esc(m.group(1)))
        pos = m.end()
    out.append(plain(s[pos:]))
    return "".join(out)


def cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def table(lines):
    head = cells(lines[0])
    body = [cells(r) for r in lines[2:]]
    out = ["<table>", "<thead><tr>%s</tr></thead>" % "".join("<th>%s</th>" % inline(c) for c in head), "<tbody>"]
    for r in body:
        out.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r))
    out += ["</tbody>", "</table>"]
    return "\n".join(out)


def starts_block(ln):
    return (not ln.strip() or ln.startswith((">", "|", "- ")) or re.match(r"#{1,6} ", ln) is not None
            or PICTURE.fullmatch(ln.strip()) is not None)


def blocks(lines):
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        h = re.match(r"(#{1,6}) (.*)", ln)
        if h:
            n = len(h.group(1))
            out.append("<h%d>%s</h%d>" % (n, inline(h.group(2)), n))
            i += 1
        elif ln.startswith(">"):
            inner = []
            while i < len(lines) and lines[i].startswith(">"):
                inner.append(lines[i][2:] if lines[i].startswith("> ") else lines[i][1:])
                i += 1
            out.append("<blockquote>\n%s\n</blockquote>" % "\n".join(blocks(inner)))
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(table(rows))
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append("<li>%s</li>" % inline(lines[i][2:]))
                i += 1
            out.append("<ul>\n%s\n</ul>" % "\n".join(items))
        elif PICTURE.fullmatch(ln.strip()):
            m = PICTURE.fullmatch(ln.strip())
            out.append('<p class="fig"><img src="%s" alt="%s"></p>' % (
                m.group(2).replace('"', "&quot;"), html.escape(m.group(1), quote=True)))
            i += 1
        else:
            para = [ln.strip()]
            i += 1
            while i < len(lines) and not starts_block(lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % inline(" ".join(para)))
    return out


def render(md):
    """The page for this Markdown: a pure function of the text."""
    lines = md.split("\n")
    first = next((ln for ln in lines if ln.startswith("# ")), "# status")
    title = re.sub(r"<[^>]+>", "", inline(first[2:]))
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>%s</title>\n"
            "<style>%s</style>\n</head>\n<body>\n<main>\n%s\n</main>\n</body>\n</html>\n" % (
                title, CSS, "\n".join(blocks(lines))))


# ------------------------------------------------------------------------------------------------ the check
def md_words(md):
    """The words of the Markdown with its syntax taken off, by a pass that shares nothing with the renderer."""
    out = []
    for ln in md.split("\n"):
        ln = re.sub(r"^(?:>\s?)+", "", ln)
        s = ln.strip()
        if re.fullmatch(r"\|[\s|:-]+\|", s) or PICTURE.fullmatch(s):
            continue
        ln = re.sub(r"^#{1,6} ", "", ln)
        ln = re.sub(r"^- ", "", ln)
        ln = ln.replace("|", " ")
        ln = LINK.sub(r"\1", ln)
        ln = ln.replace("`", "").replace("**", "")
        ln = re.sub(r"</?sub>", "", ln)
        out += ln.split()
    return out


BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "td", "th", "tr", "table", "thead", "tbody",
         "blockquote", "main", "body", "div", "br"}


class _Page(html.parser.HTMLParser):
    """What a browser would show: the text nodes of the body joined as they stand (so `<code>x</code>,` is `x,`, with no
    space a tag boundary did not put there), with a break at each block-level tag."""

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.stack, self.buf, self.links, self.errors = [], [], [], []
        self.in_body = False
        self.skip = 0

    @property
    def words(self):
        return "".join(self.buf).split()

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)
        if tag == "body":
            self.in_body = True
        if tag in ("style", "script"):
            self.skip += 1
        if self.in_body and tag in BLOCK:
            self.buf.append(" ")
        for k, v in attrs:
            if k in ("href", "src") and v is not None:
                self.links.append(v)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append("</%s> closes %s" % (tag, "<%s>" % self.stack[-1] if self.stack else "nothing"))
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()
        if tag in ("style", "script"):
            self.skip -= 1
        if self.in_body and tag in BLOCK:
            self.buf.append(" ")
        if tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and not self.skip:
            self.buf.append(data)


def check(md, page, held=None):
    """[(code, message)]: unbalanced tags, text that is not the Markdown's, links to files not held (if `held` is given)."""
    p = _Page()
    p.feed(page)
    p.close()
    out = []
    if p.errors or p.stack:
        out.append(("html-malformed", "; ".join(p.errors[:2]) or "unclosed: %s" % ", ".join("<%s>" % t for t in p.stack[:3])))
    want = md_words(md)
    if p.words != want:
        n = next((k for k in range(min(len(p.words), len(want))) if p.words[k] != want[k]), min(len(p.words), len(want)))
        out.append(("html-text", "the page shows %d words and the Markdown has %d; they first differ at word %d (page %r, "
                    "Markdown %r)" % (len(p.words), len(want), n, " ".join(p.words[n:n + 3]), " ".join(want[n:n + 3]))))
    if held is not None:
        for target in p.links:
            t = target.split("#", 1)[0]
            if t and not t.startswith(("http://", "https://", "mailto:")) and t not in held:
                out.append(("html-link", "the page names %s, which the archive does not hold" % t))
                break
    return out
