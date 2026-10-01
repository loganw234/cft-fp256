# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The language's text: a lexer, and a parser to statements and
expressions that carry their source lines.

docs/LANGUAGE.md, "The text", is the grammar this implements. The
parser knows nothing about meaning - which names exist, what is a
constant, what a statement may say - and the checker (check.py) is
where every refusal but `character`, `syntax`, `power`, `not-equal`,
`chained-comparison`, nesting's `too-deep` and the literal's own
`constant-range` is made.
"""

import re
from fractions import Fraction

from .. import chars
from .constants import LIMIT_LOG2
from .refusals import Refusal

# ---- the text's characters (2026-10-01) -------------------------------
#
# One rule for the round's two text forms: a .cftl source is held to the
# rule a .cfta source is (docs/PROGRAMS.md, "The text form's
# characters"; asm.py's lines()), in the same words, so that no reader -
# this lexer, cft-asm, an LF-only tool, str.splitlines() - sees a line
# the others do not. Before it a lone CR ended a line here and in no
# LF-only reader, so `; rounding: the default<CR>round rdn` was a comment
# to grep and rdn to the parser; and a form feed, NEL or U+2028 in a
# comment hid from the parser a line splitlines() showed (verifier-VL1):
#
# * a source is UTF-8;
# * a line ends at a line feed, and a carriage return immediately before
#   it is part of that end - so a CRLF file reads as its LF twin;
# * every other line boundary str.splitlines() knows, and NUL and
#   Ctrl-Z, is refused by name anywhere in a source, comments included;
# * outside a comment - before a line's first `;` - a line holds only
#   printable ASCII, spaces and tabs. A byte-order mark is no exception:
#   it is a character outside a comment like any other.
#
# The source is checked whole before any of it is lexed, UTF-8 first and
# then the characters line by line, left to right, so of several faults
# the first is named - the one asm.py names.

LINE_BREAKS = {
    0x0d: "a carriage return (0x0d) that is not part of a CRLF line end",
    0x0b: "a vertical tab (0x0b)",
    0x0c: "a form feed (0x0c)",
    0x1c: "a file separator (0x1c)",
    0x1d: "a group separator (0x1d)",
    0x1e: "a record separator (0x1e)",
    0x85: "a next line (U+0085)",
    0x2028: "a line separator (U+2028)",
    0x2029: "a paragraph separator (U+2029)",
}
NEVER = {0x00: "a NUL (0x00)", 0x1a: "a Ctrl-Z (0x1a)"}

_ANYWHERE = re.compile("[" + "".join(re.escape(chr(c)) for c in
                                     sorted({**LINE_BREAKS, **NEVER})) + "]")
_NOT_CODE = re.compile("[^\t\x20-\x7e]")


def char_name(cp):
    """A character as a refusal names it - asm.py's _char_name."""
    if cp in LINE_BREAKS:
        return LINE_BREAKS[cp]
    if cp in NEVER:
        return NEVER[cp]
    if cp < 0x20 or cp == 0x7F:
        return f"the control character 0x{cp:02x}"
    return f"the character U+{cp:04X}"


def _character(sentence, line):
    return Refusal("character", sentence, line)


