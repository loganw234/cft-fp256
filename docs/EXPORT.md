# Exporting the project's figures, and where it stands

`python/project_packager.py` makes one dated archive of the project's
figures and of where the project stands, for use outside the repository:
slides, a post, a report, a folder to hand to someone. The archive is a zip.
It holds every figure as the SVG that is committed and as a PNG render of
it, each with its sidecar and its caption; a status document made by script
from the project's own files, as Markdown and as a page for a browser; a few
light documents as they stand; and a manifest that says when the archive was
made, from which commit, and where every file in it came from.

It is not [FIGURES.md](FIGURES.md). That page is the gallery, written by
`python/project_figures.py` and read on GitHub. This archive is the same
figures, and the README's two charts beside them, taken out of the
repository with the date they were made on, and with what a reader outside
needs: a picture format every tool opens, and a record of what each file
is.

## Make one

```bash
python python/project_packager.py                      # exports/cft-fp256-status-<date>-<commit>.zip
python python/project_packager.py --no-png             # the same without PNG renders: no converter needed
python python/project_packager.py --verify exports/<archive>.zip
python python/project_packager.py --check              # the packager's own self-test: no converter needed
python python/project_packager.py --check --png        # and the legs that use the real converter
```

It wants Python 3.10 or later, git, a clean checkout of the commit to
archive and, unless `--no-png` is given, librsvg's `rsvg-convert` on the
PATH (or named with `--converter`). It imports nothing that is not in the
standard library or in this repository.

The pieces: `python/project_packager.py` is the command (git, the refusals, the
figures, the converter, the manifest, the zip, `--verify`);
`python/packager_status.py` writes `STATUS.md`; `python/packager_html.py` renders
it as a page and checks the page against it; `python/packager_png.py` reads a
PNG far enough to say whether it is the right size and not blank;
`python/packager_check.py` is the self-test.

| option | what it does |
|---|---|
| `--out DIR` | where to write; the default is `exports/`, which `.gitignore` names. Inside the tree, a directory git does not ignore is refused. |
| `--no-png` | make no PNG renders. The manifest then says that none was made, and why. |
| `--converter PATH` | an `rsvg-convert` to use instead of the one on PATH. |
| `--scale N` | the PNG scale, 1 to 4; the default is 2. |
| `--allow-dirty` | make an archive of a tree with uncommitted changes: its name ends `-dirty` and its manifest lists the paths that differ. |
| `--now UTC` | fix the clock, as `2026-10-19T17:31:02Z`, so that two builds can be compared byte for byte. The manifest says the clock was given (`archive.clock`). |
| `--force` | replace an archive of the same name. |

## What is in the archive

```
cft-fp256-status-<date>-<commit>/
  MANIFEST.json      every other file: its size, SHA-256 and origin; how the archive was made
  STATUS.md          where the project stands, made by script
  STATUS.html        the same words, for a browser
  README.md  LICENSE  NOTICE  CAPABILITIES.md  docs/FIGURES.md  docs/COMPLIANCE.md
                     the light documents, as they stand
  docs/img/figures/<name>-light.svg  <name>-dark.svg  <name>.json
                     the gallery's figures and their sidecars, as committed
  docs/img/bench/<name>-light.svg    <name>-dark.svg
                     the README's two charts, as committed
  png/<name>-light.png  <name>-dark.png
                     a render of each SVG
  captions/<name>.md each figure's caption
```

A file that comes from the repository keeps its repository path, so that
the copied README and gallery find their pictures where they expect them.
`png/`, `captions/`, `STATUS.md`, `STATUS.html` and the manifest are the
packager's.

**The light documents, and why each.** The README is the front page: what
the project is, how fast it is, how it is checked. `docs/FIGURES.md` is the
gallery as published, with every caption and its sources. `CAPABILITIES.md`
is what the tile can and cannot do, mark by mark, which is the features as
they stand. `docs/COMPLIANCE.md` is the standard's clauses one by one: what
is implemented, what is refused. `LICENSE` and `NOTICE` are the terms the
figures are distributed under, and the attribution notice the licence asks
every redistribution to carry. Left out on purpose: the long documents
(the ledger, the roadmap, the contract), which are not light, and
`CONFORMANCE.md`, which is the profile an independent implementation is scored
against and a longer read than a status export needs. The README and the
gallery link to documents the archive does not hold; those links do not
resolve in it.

