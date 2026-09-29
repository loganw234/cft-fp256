#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# verify/run.sh's ensure_vectors, and the record vectors/gen_vectors.py
# writes for it, held to planted directories: no host build, and the
# generator at small counts in a scratch copy of what it imports. About a
# minute in Git Bash.
#
#     bash verify/test-ensure-vectors.sh      # exit 0 pass, 1 fail, 2 cannot run
#
# Until 2026-09-29 ensure_vectors took any non-empty vectors/out for the
# whole census. On 2026-09-28 a generation that died for want of mpmath
# left five of the 168 sets and every later run reused them - and
# cft-selftest, the libcft stage's replay, passes on those five. Now the
# generator removes <out>/SHA256SUMS before it writes a set and writes it
# after the last, and ensure_vectors replays a directory only when that
# record names every set vectors/SHA256SUMS names and `sha256sum -c`
# holds it; anything else is regenerated, and a stage that cannot make
# it whole fails by name. This holds, against a small profile of its own:
#  - the generator's record: every set the run wrote and nothing else,
#    sorted, LF, bare names, held by sha256sum -c (and by shasum's, the
#    runner's fallback, where it is on PATH); byte for byte the same
#    after a --cache run that served every set; and GONE, with its
#    temporary name, after a run that crashed part way over a whole set,
#    as 2026-09-28's did (mpmath shadowed by a module that refuses to
#    import);
#  - ensure_vectors regenerates, saying why by name: no vectors/out; the
#    crash's leftovers, which have no record; a set cut at a line
#    boundary after the record was written, which only the digest sees;
#    a set deleted; a finished generation narrower than the profile. It
#    REUSES a whole set without running the generator;
#  - it fails by name when the generator cannot run, and when the
#    generator exits 0 but writes no record.
# Four negative controls put a defect back into a copy - the old
# non-empty test, the digest check skipped, the profile's names not
# compared, the generator's first removal dropped - and the case written
# for each must catch it.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILS=0

# The interpreter verify/run.sh's PY() picks, and native paths for it.
WIN=0
case "$(uname -s)" in MINGW*|MSYS*) WIN=1;; esac
if [ "$WIN" = 1 ] && command -v python >/dev/null 2>&1; then PYBIN=$(command -v python)
elif command -v python3 >/dev/null 2>&1; then PYBIN=$(command -v python3)
else PYBIN=$(command -v python || true); fi
native() { if [ "$WIN" = 1 ]; then cygpath -w "$1"; else printf '%s\n' "$1"; fi; }
if [ -z "$PYBIN" ] || ! "$PYBIN" -c 'import mpmath' >/dev/null 2>&1; then
  echo "CANNOT RUN: no python with mpmath (the generator's transcendental sets need it)"
  exit 2
fi

# A scratch root holding what the generator reads - itself, the model,
# and the pi/2 worst-case tool the model's reduction pools call, with the
# header that tool reads - and a profile of its own: twelve sets of fp32
# at two attributes, every family.
R=$T/root
mkdir -p "$R/vectors" "$R/python" "$R/host/tools" "$R/host/src"
cp "$ROOT/vectors/gen_vectors.py" "$R/vectors/"
cp -r "$ROOT/python/cft_golden" "$R/python/"
rm -rf "$R/python/cft_golden/__pycache__"
cp "$ROOT/host/tools/pi_worstcase.py" "$R/host/tools/"
cp "$ROOT/host/src/mp_2opi.h" "$R/host/src/"
SMALL=(--formats fp32 --rounding rne rtz --directed 20 --random 20 --simple 2
       --transcend 1 --reduce 0 --augmented 2 --character 1 --minmaxmag 2
       --formatof 1)
gen() {  # <gen_vectors.py> <out> [args...]: the generator, output kept
  local g=$1 o=$2; shift 2
  "$PYBIN" "$g" --out "$o" "$@" > "$T/gen.log" 2>&1
}
gen "$R/vectors/gen_vectors.py" "$T/whole" "${SMALL[@]}" \
  || { echo "CANNOT RUN: the small generation failed:"; tail -5 "$T/gen.log"; exit 2; }