def source_text(text):
    """A source as the lexer reads it, held whole to the character rule:
    `text` is a str, or a file's bytes (decoded as UTF-8, strictly).
    Returns the text with each CR LF as LF, or refuses `character`,
    naming the character and its line. A caller with a FILE should hand
    over its bytes: a text-mode read turns a lone CR into a line end
    before the rule could see it."""
    if isinstance(text, (bytes, bytearray, memoryview)):
        data = bytes(text)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _character(f"the source is not UTF-8 (byte "
                             f"0x{data[exc.start]:02x})",
                             data.count(b"\n", 0, exc.start) + 1) from None
    elif isinstance(text, str):
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _character(f"the source is not UTF-8 (a lone surrogate, "
                             f"U+{ord(text[exc.start]):04X})",
                             text.count("\n", 0, exc.start) + 1) from None
    else:
        raise TypeError(f"a source is a str or a file's bytes, not "
                        f"{type(text).__name__}")
    segs = text.split("\n")
    ended = text.endswith("\n")
    if ended:
        segs.pop()                # a final LF ends a line; it starts none
    out = []
    for i, seg in enumerate(segs, 1):
        if (ended or i < len(segs)) and seg.endswith("\r"):
            seg = seg[:-1]        # the CR of a CR LF line end
        bad = _ANYWHERE.search(seg)
        semi = seg.find(";")
        code_bad = _NOT_CODE.search(seg if semi < 0 else seg[:semi])
        if code_bad is not None and (bad is None
                                     or code_bad.start() < bad.start()):
            raise _character(f"{char_name(ord(code_bad.group()))} outside a "
                             f"comment, where a line holds only printable "
                             f"ASCII, spaces and tabs", i)
        if bad is not None:
            cp = ord(bad.group())
            if cp in NEVER:
                raise _character(f"{char_name(cp)}: a source holds none "
                                 f"anywhere, in a comment or out of one", i)
            raise _character(f"{char_name(cp)}: a line ends at a line feed, "
                             f"or a carriage return and a line feed, and at "
                             f"no other character, so a source holds none of "
                             f"the others anywhere", i)
        out.append(seg)
    return "\n".join(out) + ("\n" if ended else "")

# Words that start or shape a statement. Lexed as names, recognised by
# the parser where a statement starts, and reserved: none can name a
# value (check.py's RESERVED).
KEYWORDS = frozenset({
    "system", "format", "round", "state", "cyclic", "const", "param",
    "lane", "let", "next", "step", "for", "in", "expansion", "end",
    "tangent",
})
# `integrator` starts a block only in the library's own template text.
TEMPLATE_KEYWORDS = frozenset({"integrator"})

CMP_OPS = ("<", "<=", ">", ">=", "==")

# How deep ( and [ may nest. The parser and the checker recurse once or a
# few times a level, and Python's default recursion limit is a thousand
# frames - a limit this package keeps rather than raises, since on the
# Pythons the project supports below 3.11 a deeper Python recursion is a
# deeper C stack. A left-deep chain (a + b + c ...) and a run of unary
# minuses nest no frames at all: they are walked in loops.
MAX_NESTING = 100

_LOWER = "abcdefghijklmnopqrstuvwxyz"
_NAME0 = frozenset(_LOWER + _LOWER.upper() + "_")
_DIGITS = frozenset("0123456789")
_NAMEC = _NAME0 | _DIGITS
_HEX = frozenset("0123456789abcdefABCDEF")
_TWO_CHAR = ("**", "<=", ">=", "==", "!=", "..")
_ONE_CHAR = frozenset("+-*/()[],=<>^")


class Tok:
    __slots__ = ("kind", "text", "value", "line")

    def __init__(self, kind, text, line, value=None):
        self.kind = kind          # name, num, op, ddt, nl, eof
        self.text = text
        self.value = value
        self.line = line

    def __repr__(self):
        return f"Tok({self.kind}, {self.text!r}, {self.line})"


def _syntax(sentence, line):
    return Refusal("syntax", sentence, line)