**Where each kind of file came from.**

| file | from | the manifest records |
|---|---|---|
| a figure's SVG | the tree, byte for byte | the figure, its theme, its sidecar and the sidecar's SHA-256 |
| a sidecar | the tree | its figure |
| a PNG | the archive's own SVG, rendered | the SVG and its SHA-256, the scale, the size, the converter and its version |
| a caption | the figure's block in `docs/FIGURES.md`, without its picture; for the README's two charts, the alt text of their picture in the README | the file and its SHA-256 |
| a light document | the tree, as it stands | the reason it is there |
| `STATUS.md` | `python/packager_status.py`, from the files the manifest lists | every number: its value, its sources and the rule that read it |
| `STATUS.html` | `python/packager_html.py`, rendering `STATUS.md` | the Markdown's SHA-256 |

The README's two charts have no sidecar and no block in the gallery. Their
caption is the README's own alt text, and the manifest records the command
that makes them (`python/readme_charts.py`, from the sweeps in `docs/bench/`)
and the digests of the data. Nothing else held that these two SVGs are what
that command makes, so the packager checks it: it makes them again in a
scratch directory and requires the four files to be the committed ones,
byte for byte.

## STATUS.md: made, not typed

`STATUS.md` answers what the project is, what is built, how much is checked,
what the card last did, where the current round stands, and what each figure
shows. Every number in it is read, and none is typed:

- A number reaches the document only as a registered fact: its value, the
  text it prints as, the files it was read from with each file's SHA-256, and
  the rule that read it. The document class refuses a plain string that
  contains a digit, so `52 stages` cannot be written into the template, and
  neither can a count formatted into a string by code, which would arrive as
  the same kind of string. The only names with a digit that are allowed are
  `cft-fp256`, `SHA-256` and `U50`, and they are listed beside the refusal.
- Text reaches it as a quotation, copied from a named file and printed as a
  block quotation: the README's opening block and its table of what is built,
  the newest headings of the ledger, the heading of the roadmap's latest
  plan of record, each figure's title and caption. Links inside a quotation are
  made to resolve inside the archive.
- Every reader finds what it expects or says by name what is missing. A
  pattern that matches nothing is an error, never a count of zero.
- The commit is the commit's own: its name, and its committer time in UTC. The
  date the archive was made is not in `STATUS.md`; it is in the archive's name
  and in the manifest, so that two archives of one commit hold the same
  document.

What it reads, and from where: the runner's stage lines and budgets
(`verify/run.sh`), the RTL bench list (`tb/Makefile`), the proof tasks
(`formal/run.sh`), the test functions defined in `python/tests`, the figures'
own sidecars for the card's long run, its clock, its speed and the math
library's measurements, the ledger's headings and the README. The sidecars are
read, and not the extracts or the raw logs, because the figure check has just
held each sidecar to its sources; the manifest names each one with its digest.

## Dated, and reproducible

The date is when the run began, once, from the system clock: in the archive's
name (as UTC, so `cft-fp256-status-2026-10-19-<commit>.zip` is a UTC date) and
in the manifest as `created_utc`. Nothing else in the archive depends on the
run:

- the files copied from the tree are the tree's bytes;
- `STATUS.md` and `STATUS.html` are functions of the tree;
- the zip is written **stored**, not compressed, so that no zlib build can
  change a byte; entries are sorted by path, each with Unix mode 0644 and the
  host field set to Unix, so that the platform it was made on does not show;
- **every entry's timestamp is the commit's own committer time**, in UTC,
  rounded down to an even second. A zip entry has no time zone and
  two-second resolution, so this is a wall-clock reading that the manifest
  states is UTC. It is the same for every entry of every archive of one
  commit, whenever it was made.

So two runs at one commit, with one converter on one set of fonts, give the
same files byte for byte, and differ only in `MANIFEST.json`'s `created_utc`
and `date_utc`, in the archive's name and in the directory the entries sit in,
which carry the date. With the same `--now` the whole zip is the same. The
manifest records that the clock was given (`archive.clock`), so an archive made
with `--now` set to the time an earlier archive recorded differs from that one
in this field and in no other. The self-test shows all three: the same commit
and clock give the same zip, a clock a day and three seconds later changes
only those date fields, and a build in another process under another
`PYTHONHASHSEED` gives the same zip.