sed 's#  #  out/#' "$T/whole/SHA256SUMS" > "$R/vectors/SHA256SUMS"
NSETS=$(grep -c . "$R/vectors/SHA256SUMS")
# mpmath shadowed, for the crash 2026-09-28's PATH slip produced.
mkdir -p "$T/nompmath"
echo 'raise ImportError("no mpmath: planted by verify/test-ensure-vectors.sh")' \
  > "$T/nompmath/mpmath.py"
NOMP=$(native "$T/nompmath")

ok()  { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }

# holds <dir>: its record names exactly the sets in it, sorted, and holds.
holds() {
  local d=$1 names sets
  [ -f "$d/SHA256SUMS" ] || { echo "no SHA256SUMS"; return 1; }
  if grep -q $'\r' "$d/SHA256SUMS"; then echo "CR in SHA256SUMS"; return 1; fi
  if grep -vqE '^[0-9a-f]{64}  [^/ ]+\.jsonl$' "$d/SHA256SUMS"; then
    echo "a line that is not '<sha256>  <set>.jsonl'"; return 1
  fi
  names=$(sed 's#^[0-9a-f]*  ##' "$d/SHA256SUMS")
  [ "$names" = "$(printf '%s\n' "$names" | LC_ALL=C sort)" ] || { echo "not sorted"; return 1; }
  sets=$(cd "$d" && ls -1 -- *.jsonl | LC_ALL=C sort)
  [ "$names" = "$sets" ] || { echo "names other than the directory's sets"; return 1; }
  (cd "$d" && sha256sum -c --quiet --strict SHA256SUMS) > "$T/holds.log" 2>&1 \
    || { echo "sha256sum -c: $(head -2 "$T/holds.log" | tr '\n' ' ')"; return 1; }
  if command -v shasum >/dev/null 2>&1; then
    (cd "$d" && shasum -a 256 -c --quiet --strict SHA256SUMS) > "$T/holds.log" 2>&1 \
      || { echo "shasum -c: $(head -2 "$T/holds.log" | tr '\n' ' ')"; return 1; }
  fi
}

# ---- the generator's record -----------------------------------------
# Each prints one "ok" or "FAIL" line, in this shell (never a pipeline),
# so a failure reaches FAILS.
rec_whole() {
  local why
  if why=$(holds "$T/whole"); then
    ok "a finished run's record: all $NSETS sets it wrote, sorted, LF, held by sha256sum -c$(command -v shasum >/dev/null 2>&1 && echo ' and shasum -c')"
  else bad "a finished run's record: $why"; fi
}
rec_cache() {  # <gen_vectors.py>
  local g=$1
  rm -rf "$T/cached" "$T/cache"
  if gen "$g" "$T/cached" "${SMALL[@]}" --cache "$(native "$T/cache")" \
     && gen "$g" "$T/cached" "${SMALL[@]}" --cache "$(native "$T/cache")" \
     && [ "$(grep -c '\[cached\]$' "$T/gen.log")" -eq "$NSETS" ] \
     && cmp -s "$T/cached/SHA256SUMS" "$T/whole/SHA256SUMS"; then
    ok "a --cache run that served all $NSETS sets writes the same record, byte for byte"
  else bad "a --cache run that served every set: its record differs, or it did not serve them"; fi
}
rec_crash() {  # <gen_vectors.py>
  local g=$1
  rm -rf "$T/over"; cp -r "$T/whole" "$T/over"
  : > "$T/over/SHA256SUMS.tmp"
  if PYTHONPATH="$NOMP" gen "$g" "$T/over" "${SMALL[@]}"; then
    bad "a run without mpmath exited 0, so the crash was not planted"
  elif ! grep -q "no mpmath: planted" "$T/gen.log"; then
    bad "a run without mpmath failed, but not for the planted reason: $(tail -1 "$T/gen.log")"
  elif [ -e "$T/over/SHA256SUMS" ] || [ -e "$T/over/SHA256SUMS.tmp" ]; then
    bad "a run that crashed over a whole set left a record behind ($(cd "$T/over" && ls SHA256SUMS* | tr '\n' ' '))"
  else ok "a run that crashed over a whole set leaves no record, and no temporary one"; fi
}