def _number(text, i, line):
    """(Tok, next index) for the number at text[i]."""
    n = len(text)
    start = i
    if text.startswith(("0x", "0X"), i):
        i += 2
        j = i
        while i < n and text[i] in _HEX:
            i += 1
        intpart = text[j:i]
        frac = ""
        if i < n and text[i] == "." and not text.startswith("..", i):
            i += 1
            j = i
            while i < n and text[i] in _HEX:
                i += 1
            frac = text[j:i]
        if not intpart and not frac:
            raise _syntax(f"{text[start:i]!r} is not a hexadecimal "
                          f"significand", line)
        if i >= n or text[i] not in "pP":
            raise _syntax(
                f"{text[start:i]} has no binary exponent: a hexadecimal "
                f"significand needs one, as 5.12.3's grammar does "
                f"({text[start:i]}p+0); an encoding is not a literal",
                line)
        i += 1
        esign = 1
        if i < n and text[i] in "+-":
            esign = -1 if text[i] == "-" else 1
            i += 1
        j = i
        while i < n and text[i] in _DIGITS:
            i += 1
        if j == i:
            raise _syntax(f"{text[start:i]!r}: the binary exponent needs "
                          f"its digits", line)
        exp = esign * chars._int_from_digits(text[j:i])
        m = int(intpart + frac or "0", 16)
        e = exp - 4 * len(frac)
        if m == 0:
            value = Fraction(0)
        else:
            lead = e + m.bit_length() - 1
            if not -LIMIT_LOG2 <= lead <= LIMIT_LOG2:
                raise Refusal(
                    "constant-range",
                    f"{text[start:i]} lies far outside every format: a "
                    f"constant must lie within 2^+-{LIMIT_LOG2} to be "
                    f"evaluated", line)
            value = Fraction(m * 2 ** e) if e >= 0 else Fraction(m, 2 ** -e)
    else:
        j = i
        while i < n and text[i] in _DIGITS:
            i += 1
        intpart = text[j:i]
        frac = ""
        if i < n and text[i] == "." and not text.startswith("..", i):
            i += 1
            j = i
            while i < n and text[i] in _DIGITS:
                i += 1
            frac = text[j:i]
        exp = 0
        if i < n and text[i] in "eE":
            k = i + 1
            if k < n and text[k] in "+-":
                k += 1
            if k < n and text[k] in _DIGITS:
                esign = -1 if text[i + 1] == "-" else 1
                i = k
                j = i
                while i < n and text[i] in _DIGITS:
                    i += 1
                exp = esign * chars._int_from_digits(text[j:i])
        is_integer = text[start:i].isdigit()
        if is_integer and len(intpart) > 1 and intpart[0] == "0":
            # 05 is octal in C; 05.5 and 007e-3 are decimals there and
            # here, read as chars.lex_decimal reads them
            raise _syntax(f"{text[start:i]}: an integer does not start "
                          f"with 0 followed by another digit (in C that "
                          f"is octal)", line)
        digits = chars._int_from_digits(intpart + frac)
        k10 = exp - len(frac)
        if digits == 0:
            value = Fraction(0)
        else:
            lo, hi = chars._log2_10_bounds(k10)
            b = digits.bit_length()
            if b + hi < -LIMIT_LOG2 or b - 2 + lo > LIMIT_LOG2:
                raise Refusal(
                    "constant-range",
                    f"{text[start:i]} lies far outside every format: a "
                    f"constant must lie within 2^+-{LIMIT_LOG2} to be "
                    f"evaluated", line)
            value = (Fraction(digits * 10 ** k10) if k10 >= 0
                     else Fraction(digits, 10 ** -k10))
    if i < n and text[i] in _NAMEC:
        raise _syntax(f"{text[start:i + 1]!r}: a number runs straight "
                      f"into a name; write the product with *", line)
    return Tok("num", text[start:i], line, value), i


