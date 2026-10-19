# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""packager_png: the two questions python/project_packager.py asks of a PNG it has just had rendered.

    Is it the size it should be?   Is it not blank?

Nothing else. This is a reader, not an image library, and it is the standard library only (zlib and
struct), so the check runs wherever the packager does, with no Pillow or numpy to be present.

WHAT IT READS. The signature, then every chunk with its CRC (a flipped bit, a truncated file or bytes after
IEND are `png-corrupt`); IHDR (8-bit RGB or RGBA, not interlaced: anything else is `png-unsupported`, named,
because a decoder that guessed would answer a question about an image it had not read); the image data, which
must inflate to exactly height x (1 + width x bytes-per-pixel) bytes with every row's filter byte in 0..4.
Then it decodes the first BAND_ROWS rows exactly (all five filters) and counts what is in them.

"NOT BLANK" HERE MEANS: in that band of the top rows - the title and the first lines of the subtitle in every
figure of this project - at least MIN_INK of the pixels differ from the corner pixel, and at least MIN_COLOURS
distinct colours occur. Both thresholds come from a measurement, not a belief: on all 34 renders of the
project's 17 figures at 2x (rsvg-convert 2.58.4) the band held at least 5.03% non-background pixels and at least
471 distinct colours (text is anti-aliased), so the thresholds sit ten times and fourteen times below the least
of them, and a blank image (one colour, 0%) is nowhere near. WHAT IT DOES NOT PROVE: that the whole figure was
drawn. A render with its title and nothing below it passes. The completeness of a render is the converter's
business; the packager pins the bytes with a SHA-256 and shows that a second render gives the same bytes.

WHY ONLY A BAND. A pure-Python decode of the whole image took 111 s for those 34 files (3.3 s each: a PNG row
may be filtered against the row above it and the pixel to its left, so every row is a loop), and 10.7 s for the
band. A check that costs two minutes is a check that gets skipped.

`selftest()` is what python/project_packager.py --check runs: the decoder against the encoder below on every
filter, and each fault planted and required to come back under its own name.
"""
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
BAND_ROWS = 160
MIN_INK = 0.005
MIN_COLOURS = 32
BYTES_PER_PIXEL = {2: 3, 6: 4}


class PngError(Exception):
    """A structural fault, with the name the packager refuses under."""

    def __init__(self, code, message):
        Exception.__init__(self, "%s: %s" % (code, message))
        self.code = code
        self.message = message


def _crc(ctype, body):
    return zlib.crc32(ctype + body) & 0xFFFFFFFF


def parse(data):
    """The PNG's facts and its joined image data; raises PngError."""
    if data[:8] != SIGNATURE:
        raise PngError("png-corrupt", "no PNG signature")
    pos, ihdr, idat, ended, order = 8, None, [], False, []
    while pos < len(data):
        if ended:
            raise PngError("png-corrupt", "%d bytes follow IEND" % (len(data) - pos))
        if pos + 12 > len(data):
            raise PngError("png-corrupt", "the file ends inside a chunk header at byte %d" % pos)
        length, = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        end = pos + 8 + length
        if end + 4 > len(data):
            raise PngError("png-corrupt", "a %s chunk at byte %d runs past the end of the file" % (
                ctype.decode("latin-1"), pos))
        body = data[pos + 8:end]
        crc, = struct.unpack(">I", data[end:end + 4])
        if _crc(ctype, body) != crc:
            raise PngError("png-corrupt", "bad CRC in the %s chunk at byte %d" % (ctype.decode("latin-1"), pos))
        if not order and ctype != b"IHDR":
            raise PngError("png-corrupt", "the first chunk is %s, not IHDR" % ctype.decode("latin-1"))
        order.append(ctype)
        if ctype == b"IHDR":
            if len(body) != 13 or ihdr is not None:
                raise PngError("png-corrupt", "a malformed or repeated IHDR")
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            if idat and order[-2] != b"IDAT":
                raise PngError("png-corrupt", "IDAT chunks are not contiguous")
            idat.append(body)
        elif ctype == b"IEND":
            ended = True
        pos = end + 4
    if not ended:
        raise PngError("png-corrupt", "the file has no IEND")
    if not idat:
        raise PngError("png-corrupt", "the file has no image data")
    width, height, depth, colour, comp, filt, interlace = ihdr
    if width < 1 or height < 1:
        raise PngError("png-corrupt", "IHDR gives a %d x %d image" % (width, height))
    if depth != 8 or colour not in BYTES_PER_PIXEL or comp != 0 or filt != 0 or interlace != 0:
        raise PngError("png-unsupported", "bit depth %d, colour type %d, interlace %d: this reader holds 8-bit RGB "
                       "or RGBA, not interlaced" % (depth, colour, interlace))
    return {"width": width, "height": height, "colour_type": colour, "bpp": BYTES_PER_PIXEL[colour],
            "idat": b"".join(idat), "chunks": order}