# ---- ensure_vectors -------------------------------------------------
fns() {  # <run.sh>: the functions under test, as text
  awk '/^(sha256_holds|vectors_whole|ensure_vectors)\(\) \{/ { on = 1 }
       on { print }
       on && /^\}/ { on = 0 }' "$1"
}
# ev <run.sh> [py]: ensure_vectors from that runner against $R, with the
# small profile's arguments. "py" is the interpreter's name: good,
# nompmath (the crash), or silent (exits 0 having written nothing).
# Every call of PY is logged to $T/py-calls; the output is in $T/ev.log.
ev() {
  local fn py=${2:-good}
  fn=$(fns "$1")
  : > "$T/py-calls"
  ( ROOT=$R
    VECTOR_ARGS=("${SMALL[@]}")
    PY() {
      printf '%s\n' "$*" >> "$T/py-calls"
      case "$py" in
        good)     "$PYBIN" "$@";;
        nompmath) PYTHONPATH="$NOMP" "$PYBIN" "$@";;
        silent)   return 0;;
      esac
    }
    eval "$fn"
    ensure_vectors ) > "$T/ev.log" 2>&1
}
plant() {  # <state>: vectors/out in $R as that state
  local o=$R/vectors/out
  rm -rf "$o"
  case "$1" in
    absent) ;;
    crash)  PYTHONPATH="$NOMP" gen "$R/vectors/gen_vectors.py" "$o" "${SMALL[@]}" \
              && echo "the crash plant did not crash";;
    whole)  cp -r "$T/whole" "$o";;
    star)   cp -r "$T/whole" "$o"      # the record as MSYS's sha256sum writes one
            sed -i 's/^\([0-9a-f]\{64\}\)  /\1 */' "$o/SHA256SUMS"
            [ "$(grep -c '^[0-9a-f]\{64\} \*' "$o/SHA256SUMS")" -eq "$NSETS" ] \
              || bad "the star plant did not take: $(head -1 "$o/SHA256SUMS")";;
    cut)    cp -r "$T/whole" "$o"
            head -n 5 "$T/whole/fp32-rtz.jsonl" > "$o/fp32-rtz.jsonl";;
    gone)   cp -r "$T/whole" "$o"; rm "$o/fp32-augmented.jsonl";;
    narrow) gen "$R/vectors/gen_vectors.py" "$o" --formats fp32 --rounding rne \
              --directed 20 --random 20 --simple 2 --transcend 1 --reduce 0 \
              --augmented 2 --character 1 --minmaxmag 2 --formatof 1 \
              || echo "the narrow plant did not generate";;
  esac
}
calls() { grep -c . "$T/py-calls"; }
# evcase <run.sh> <state> <py> <expect> <regex>: expect is "reuse" (exit
# 0, no generator run, vectors/out untouched), "regen" (the generator
# run, exit 0, vectors/out whole afterwards) or "fail" (exit nonzero);
# the log must match regex, which names why.
evcase() {
  local r=$1 state=$2 py=$3 want=$4 re=$5 rc why before=""
  plant "$state"
  [ "$want" = reuse ] && before=$(cd "$R/vectors/out" && sha256sum -- * | sha256sum)
  ev "$r" "$py"; rc=$?
  # The outcome first, then the words: a control is caught for what it
  # does, not for how it says it.
  case "$want" in
    reuse)
      if [ $rc -ne 0 ] || [ "$(calls)" -ne 0 ]; then
        bad "$state/$py: expected reuse; exit $rc after $(calls) generator run(s)"; return
      elif [ "$(cd "$R/vectors/out" && sha256sum -- * | sha256sum)" != "$before" ]; then
        bad "$state/$py: reused, but vectors/out changed"; return
      fi;;
    regen)
      if [ $rc -ne 0 ] || [ "$(calls)" -ne 1 ]; then
        bad "$state/$py: expected one regeneration; exit $rc after $(calls) generator run(s) - $(tr '\n' ' ' < "$T/ev.log" | cut -c1-200)"; return
      elif ! why=$(holds "$R/vectors/out"); then
        bad "$state/$py: regenerated, and vectors/out is not whole: $why"; return
      elif [ "$(sed 's#  #  out/#' "$R/vectors/out/SHA256SUMS")" != "$(cat "$R/vectors/SHA256SUMS")" ]; then
        bad "$state/$py: regenerated, and its record is not the profile's"; return
      fi;;
    fail)
      if [ $rc -eq 0 ]; then bad "$state/$py: expected a failure; exit 0"; return; fi;;
  esac
  if ! grep -qE -- "$re" "$T/ev.log"; then
    bad "$state/$py: $want as expected, but not saying /$re/: $(tr '\n' ' ' < "$T/ev.log" | cut -c1-240)"
    return
  fi
  case "$want" in
    reuse) ok "$state: reused, the generator not run - $(grep -m1 -oE -- "$re" "$T/ev.log")";;
    regen) ok "$state: regenerated - $(grep -m1 -oE -- "$re" "$T/ev.log")";;
    fail)  ok "$state/$py: failed (exit $rc) - $(grep -m1 -oE -- "$re" "$T/ev.log")";;
  esac
}
ev_cases() {  # <run.sh>
  local r=$1
  evcase "$r" absent good regen "vectors/out does not exist"
  evcase "$r" crash  good regen "vectors/out has no SHA256SUMS"
  evcase "$r" cut    good regen "fp32-rtz\.jsonl: FAILED"
  evcase "$r" gone   good regen "fp32-augmented\.jsonl: FAILED open or read"
  evcase "$r" narrow good regen "leaves out 5 of the $NSETS sets vectors/SHA256SUMS names"
  evcase "$r" whole  good reuse "names all $NSETS sets vectors/SHA256SUMS names, and all $NSETS it names hold"
  evcase "$r" star   good reuse "names all $NSETS sets vectors/SHA256SUMS names, and all $NSETS it names hold"
  evcase "$r" crash  nompmath fail "FAILED - the generator exited nonzero"
  evcase "$r" crash  silent   fail "FAILED - regenerated, and still not a whole set: vectors/out has no SHA256SUMS"
}