def lex(text):
    """The tokens of a source - a str, or a file's bytes - once the whole
    of it is held to the character rule (source_text). A newline ends a
    statement unless it is inside ( ) or [ ], and `d/dt` is one token
    where a statement starts."""
    text = source_text(text)
    toks = []
    i, n, line, depth = 0, len(text), 1, 0

    def at_start():
        return depth == 0 and (not toks or toks[-1].kind == "nl")

    while i < n:
        c = text[i]
        if c == "\n":
            # the one line end left: source_text made each CR LF an LF
            # and refused every other
            if depth == 0 and toks and toks[-1].kind != "nl":
                toks.append(Tok("nl", "\n", line))
            line += 1
            i += 1
            continue
        if c in " \t":
            i += 1
            continue
        if c == ";":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if (c == "d" and at_start() and text.startswith("d/dt", i)
                and (i + 4 >= n or text[i + 4] not in _NAMEC)):
            toks.append(Tok("ddt", "d/dt", line))
            i += 4
            continue
        if c in _NAME0:
            j = i
            while i < n and text[i] in _NAMEC:
                i += 1
            while (i + 1 < n and text[i] == "." and text[i + 1] in _NAME0):
                i += 1
                while i < n and text[i] in _NAMEC:
                    i += 1
            toks.append(Tok("name", text[j:i], line))
            continue
        if c in _DIGITS or (c == "." and i + 1 < n and text[i + 1] in _DIGITS):
            tok, i = _number(text, i, line)
            toks.append(tok)
            continue
        two = text[i:i + 2]
        if two in _TWO_CHAR:
            toks.append(Tok("op", two, line))
            i += 2
            continue
        if c in _ONE_CHAR:
            if c in "([":
                depth += 1
                if depth > MAX_NESTING:
                    raise Refusal("too-deep", f"parentheses and brackets nest "
                                  f"more than {MAX_NESTING} deep here; name "
                                  f"a part of the expression with a let",
                                  line)
            elif c in ")]":
                depth = max(0, depth - 1)
            toks.append(Tok("op", c, line))
            i += 1
            continue
        raise _syntax(f"{c!r} is not a character the language uses", line)
    if toks and toks[-1].kind != "nl":
        toks.append(Tok("nl", "\n", line))
    toks.append(Tok("eof", "", line))
    return toks


# ---- the tree ---------------------------------------------------------

class Num:
    __slots__ = ("value", "text", "line")

    def __init__(self, value, text, line):
        self.value, self.text, self.line = value, text, line


class Name:
    __slots__ = ("name", "line")

    def __init__(self, name, line):
        self.name, self.line = name, line


class Index:
    __slots__ = ("name", "index", "line")

    def __init__(self, name, index, line):
        self.name, self.index, self.line = name, index, line


class Call:
    __slots__ = ("name", "args", "line")

    def __init__(self, name, args, line):
        self.name, self.args, self.line = name, args, line


class Neg:
    __slots__ = ("arg", "line")

    def __init__(self, arg, line):
        self.arg, self.line = arg, line


class Bin:
    __slots__ = ("op", "left", "right", "line")

    def __init__(self, op, left, right, line):
        self.op, self.left, self.right, self.line = op, left, right, line


class Cmp:
    __slots__ = ("op", "left", "right", "line")

    def __init__(self, op, left, right, line):
        self.op, self.left, self.right, self.line = op, left, right, line


class Target:
    """An equation's or a let's left side: a name and an optional
    index expression."""
    __slots__ = ("name", "index", "line")

    def __init__(self, name, index, line):
        self.name, self.index, self.line = name, index, line


class Range:
    __slots__ = ("var", "lo", "hi", "line")

    def __init__(self, var, lo, hi, line):
        self.var, self.lo, self.hi, self.line = var, lo, hi, line


class Stmt:
    """One statement. `kind` is the keyword (`d/dt` for a derivative);
    the other fields are the kind's own:

      system, format, round   word
      state                   items: [(name, length Num or None, cyclic, line)]
      tangent                 items: [(name, line)]
      const, param            items: [(name, expr, line)]
      lane                    items: [(name, expr or None, line)]
      let                     target, expr, range
      d/dt, next              target, expr, range
      step                    word (the integrator), items: [(key, value, line)]
                              - value an expr for h, a [(name, line)] for q and p
      expansion, integrator   body: [Stmt], word (integrator's name)
    """
    __slots__ = ("kind", "line", "word", "items", "target", "expr",
                 "range", "body", "end_line")

    def __init__(self, kind, line, **kw):
        self.kind = kind
        self.line = line
        self.word = kw.get("word")
        self.items = kw.get("items")
        self.target = kw.get("target")
        self.expr = kw.get("expr")
        self.range = kw.get("range")
        self.body = kw.get("body")
        self.end_line = kw.get("end_line")


# ---- the parser -------------------------------------------------------