def inflate(info):
    """The image data's filtered scanlines, checked to be exactly the length the header promises."""
    d = zlib.decompressobj()
    try:
        raw = d.decompress(info["idat"]) + d.flush()
    except zlib.error as e:
        raise PngError("png-corrupt", "the image data does not inflate (%s)" % e)
    if not d.eof:
        raise PngError("png-corrupt", "the image data ends before its zlib stream does")
    if d.unused_data:
        raise PngError("png-corrupt", "%d bytes follow the zlib stream" % len(d.unused_data))
    stride = info["width"] * info["bpp"]
    want = info["height"] * (stride + 1)
    if len(raw) != want:
        raise PngError("png-corrupt", "the image data is %d bytes where a %d x %d image needs %d" % (
            len(raw), info["width"], info["height"], want))
    bad = set(raw[0::stride + 1]) - {0, 1, 2, 3, 4}
    if bad:
        raise PngError("png-corrupt", "a scanline has filter type %s, which does not exist" % sorted(bad)[0])
    return raw


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def unfilter_rows(raw, width, bpp, nrows):
    """The first nrows scanlines, exactly unfiltered: a list of bytes, each width x bpp long."""
    stride = width * bpp
    rows = []
    prev = bytes(stride)
    pos = 0
    for _y in range(nrows):
        ft = raw[pos]
        row = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 255
        elif ft == 2:
            row = bytearray((a + b) & 255 for a, b in zip(row, prev))
        elif ft == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                if i >= bpp:
                    a, b, c = row[i - bpp], prev[i], prev[i - bpp]
                    # the two cases that cover flat regions, then the general rule
                    pr = a if b == c else (b if a == c else _paeth(a, b, c))
                else:
                    pr = prev[i]
                row[i] = (row[i] + pr) & 255
        prev = bytes(row)
        rows.append(prev)
    return rows


def inspect(data, expect=None, band=BAND_ROWS):
    """(facts, problems) for one PNG. `expect` is (width, height) or None. A problem is (code, message);
    the codes are png-corrupt, png-unsupported, png-size and png-blank."""
    facts, problems = {"bytes": len(data)}, []
    try:
        info = parse(data)
        facts.update(width=info["width"], height=info["height"], colour_type=info["colour_type"])
        if expect is not None and (info["width"], info["height"]) != tuple(expect):
            problems.append(("png-size", "the PNG is %d x %d where %d x %d was expected" % (
                info["width"], info["height"], expect[0], expect[1])))
        raw = inflate(info)
        nrows = min(band, info["height"])
        rows = unfilter_rows(raw, info["width"], info["bpp"], nrows)
    except PngError as e:
        return facts, problems + [(e.code, e.message)]
    bpp = info["bpp"]
    bg = rows[0][:bpp]
    ink, colours = 0, set()
    for r in rows:
        px = [r[i:i + bpp] for i in range(0, len(r), bpp)]
        ink += sum(1 for q in px if q != bg)
        colours.update(px)
    area = info["width"] * nrows
    facts.update(band_rows=nrows, ink_pct=round(100.0 * ink / area, 3), colours=len(colours))
    if ink < MIN_INK * area or len(colours) < MIN_COLOURS:
        problems.append(("png-blank", "the top %d rows hold %.3f%% non-background pixels in %d distinct colours; a "
                         "figure needs at least %.1f%% and %d (the measured least was 5.03%% and 471)" % (
                             nrows, 100.0 * ink / area, len(colours), 100.0 * MIN_INK, MIN_COLOURS)))
    return facts, problems


# ------------------------------------------------------------------ an encoder, for the tests and nothing else
def _forward(ft, row, prev, bpp):
    if ft == 0:
        return bytes(row)                      # the common case of the archive plants: no per-byte work
    out = bytearray(len(row))
    for i in range(len(row)):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if ft == 0:
            pr = 0
        elif ft == 1:
            pr = a
        elif ft == 2:
            pr = b
        elif ft == 3:
            pr = (a + b) >> 1
        else:
            pr = _paeth(a, b, c)
        out[i] = (row[i] - pr) & 255
    return bytes(out)


def _chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", _crc(ctype, body))


def _raw(width, height, depth, colour_type, scanlines):
    """A PNG around scanlines the caller has already filtered (filter byte first on each row)."""
    return (SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour_type, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(scanlines), 9)) + _chunk(b"IEND", b""))


def encode(width, height, rows, colour_type=2, filters=None):
    """An 8-bit PNG of `rows` (height byte strings of width x bpp), each scanline filtered as `filters[y]` says."""
    bpp = BYTES_PER_PIXEL[colour_type]
    scan, prev = bytearray(), bytes(width * bpp)
    for y, row in enumerate(rows):
        ft = filters[y] if filters else 0
        scan.append(ft)
        scan += _forward(ft, row, prev, bpp)
        prev = row
    return _raw(width, height, 8, colour_type, scan)