Stored costs size: on 2026-10-19 the archive with PNGs was 10.3 MB, where
the same entries deflated at the highest level were 8.7 MB, because the PNGs
(86% of it) are compressed already.

## The PNGs

**The converter is `rsvg-convert`** (librsvg). It was chosen against the other
tools that were already on the maintainer's desktop, measured on one figure
at 2x on 2026-10-19:

| tool | time | the same twice? | its PNG's chunks | what it does with the SVG's fonts |
|---|---|---|---|---|
| `rsvg-convert` 2.58.4 | 0.41 s | yes | header, background marker, data, end | follows the SVG's own font stack through the system's fonts |
| ImageMagick 7.1.2-8 | 0.32 s | no | header, colour and size chunks, data, and three text chunks, `date:create`, `date:modify` and `date:timestamp`, which move between runs | its SVG delegate is RSVG 2.40.20, an older librsvg |
| PyMuPDF 1.27.2.3 | 0.05 s | yes | header, pixel density, data, end | ignores the font stack: MuPDF's own faces |
| Edge, headless | 1.1 to 1.2 s a file | yes | header, data, end | a browser's, so it follows the stack |

Edge and `rsvg-convert` both give the same bytes twice and both follow the
SVG's fonts. `rsvg-convert` is the lighter (a small process for each file, a
third of the time), is one tool with one job, and answers `--version` with
a version the manifest can record; a browser's version is not a command-line
answer on Windows, where running `msedge --version` starts the browser.
ImageMagick is out because its output moves between runs as it stands (it can
be told to leave the date chunks out; that was not tried), and PyMuPDF because
it does not draw the SVG's fonts. On a Windows PATH `convert` is a disk tool
and not ImageMagick; the packager never looks for that name.

**The fonts.** The SVGs name system fonts, not fonts they carry:
`-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif` for
text and `ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace` for
numbers. A PNG's pixels therefore depend on the machine that renders them. The
manifest records the stacks and the fonts the render actually used, read from
the `/BaseFont` names of a PDF that the same converter writes from each SVG:
on the maintainer's desktop, `SegoeUI`, `SegoeUI-Semibold`, `Consolas` and
`Consolas-Bold`. On another machine the same SVG may be drawn in other fonts
and give other bytes; the manifest says which.

**The scale is 2x: 1800 px wide.** Each SVG declares its own size, and on
2026-10-19 every one was 900 px wide (the manifest records the widths it
found). Twice that is the usual export for a slide or a page that may be seen
on a dense screen, and it stays sharp when a tool scales it down; `--scale`
changes it.
The figures are on an opaque background in both themes, so no PNG is
transparent, and no background colour is given.

**The check.** Each PNG is checked for its size and for not being blank before
anything is written, and again by `--verify`. The size is the SVG's declared
size times the scale. A PNG is blank here if, in its top 160 rows, fewer than
0.5% of the pixels differ from the corner pixel or fewer than 32 colours occur.
Both numbers come from a measurement, not from a belief: across all 34 renders
the top rows held at least 5.03% non-background pixels and 471 colours. The
check reads the PNG with `python/packager_png.py`, a decoder of the standard
library alone, and only the band, because a pure-Python decode of the whole
image took 53 s for the 34 files on a quiet desktop and the band 6.6 s (111 s
and 10.7 s when first measured, beside other work). Its decoder gives the
same pixels as Pillow's on all 34 (checked outside the repository). What
it does not prove is that the whole figure was drawn: a render with its title
and nothing below passes. The packager pins the bytes instead, with a SHA-256,
and shows that a second render is the same bytes.

## What it refuses

Each refusal is by name, writes nothing, and ends the run with exit status 1.
Several that do not depend on each other are reported together.