echo "== vectors/gen_vectors.py's record, as committed"
rec_whole
rec_cache "$R/vectors/gen_vectors.py"
rec_crash "$R/vectors/gen_vectors.py"
echo "== verify/run.sh's ensure_vectors, as committed"
ev_cases "$ROOT/verify/run.sh"

# ---- negative controls ----------------------------------------------
# control <name> <file> <marker> <replacement> <case...>: the case must
# FAIL on a copy of <file> whose line holding <marker> is <replacement>.
control() {
  local name=$1 file=$2 m=$3 repl=$4 c before
  shift 4
  c=$T/control-$(basename "$file")
  grep -qF -- "$m" "$file" || { bad "control $name: marker $m not found in $file"; return; }
  REPL="$repl" awk -v m="$m" 'index($0, m) { print ENVIRON["REPL"]; next } { print }' \
    "$file" > "$c"
  before=$FAILS
  "$@" "$c" > "$T/control.log"
  if [ "$FAILS" -gt "$before" ]; then
    FAILS=$before
    ok "control $name: caught - $(grep -m1 '^FAIL' "$T/control.log" | cut -c7-200)"
  else
    bad "control $name: the defect went unseen"
  fi
}
one_ev() {  # <state> <expect> <regex> <run.sh>
  evcase "$4" "$1" good "$2" "$3"
}
echo "== negative controls"
control "the old test (anything in vectors/out)" "$ROOT/verify/run.sh" \
  '# ENSURE-VECTORS-WHOLE' \
  '  msg="(the old test)"; if [ -n "$(ls "$d" 2>/dev/null)" ]; then' \
  one_ev crash regen "vectors/out has no SHA256SUMS"
control "the digest check skipped" "$ROOT/verify/run.sh" \
  '# VECTORS-WHOLE-DIGESTS' '  if false; then' \
  one_ev cut regen "fp32-rtz\.jsonl: FAILED"
control "the profile's names not compared" "$ROOT/verify/run.sh" \
  '# VECTORS-WHOLE-NAMES' '  if false; then' \
  one_ev narrow regen "leaves out 5 of the $NSETS sets"
gen_control() {  # <gen_vectors.py>: the crash case, with that generator
  # beside the scratch root's python/, where its imports resolve
  cp "$1" "$R/vectors/gen_vectors.control.py"
  rec_crash "$R/vectors/gen_vectors.control.py"
}
control "the generator's first removal dropped" "$ROOT/vectors/gen_vectors.py" \
  '    remove_record(outdir)' '' \
  gen_control

echo
if [ "$FAILS" -eq 0 ]; then
  echo "test-ensure-vectors: PASS"
  exit 0
fi
echo "test-ensure-vectors: FAIL ($FAILS)"
exit 1