def _synthetic(width, height, bpp, ink=True, seed=1, ink_rows=None):
    """Rows that look like a figure's top band: a background with a scatter of anti-aliased-looking pixels,
    in the first `ink_rows` rows only if that is given (a big image whose band is all the check reads)."""
    x = seed
    rows = []
    bg = bytes([250, 251, 252, 255][:bpp])
    flat = bytes(bg * width)
    for y in range(height):
        if ink and ink_rows is not None and y >= ink_rows:
            rows.append(flat)
            continue
        row = bytearray(bg * width)
        if ink:
            for k in range(width):
                x = (x * 1103515245 + 12345) & 0x7FFFFFFF
                if (x >> 8) % 5 == 0:
                    v = (x >> 16) & 255
                    px = bytes([v, (v * 3) & 255, (v * 7) & 255, 255][:bpp])
                    row[k * bpp:(k + 1) * bpp] = px
        rows.append(bytes(row))
    return rows


def selftest():
    """(problems, report): the decoder agrees with the encoder on every filter, and each fault planted in a PNG
    is named by the check. A plant the check does not name is a problem; so is a clean image it refuses."""
    problems, report = [], []
    w, h = 41, 23
    for colour in (2, 6):
        bpp = BYTES_PER_PIXEL[colour]
        rows = _synthetic(w, h, bpp)
        for ft in range(5):
            png = encode(w, h, rows, colour, [ft] * h)
            info = parse(png)
            got = unfilter_rows(inflate(info), w, bpp, h)
            if got != rows:
                problems.append("png decoder: colour type %d, filter %d does not give back the rows it was given" % (
                    colour, ft))
        mixed = encode(w, h, rows, colour, [y % 5 for y in range(h)])
        info = parse(mixed)
        if unfilter_rows(inflate(info), w, bpp, h) != rows:
            problems.append("png decoder: colour type %d, a different filter on each row, does not round-trip" % colour)
    report.append("decoder: both colour types, every filter alone and all five in turn, give back exactly the rows "
                  "the encoder was given")
    good = encode(w, h, _synthetic(w, h, 3), 2, [y % 5 for y in range(h)])
    facts, bad = inspect(good, expect=(w, h))
    if bad:
        problems.append("png check: a clean synthetic image is refused: %s" % bad[0][1])
    flat = encode(w, h, [bytes([250, 251, 252]) * w] * h, 2)
    dot = _synthetic(w, h, 3, ink=False)
    dot[5] = bytes(dot[5][:6]) + bytes([0, 0, 0]) + bytes(dot[5][9:])
    idat_at = good.index(b"IDAT")
    bad_crc = bytearray(good)
    bad_crc[idat_at + 8] ^= 0x01                                           # a data byte, so its CRC fails
    after_ihdr = len(SIGNATURE) + 12 + 13                                  # an ancillary chunk goes here
    with_text = good[:after_ihdr] + _chunk(b"tEXt", b"note\x00hello") + good[after_ihdr:]
    bad_text = bytearray(with_text)
    bad_text[after_ihdr + 8 + 2] ^= 0x01                                   # inside the chunk only its CRC can see
    _f, found = inspect(with_text, expect=(w, h))
    if found:
        problems.append("png check: an image with an ancillary chunk is refused: %s" % found[0][1])
    else:
        report.append("png control: an ancillary chunk is allowed")
    bad_filter = bytearray(zlib.decompress(parse(good)["idat"]))
    bad_filter[0] = 9
    # structure, one rule at a time: chunks that are each whole and each have their CRC, arranged wrongly
    scan = zlib.decompress(parse(good)["idat"])
    comp = zlib.compress(scan, 9)
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    iend = _chunk(b"IEND", b"")
    note = _chunk(b"tEXt", b"k\x00v")

    def png_of(*chunks):
        return SIGNATURE + b"".join(chunks)
    # each of these is refused by one rule and, if that rule were gone, by a later one under the same code: so each
    # also names the words of its own rule, and a plant that is refused by the wrong rule is the check's failure
    structure = [
        ("a PNG whose signature has one damaged byte", bytes([good[0] ^ 1]) + good[1:], "no PNG signature"),
        ("image data one row short", png_of(ihdr, _chunk(b"IDAT", zlib.compress(scan[:-(1 + w * 3)], 9)), iend), " image needs "),
        ("a zlib stream cut short inside a whole chunk", png_of(ihdr, _chunk(b"IDAT", comp[:-6]), iend), "ends before its zlib stream does"),
        ("bytes after the zlib stream, inside the chunk", png_of(ihdr, _chunk(b"IDAT", comp + b"junk"), iend), "follow the zlib stream"),
        ("a first chunk that is not IHDR", png_of(note, ihdr, _chunk(b"IDAT", comp), iend), ", not IHDR"),
        ("image data split by another chunk", png_of(ihdr, _chunk(b"IDAT", comp[:20]), note, _chunk(b"IDAT", comp[20:]), iend), "not contiguous"),
        ("a whole chunk after IEND", png_of(ihdr, _chunk(b"IDAT", comp), iend, note), "follow IEND"),
        ("a file with no IEND", png_of(ihdr, _chunk(b"IDAT", comp)), "has no IEND"),
        ("a file with no image data", png_of(ihdr, iend), "has no image data"),
        ("an image of no width", png_of(_chunk(b"IHDR", struct.pack(">IIBBBBB", 0, h, 8, 2, 0, 0, 0)), _chunk(b"IDAT", comp), iend), "IHDR gives a"),
        ("an image of no height", png_of(_chunk(b"IHDR", struct.pack(">IIBBBBB", w, 0, 8, 2, 0, 0, 0)), _chunk(b"IDAT", comp), iend), "IHDR gives a"),
        ("a second IHDR", png_of(ihdr, ihdr, _chunk(b"IDAT", comp), iend), "malformed or repeated IHDR"),
        ("an IHDR twelve bytes long", png_of(_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)[:12]),
                                              _chunk(b"IDAT", comp), iend), "malformed or repeated IHDR"),
    ]

    def header_with(depth=8, colour=2, method=0, filtering=0, interlace=0):
        """The same image under an IHDR that differs in exactly one field."""
        return png_of(_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, colour, method, filtering, interlace)),
                      _chunk(b"IDAT", comp), iend)
    bgp = bytes([250, 251, 252])
    two_colours = encode(w, h, [bgp * (w // 2) + bytes([10, 10, 10]) * (w - w // 2)] * h, 2)    # ink aplenty, two colours
    bigw, bigh = 400, 160
    stray = [bytearray(bgp * bigw) for _ in range(bigh)]
    for k in range(40):                                                     # forty-one colours, forty pixels of ink
        stray[0][(10 + k) * 3:(11 + k) * 3] = bytes([10 + 5 * k, 200 - 3 * k, 1 + 2 * k])
    stray_pixels = encode(bigw, bigh, [bytes(r) for r in stray], 2)
    plants = [(what, data, (w, h), "png-corrupt", say) for what, data, say in structure] + [
        ("a flat image of the right size", flat, (w, h), "png-blank", None),
        ("one dark pixel on a flat image", encode(w, h, dot, 2), (w, h), "png-blank", None),
        ("the wrong size", good, (w * 2, h * 2), "png-size", None),
        ("a file cut short", good[:len(good) // 2], (w, h), "png-corrupt", None),
        ("a flipped bit in the image data", bytes(bad_crc), (w, h), "png-corrupt", "bad CRC"),
        ("a flipped bit in an ancillary chunk, which only its CRC can see", bytes(bad_text), (w, h), "png-corrupt", "bad CRC"),
        ("bytes after IEND", good + b"\x00", (w, h), "png-corrupt", "follow IEND"),
        ("not a PNG", b"GIF89a" + b"\x00" * 40, (w, h), "png-corrupt", "no PNG signature"),
        ("a 16-bit image", _raw(w, h, 16, 2, (b"\x00" + bytes(w * 6)) * h), (w, h), "png-unsupported", None),
        ("a palette image (colour type 3)", header_with(colour=3), (w, h), "png-unsupported", "colour type 3"),
        ("a compression method that is not 0", header_with(method=1), (w, h), "png-unsupported", None),
        ("a filter method that is not 0", header_with(filtering=1), (w, h), "png-unsupported", None),
        ("an interlaced image", header_with(interlace=1), (w, h), "png-unsupported", "interlace 1"),
        ("many pixels of ink in only two colours", two_colours, (w, h), "png-blank", None),
        ("forty pixels of ink in forty colours on a flat image", stray_pixels, (bigw, bigh), "png-blank", None),
        ("a scanline with filter type 9", _raw(w, h, 8, 2, bytes(bad_filter)), (w, h), "png-corrupt", "filter type 9"),
    ]
    for what, data, expect, code, say in plants:
        _f, found = inspect(data, expect=expect)
        codes = [c for c, _m in found]
        if code not in codes:
            problems.append("png check: %s was not named %s (it gave %s)" % (what, code, codes or "nothing"))
        elif say is not None and not any(say in m for c, m in found if c == code):
            problems.append("png check: %s was named %s, but not by the rule that refuses it: it said %r, and that rule says "
                            "%r" % (what, code, [m for c, m in found if c == code][0], say))
        else:
            report.append("png plant, %s: %s" % (what, code))
    return problems, report