| name | when |
|---|---|
| `no-git`, `not-a-git-tree` | there is no git, or the root is not the top of a work tree that has a commit |
| `dirty-tree` | the tree differs from `HEAD`. The archive names a commit, so it is made from a clean tree; `--allow-dirty` records the difference instead, in the name and the manifest. |
| `missing-figure`, `missing-document` | a figure's light or dark SVG or its sidecar is absent, or a README chart's SVG is absent or has no `aria-label` to name it by; a figure's files have no place in the gallery; or a light document is absent |
| `gallery-unreadable`, `readme-unreadable` | `docs/FIGURES.md` or the README no longer has the structure the packager reads |
| `sidecar-mismatch` | a sidecar is not JSON or not shaped like a sidecar, or does not describe its figure: another name, other files, an alt text that is not its SVG's or the gallery's, a title that is not the gallery's, an SVG that declares no size, a source or an extract that is not in the tree, or whose digest is not the tree's file |
| `figures-out-of-date` | `python/project_figures.py --check` fails, or prints no summary: a figure, sidecar or caption is not what a fresh generation gives. It is run first, so that an out-of-date figure is never exported. |
| `readme-charts-out-of-date` | the README's charts are not what `python/readme_charts.py` makes from `docs/bench/` |
| `no-converter`, `converter-unusable` | there is no `rsvg-convert`, or the one named does not answer `--version` as it does, and `--no-png` was not given |
| `render-failed`, `png-size`, `png-blank`, `png-corrupt`, `png-unsupported` | the converter failed, or its PNG is the wrong size, blank, damaged or of a kind the reader does not hold; or an SVG declares no size, so the size of its PNG cannot be known |
| `status-source` | a file `STATUS.md` is read from no longer says what its reader expects |
| `html-text`, `html-malformed`, `html-link` | the page does not say what the Markdown says, its tags do not balance, or it names a file the archive does not hold |
| `personal-path` | anything bound for the archive holds a path under a user's directory |
| `output-not-ignored` | the output directory is inside the tree and git does not ignore it |
| `exists` | the archive is already there; `--force` replaces it |
| `self-verify` | the archive just written does not verify: a defect in the packager, and nothing is left behind |

## Where it writes

`exports/`, in the tree, and `.gitignore` names it: nothing the packager makes
is committed. It refuses an output directory inside the tree that git does not
ignore, so that its own output cannot make the next run find the tree dirty.

## Checking an archive

`--verify ARCHIVE` opens the zip and re-hashes every file against the manifest,
and then checks what a hash cannot: that the manifest agrees with itself and
with the archive. It prints every problem it finds, by name, and exits 1 if
there is one.

| name | when |
|---|---|
| `archive-unreadable`, `archive-structure` | the file is not a zip; its entries are not all under one directory, an entry name occurs twice, or an entry would extract outside its directory |
| `manifest-missing`, `manifest-unreadable` | there is no `MANIFEST.json`, or it does not parse, is not a manifest, or is a format this reader does not know |
| `manifest-mismatch` | the manifest disagrees with itself: the archive's name is not its date, commit and tree state; the time it was made is not on its date; it says the tree was clean and lists differing paths, or the reverse; the commit's time rounded down is not the entries' stamp; or the statistics it records for a PNG are not the PNG's |
| `file-unlisted`, `file-missing` | a file is in the archive and not in the manifest, or the reverse |
| `size-mismatch`, `hash-mismatch` | a file's size or SHA-256 is not what the manifest says |
| `zip-metadata` | an entry is not stored, not Unix-made, not mode 0644, has a time that is not the manifest's, or the entries are not sorted by path |
| `png-unexpected`, `png-missing`, `png-source` | the archive holds PNGs and the manifest says none was made, or holds none and the manifest says they were, or a PNG's SVG is not in the archive |
| `png-size`, `png-blank`, `png-corrupt`, `png-unsupported` | a PNG is not its SVG's size times the scale, or not the manifest's size, or is blank, damaged, or of a kind the reader does not hold |
| `sidecar-mismatch` | a sidecar does not parse, or does not describe its figure: the SVGs' title and aria-label are not its alt text, or it names another figure than the manifest does |
| `link-dead`, `html-mismatch`, `html-text`, `html-malformed`, `html-link` | `STATUS.md` links to a file the archive does not hold; `STATUS.html` is not what the renderer makes of `STATUS.md`, does not say its words, has tags that do not balance, or names a file the archive does not hold |
| `personal-path` | a file or the manifest holds a path under a user's directory |