class Parser:
    def __init__(self, toks, templates=False):
        self.toks = toks
        self.i = 0
        self.templates = templates

    # -- tokens ---------------------------------------------------------

    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def take(self):
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def at_op(self, text):
        t = self.peek()
        return t.kind == "op" and t.text == text

    def expect_op(self, text, what):
        t = self.take()
        if t.kind != "op" or t.text != text:
            raise _syntax(f"expected {text} {what}, found "
                          f"{self._show(t)}", t.line)
        return t

    def expect_name(self, what):
        t = self.take()
        if t.kind != "name":
            raise _syntax(f"expected {what}, found {self._show(t)}", t.line)
        return t

    def end_statement(self, what):
        t = self.peek()
        if t.kind not in ("nl", "eof"):
            raise _syntax(f"{what} ends here; found {self._show(t)}",
                          t.line)
        self.take()

    @staticmethod
    def _show(t):
        if t.kind == "nl":
            return "the end of the line"
        if t.kind == "eof":
            return "the end of the text"
        return repr(t.text)

    # -- the file -------------------------------------------------------

    def parse_file(self):
        stmts = []
        while True:
            t = self.peek()
            if t.kind == "eof":
                return stmts
            if t.kind == "nl":
                self.take()
                continue
            stmts.append(self.statement(top=True))

    def statement(self, top, in_block=False):
        t = self.peek()
        if t.kind == "ddt":
            if in_block:
                raise _syntax("an expansion block holds let and next "
                              "lines only", t.line)
            return self.equation("d/dt")
        if t.kind != "name":
            raise _syntax(f"a statement starts with a keyword; found "
                          f"{self._show(t)}", t.line)
        kw = t.text
        if in_block and kw not in ("let", "next"):
            raise _syntax(f"an expansion block holds let and next lines "
                          f"only; found {kw!r}", t.line)
        if kw in ("system", "format", "round"):
            self.take()
            word = self.expect_name(f"a name after {kw}")
            self.end_statement(f"{kw} {word.text}")
            return Stmt(kw, t.line, word=word.text)
        if kw == "state":
            return self.state()
        if kw == "tangent":
            return self.tangent()
        if kw in ("const", "param"):
            return self.const_or_param(kw)
        if kw == "lane":
            return self.lane()
        if kw == "let":
            return self.let()
        if kw == "next":
            return self.equation("next")
        if kw == "step":
            return self.step()
        if kw == "expansion":
            if not top:
                raise _syntax("an expansion block is not nested in "
                              "another", t.line)
            return self.expansion()
        if kw == "integrator" and self.templates and top:
            return self.integrator()
        if kw == "integrator":
            raise _syntax("integrator blocks are the library's own; v1 "
                          "steps with rk4, euler, stormer-verlet or map",
                          t.line)
        if kw == "end":
            raise _syntax("end closes an expansion block, and none is "
                          "open", t.line)
        raise _syntax(f"{kw!r} does not start a statement: system, "
                      f"format, round, state, tangent, const, param, lane "
                      f"param, let, d/dt, next, step or expansion", t.line)

    def state(self):
        t = self.take()
        items = []
        while True:
            name = self.expect_name("a state name")
            length = None
            cyclic = False
            if self.at_op("["):
                self.take()
                ln = self.take()
                if ln.kind != "num":
                    raise _syntax(f"an array's length is a number; found "
                                  f"{self._show(ln)}", ln.line)
                length = Num(ln.value, ln.text, ln.line)
                self.expect_op("]", "after an array's length")
                if self.peek().kind == "name" and self.peek().text == "cyclic":
                    self.take()
                    cyclic = True
            items.append((name.text, length, cyclic, name.line))
            if not self.at_op(","):
                break
            self.take()
        self.end_statement("a state declaration")
        return Stmt("state", t.line, items=items)

    def tangent(self):
        """tangent NAME {, NAME}: the tangent vectors, each over the
        whole state (docs/LANGUAGE.md, "The variational equations")."""
        t = self.take()
        items = []
        while True:
            name = self.expect_name("a tangent vector's name")
            items.append((name.text, name.line))
            if not self.at_op(","):
                break
            self.take()
        self.end_statement("a tangent declaration")
        return Stmt("tangent", t.line, items=items)

    def const_or_param(self, kw):
        t = self.take()
        items = []
        while True:
            name = self.expect_name(f"a {kw} name")
            if not self.at_op("="):
                raise _syntax(f"a {kw} has a value: {kw} {name.text} = ...",
                              name.line)
            self.take()
            items.append((name.text, self.expr(), name.line))
            if not self.at_op(","):
                break
            self.take()
        self.end_statement(f"a {kw} declaration")
        return Stmt(kw, t.line, items=items)

    def lane(self):
        t = self.take()
        p = self.peek()
        if p.kind != "name" or p.text != "param":
            raise _syntax("lane begins a lane parameter: lane param NAME",
                          p.line)
        self.take()
        items = []
        while True:
            name = self.expect_name("a lane param name")
            expr = None
            if self.at_op("="):
                self.take()
                expr = self.expr()
            items.append((name.text, expr, name.line))
            if not self.at_op(","):
                break
            self.take()
        self.end_statement("a lane param declaration")
        return Stmt("lane", t.line, items=items)

    def target(self):
        name = self.expect_name("a name")
        index = None
        if self.at_op("["):
            self.take()
            index = self.sum()
            self.expect_op("]", "after an index")
        return Target(name.text, index, name.line)

    def range_clause(self):
        if not (self.peek().kind == "name" and self.peek().text == "for"):
            return None
        t = self.take()
        var = self.expect_name("an index variable after for")
        word = self.take()
        if word.kind != "name" or word.text != "in":
            raise _syntax(f"expected in after for {var.text}, found "
                          f"{self._show(word)}", word.line)
        lo = self.sum()
        self.expect_op("..", "between a range's ends")
        hi = self.sum()
        return Range(var.text, lo, hi, t.line)

    def let(self):
        t = self.take()
        target = self.target()
        self.expect_op("=", "after a let's name")
        expr = self.expr()
        rng = self.range_clause()
        self.end_statement("a let")
        return Stmt("let", t.line, target=target, expr=expr, range=rng)

    def equation(self, kind):
        t = self.take()
        target = self.target()
        self.expect_op("=", f"after {kind} {target.name}")
        expr = self.expr()
        rng = self.range_clause()
        self.end_statement("an equation")
        return Stmt(kind, t.line, target=target, expr=expr, range=rng)

    def step(self):
        t = self.take()
        name = self.expect_name("an integrator after step")
        word = name.text
        while (self.at_op("-") and self.peek(1).kind == "name"):
            self.take()
            word += "-" + self.take().text
        items = []
        while self.at_op(","):
            self.take()
            key = self.expect_name("an option of the step")
            self.expect_op("=", f"after {key.text}")
            if key.text in ("q", "p"):
                self.expect_op("(", f"before {key.text}'s names")
                names = []
                while True:
                    nm = self.expect_name("a state name")
                    names.append((nm.text, nm.line))
                    if self.at_op(","):
                        self.take()
                        continue
                    break
                self.expect_op(")", f"after {key.text}'s names")
                items.append((key.text, names, key.line))
            else:
                items.append((key.text, self.expr(), key.line))
        self.end_statement("the step")
        return Stmt("step", t.line, word=word, items=items)

    def expansion(self):
        t = self.take()
        self.end_statement("expansion")
        body = []
        while True:
            p = self.peek()
            if p.kind == "eof":
                raise _syntax("the expansion block is never closed by end",
                              t.line)
            if p.kind == "nl":
                self.take()
                continue
            if p.kind == "name" and p.text == "end":
                self.take()
                self.end_statement("end")
                return Stmt("expansion", t.line, body=body, end_line=p.line)
            body.append(self.statement(top=False, in_block=True))

    def integrator(self):
        t = self.take()
        name = self.expect_name("the integrator's name")
        word = name.text
        while (self.at_op("-") and self.peek(1).kind == "name"):
            self.take()
            word += "-" + self.take().text
        self.end_statement("the integrator's name")
        body = []
        while True:
            p = self.peek()
            if p.kind == "eof":
                raise _syntax(f"integrator {word} is never closed by end",
                              t.line)
            if p.kind == "nl":
                self.take()
                continue
            if p.kind == "name" and p.text == "end":
                self.take()
                self.end_statement("end")
                return Stmt("integrator", t.line, word=word, body=body,
                            end_line=p.line)
            body.append(self.statement(top=False, in_block=True))

    # -- expressions ------------------------------------------------------

    def expr(self):
        left = self.sum()
        t = self.peek()
        if t.kind == "op" and t.text in CMP_OPS:
            self.take()
            right = self.sum()
            u = self.peek()
            if u.kind == "op" and u.text in CMP_OPS:
                raise Refusal(
                    "chained-comparison",
                    f"a {t.text} b {u.text} c compares a comparison's 1 "
                    f"or 0 with c; parenthesise the comparison you mean",
                    u.line)
            if u.kind == "op" and u.text == "!=":
                raise Refusal("not-equal", self._not_equal(), u.line)
            return Cmp(t.text, left, right, t.line)
        if t.kind == "op" and t.text == "!=":
            raise Refusal("not-equal", self._not_equal(), t.line)
        return left

    @staticmethod
    def _not_equal():
        return ("there is no not-equal operation; select(a == b, 0, 1) "
                "is 1 where a and b differ")

    def sum(self):
        left = self.term()
        while True:
            t = self.peek()
            if t.kind == "op" and t.text in ("+", "-"):
                self.take()
                left = Bin(t.text, left, self.term(), t.line)
                continue
            return left

    def term(self):
        left = self.unary()
        while True:
            t = self.peek()
            if t.kind == "op" and t.text in ("*", "/"):
                self.take()
                left = Bin(t.text, left, self.unary(), t.line)
                continue
            if t.kind == "op" and t.text in ("^", "**"):
                raise self._power(t)
            return left

    @staticmethod
    def _power(t):
        return Refusal("power", f"{t.text} is not an operator: write x * x "
                       f"for a square, and a longer product in the order "
                       f"you mean", t.line)

    def unary(self):
        negs = []
        while True:
            t = self.peek()
            if t.kind == "op" and t.text == "-":
                negs.append(self.take())
                continue
            if t.kind == "op" and t.text == "+":
                raise _syntax("a unary + is no operation; leave it out",
                              t.line)
            break
        p = self.primary()
        u = self.peek()
        if u.kind == "op" and u.text in ("^", "**"):
            raise self._power(u)
        for t in reversed(negs):
            p = Neg(p, t.line)
        return p

    def primary(self):
        t = self.take()
        if t.kind == "num":
            return Num(t.value, t.text, t.line)
        if t.kind == "name":
            if t.text in KEYWORDS:
                raise _syntax(f"{t.text} is a keyword; a value was expected "
                              f"here", t.line)
            if self.at_op("("):
                self.take()
                args = []
                if not self.at_op(")"):
                    while True:
                        args.append(self.expr())
                        if self.at_op(","):
                            self.take()
                            continue
                        break
                self.expect_op(")", f"to close {t.text}'s arguments")
                return Call(t.text, args, t.line)
            if self.at_op("["):
                self.take()
                index = self.sum()
                self.expect_op("]", "after an index")
                return Index(t.text, index, t.line)
            return Name(t.text, t.line)
        if t.kind == "op" and t.text == "(":
            e = self.expr()
            self.expect_op(")", "to close a parenthesis")
            return e
        raise _syntax(f"a value was expected; found {self._show(t)}", t.line)


def parse(text, templates=False):
    """[Stmt] for a source; refusals carry lines but no source name."""
    return Parser(lex(text), templates=templates).parse_file()