Each of these is planted in an archive that has been rewritten so that its
hashes still agree, to show that it is that check that fails and not the hash
that catches it first.

## The packager's own check, and the runner

`python python/project_packager.py --check` is the packager's self-test: a
check that cannot fail is a defect, so it plants each fault in a scratch copy and
requires it to be named. It needs no converter. It:

1. asks whether an archive can still be made from this tree: the figures and
   their sidecars agree, `STATUS.md` builds from sources that still say what
   its readers expect, every link would resolve, and its page says its words;
2. plants the template's rules and each reader's refusal to default;
3. runs the PNG reader against its own encoder on every filter, and plants
   each kind of damaged, unsupported or blank image;
4. in a scratch copy of the tree made of exactly the files the packager and the
   figure check read, committed in a git repository of its own, builds an
   archive and verifies it; shows the three kinds of reproducibility above;
   plants every refusal in the table above, each under its own name (a fake
   converter stands in for `rsvg-convert`, failing, or writing a blank,
   half-size, 16-bit or non-PNG image; the refusals that stand for a defect in
   the packager itself, a page that does not match its Markdown, a status
   document that names a file the archive lacks, an archive that does not
   verify once written, are planted by replacing that one function for the
   length of one build); plants a corrupted sidecar that gets past a figure
   check that has been stubbed out; and plants each of `--verify`'s names in an
   archive rewritten to defeat the hash.

`--check --png` adds the real converter: a build with PNGs, its verification,
its reproducibility, and planted replacements of a real PNG. It refuses by name
if there is no converter, because it was asked to use one.

**It belongs in the `generated` stage, and is there as the stage's eighth
generator; the PNG legs do not belong in any stage.** The converter-free check
owns no committed file, but it fails exactly when something it reads moves
(the README, the gallery, a sidecar, the ledger's newest heading), which is the
kind of drift the stage exists to find; it takes 38 to 46 s on the maintainer's
Windows desktop and 14 s under WSL's Python 3.10 (2026-10-19); it needs git, to
commit a copy of the files it reads in a temporary directory of its own (no
history of the tree it checks, no network), and the standard library, nothing
else: no converter, no Pillow, no PyMuPDF; it never skips and prints no `SKIP`
line, so `--require-all` is satisfied; and its failure output avoids the words
that make the stage print STALE, because there is nothing to regenerate. The
legs that need a converter
cannot join it: CI's host job installs no librsvg (`.github/workflows/gates.yml`
sets up Python and Node, and installs gfortran and some pip packages; whether
the hosted image carries an `rsvg-convert` is not known), and a check that
skipped inside a passing stage would fail `--require-all`. They are run by
hand, on a host that has one.

## Known limits

- **The PNGs depend on the machine's fonts.** The SVGs, the sidecars, the
  captions, `STATUS.md`, `STATUS.html` and the zip do not. The manifest says
  which fonts a render used.
- **"Not blank" is a measure of the top rows.** It would pass a render with its
  title and nothing below. The hash and the second render are what pin the rest.
- **The README's charts are checked with a fixed command.** The packager makes
  them with the arguments in `python/project_packager.py` (the sweep and the
  two peer files, and the machine labels). If they are ever made another way it
  refuses by name, and the constant there must follow.
- **`STATUS.md`'s readers are tied to the shape of what they read:** the README's
  title line and its `What is built and working` heading, the gallery's blocks,
  the ledger's `## ` headings with a date at the start of the newest, the word
  `plan of record` in a roadmap heading. A change there stops the export, and
  in the `generated` stage the gate, with a message that names the file.
- **The history figures end at the commit their extracts were read at**, and the
  status document quotes their captions as they are. `STATUS.md` says what the
  tree holds now, from the tree.
- **A dirty tree can be exported, never a stale figure.** `--allow-dirty` does
  not turn off the figure check.
- **One of `--verify`'s rules cannot be planted on Windows.** An entry whose
  name has a backslash is refused as one that could extract outside its
  directory, and Python's `zipfile` reads a backslash as a slash on Windows, so
  no archive read there can show it. The self-test plants it where `os.sep` is a
  slash, and says in its report that it did not run it where it is not.
- **Stored is larger.** About 1.6 MB, 15%, on the archive of 2026-10-19.
