#!/bin/bash
# formal/run.sh - the whole formal gate, one command, per-proof verdicts.
#
#   MSYS_NO_PATHCONV=1 docker run --rm -v <repo>:/work -w /work \
#       cft-formal ./formal/run.sh
#
# or just ./formal/run.sh from a Git Bash / Linux shell: if sby is not
# on PATH the script re-execs itself inside the cft-formal image
# (docker/Dockerfile.formal), so the host needs Docker and nothing
# else. Same gate on a developer box and in CI, same claim.
#
# The gate is six proof files - thirty tasks - and a tripwire, in this
# order:
#
#   fifo.sby      prove+cover   cft_fifo contract, unbounded (pdr)
#   seedop.sby    check+cover   cft_seedop special-case routing
#   equiv.sby     check+cover   cft_simpleops == frozen pre-rewrite ref
#   mulexact.sby  7 geometries  cft_mulpass' iterated product is exact,
#                 x 2 lemmas    at the REAL 24-bit chunk, for every pass
#                 + 2 covers    geometry the tile builds
#   mulpass_real  4 geometries  the same claim as ONE property, where a
#                               solver will take it that way - the
#                               composition argument's independent check
#   lzcone.sby    4 rungs       cft_lzcone == the priority-loop cone it
#                               replaced, complete at each window width
#   negcontrol.sby              a deliberately broken property that MUST
#                               be refuted - a gate that cannot fail
#                               proves nothing, and this run discovered
#                               exactly that failure mode once already
#                               (a bind that silently dropped every
#                               assertion and "passed")
#
# VACUITY IS CHECKED TWICE, and the second check is the general one.
#
# Before any proof runs, a preflight elaborates the five single-file
# harnesses and counts their assertion cells, because the frontend's
# failure mode for unsupported constructs is silence, not an error.
# That check cannot cover mulexact.sby, whose model only exists after a
# flatten, a cutpoint and a set of `connect` commands; mirroring those
# in a second script would be a copy to drift.
#
# So EVERY task, old and new, is also checked after it runs, on the
# model sby itself built and solved: <workdir>/model/design_prep.il is
# the netlist handed to the engine, and its $assert and $cover cells are
# counted against a stated minimum. A task whose checks were silently
# dropped fails the gate even if the engine said pass. The minimums are
# minimums, not exact counts, so adding a property never breaks the
# gate - the guarded failure mode is wholesale silent loss.

set -u

# --- find ourselves, and a toolchain -------------------------------------
if ! command -v sby >/dev/null 2>&1; then
    if command -v docker >/dev/null 2>&1; then
        repo=$(cd -- "$(dirname -- "$0")/.." && { pwd -W 2>/dev/null || pwd; })
        echo "sby not on PATH - re-running inside the cft-formal image"
        MSYS_NO_PATHCONV=1 exec docker run --rm -v "$repo:/work" -w /work \
            cft-formal ./formal/run.sh "$@"
    fi
    echo "FATAL: neither sby nor docker is available" >&2
    exit 1
fi

cd -- "$(dirname -- "$0")" || exit 1

echo "== toolchain =="
yosys --version
sby --version
echo "bitwuzla $(bitwuzla --version)"
echo

# --- vacuity preflight ---------------------------------------------------
# read commands mirror each .sby's [script]; the count is of $check
# cells with FLAVOR=assert after prep. mulexact.sby is not here on
# purpose - see the header, and the per-task model check below, which
# covers it and these four alike.
declare -i preflight_bad=0

vacuity() { # label, top, min_asserts, files...
    local label=$1 top=$2; local -i want=$3; shift 3
    local -i got
    # not -q: quiet mode suppresses the very "N objects." line this parses
    got=$(yosys -p "read_verilog -formal -sv $*; prep -top $top; select -count t:\$check r:FLAVOR=assert %i" 2>&1 \
          | sed -n 's/^\([0-9]\+\) objects.*/\1/p' | tail -1)
    if [ "${got:-0}" -ge "$want" ]; then
        printf 'preflight  %-12s %d assertion cells in the model (>= %d)\n' "$label" "$got" "$want"
    else
        printf 'preflight  %-12s VACUOUS: %s assertion cells, expected >= %d\n' "$label" "${got:-0}" "$want"
        preflight_bad+=1
    fi
}

vacuity fifo       tb_fifo_formal      3 ../rtl/cft_fifo.sv tb_fifo_formal.sv
vacuity seedop     tb_seedop_formal   11 ../rtl/cft_seedop.sv tb_seedop_formal.sv
vacuity equiv      tb_simpleops_equiv  3 ../rtl/cft_simpleops.sv ../tb/wrappers/cft_simpleops_ref.sv tb_simpleops_equiv.sv
vacuity lzcone     tb_lzcone_equiv     3 -I ../rtl ../rtl/cft_fpfma_pipe.sv cft_lzcone_ref.sv tb_lzcone_equiv.sv
vacuity negcontrol tb_negcontrol_formal 1 ../rtl/cft_fifo.sv tb_negcontrol_formal.sv

if [ "$preflight_bad" -ne 0 ]; then
    echo
    echo "GATE BROKEN: a harness elaborated without its assertions."
    exit 1
fi
echo

# --- the proofs ----------------------------------------------------------
declare -i bad=0 total=0
verdicts=""

note() { verdicts="${verdicts}$1
"; }

# How many $assert plus $cover cells survived into the model sby solved.
# design_prep.il is the netlist the engine is handed: prep drops the
# checks that the mode does not use (bmc keeps asserts, cover keeps
# covers), so the two are counted together and compared to one minimum.
model_checks() { # workdir -> prints the count, or nothing if no model
    local il="$1/model/design_prep.il"
    [ -f "$il" ] || return 1
    grep -c 'cell \$assert\|cell \$cover' "$il"
}

run_proof() { # sbyfile, task (may be empty), min_checks, detail
    local sbyfile=$1 task=$2 detail=$4
    local -i want=$3
    local -i t0 t1 rc n
    total+=1
    t0=$(date +%s)
    sby -f "$sbyfile" $task >/dev/null 2>&1
    rc=$?
    t1=$(date +%s)
    local dir=${sbyfile%.sby}${task:+_$task}
    local label="$sbyfile${task:+ $task}"
    if [ $rc -ne 0 ]; then
        note "$(printf 'FAIL  %-22s %-38s %4ds' "$label" "$detail" $((t1 - t0)))"
        bad+=1
        echo "---- $dir/logfile.txt (tail) ----"
        tail -15 "$dir/logfile.txt" 2>/dev/null
        echo "---------------------------------"
        return
    fi
    n=$(model_checks "$dir" || echo 0)
    if [ "$n" -lt "$want" ]; then
        note "$(printf 'FAIL  %-22s %-38s %4ds' "$label" "VACUOUS: $n checks in the model, want >= $want" $((t1 - t0)))"
        bad+=1
        return
    fi
    note "$(printf 'PASS  %-22s %-38s %4ds' "$label" "$detail" $((t1 - t0)))"
}

run_proof fifo.sby     prove  3 "cft_fifo contract, unbounded (abc pdr)"
run_proof fifo.sby     cover  8 "cft_fifo control shapes reachable"
run_proof seedop.sby   check 11 "cft_seedop routing, all 2^40 inputs"
run_proof seedop.sby   cover 12 "cft_seedop operand classes reachable"
run_proof equiv.sby    check  3 "cft_simpleops == frozen ref (op != 26,27,30)"
run_proof equiv.sby    cover  6 "carve-out neighbours reachable"

# cft_lzcone against formal/cft_lzcone_ref.sv, the priority-loop cone
# frozen at the moment of the split (2026-09-07). Both combinational,
# so one BMC step is the whole input space at each window width.
run_proof lzcone.sby   fp32   3 "cft_lzcone == frozen cone, 78-bit window"
run_proof lzcone.sby   fp64   3 "cft_lzcone == frozen cone, 165-bit window"
run_proof lzcone.sby   fp128  3 "cft_lzcone == frozen cone, 345-bit window"
run_proof lzcone.sby   fp256  3 "cft_lzcone == frozen cone, 717-bit window"

# NOT IN THE GATE: imul.sby (IMUL, opcode 30, 2026-09-07). Its `value`
# task - the three 16x16 partial products against one 32x32 multiply,
# truncated - ran twenty-six minutes under bitwuzla without returning,
# and its `check` task - the decode, the zero extension and the 32-bit
# rule as a self-miter over the bits it must ignore - ran thirty
# minutes for the integrator and two and a half hours inside this gate
# on the merged tree without returning either. A miter over a
# multiplier is what a bit-blasting engine does worst at. Until one
# closes, IMUL's value rests on tb/test_simpleops.py's test_imul (6,225
# operand pairs at four rungs against the golden model) and
# host/tests/seq_check.py's differential; the harness and the .sby
# stay in the tree. `sby -f imul.sby check` or `value` to try again.

# cft_mulpass, at CFT_MUL_MCH = 24 - the chunk the tile synthesises -
# for all seven (P, COLS) pairs cft_lanes can build. Lemma A (fold) is
# one assertion; lemma B/C (sel) is NC + 2 + (COLS > 1 ? COLS : 0), which
# is the count each geometry's harness elaborates. See mulexact.sby.
run_proof mulexact.sby fold_53c2   1 "fp64 x2:  fold exact (P=53,C=2)"
run_proof mulexact.sby sel_53c2    6 "fp64 x2:  operands and columns"
run_proof mulexact.sby fold_53c1   1 "fp64 x5:  fold exact (P=53,C=1)"
run_proof mulexact.sby sel_53c1    3 "fp64 x5:  operands and columns"
run_proof mulexact.sby fold_113c3  1 "fp128 x2: fold exact (P=113,C=3)"
run_proof mulexact.sby sel_113c3   9 "fp128 x2: operands and columns"
run_proof mulexact.sby fold_113c1  1 "fp128 x5: fold exact (P=113,C=1)"
run_proof mulexact.sby sel_113c1   3 "fp128 x5: operands and columns"
run_proof mulexact.sby fold_237c5  1 "fp256 x2: fold exact (P=237,C=5)"
run_proof mulexact.sby sel_237c5  15 "fp256 x2: operands and columns"
run_proof mulexact.sby fold_237c2  1 "fp256 x5: fold exact (P=237,C=2)"
run_proof mulexact.sby sel_237c2   6 "fp256 x5: operands and columns"
run_proof mulexact.sby fold_237c1  1 "fp256 x10: fold exact (P=237,C=1)"
run_proof mulexact.sby sel_237c1   3 "fp256 x10: operands and columns"
run_proof mulexact.sby cover_fold  2 "fold claim reached, product non-zero"
run_proof mulexact.sby cover_sel   4 "every pass selection reached"

# The SINGLE-PROPERTY form of the same claim, where it closes.
# mulexact.sby proves exactness by splitting it into lemmas and
# composing them in prose; these assert the whole thing in one place -
# the module's output against the pipe's own column-sum expression,
# both multipliers standing, no lemmas - so the composition argument has
# an independent check under it. Four of the seven geometries close
# this way, including fp256 at MUL_PASSES=10, the deepest the tile
# builds. The engine here is boolector, not the bitwuzla the rest of
# this directory uses: on this property they are not close, and
# docs/VALIDATION.md's 2026-09-07 entry has the measurement.
run_proof mulpass_real.sby p53c2   1 "fp64 x2:  whole claim, one property"
run_proof mulpass_real.sby p53c1   1 "fp64 x5:  whole claim, one property"
run_proof mulpass_real.sby p113c1  1 "fp128 x5: whole claim, one property"
run_proof mulpass_real.sby p237c1  1 "fp256 x10: whole claim, one property"

# NOT IN THE GATE: mulpass_real.sby's other five tasks - p113c3,
# p237c2, p237c5 and the two sub-tile shapes - which do not return
# inside a wall bound; and formal/mulpass.sby, the same single property
# at a NARROWED chunk (CFT_MUL_MCH_FORMAL=4), which is not the tile's
# arithmetic. Both are measured in the 2026-09-07 entry, with the step
# each stalls on. mulexact.sby covers every one of those geometries at
# the real chunk, which is what the gate certifies.

# --- the negative control ------------------------------------------------
# expect fail in negcontrol.sby means: rc 0 == the broken property was
# refuted (required), rc != 0 == it was NOT refuted, i.e. the gate has
# stopped being able to catch a real bug. The logfile is checked too,
# so an sby that errored out cannot masquerade as a refutation, and the
# model is checked for its assertion the same way every proof is.
total+=1
t0=$(date +%s)
sby -f negcontrol.sby >/dev/null 2>&1
rc=$?
t1=$(date +%s)
ncchecks=$(model_checks negcontrol || echo 0)
if [ $rc -eq 0 ] && grep -q 'DONE (FAIL, rc=0)' negcontrol/logfile.txt 2>/dev/null \
   && [ "$ncchecks" -ge 1 ]; then
    note "$(printf 'PASS  %-22s %-38s %4ds' "negcontrol.sby" "broken property refuted, as required" $((t1 - t0)))"
else
    note "$(printf 'FAIL  %-22s %-38s %4ds' "negcontrol.sby" "BROKEN PROPERTY NOT REFUTED - dead gate" $((t1 - t0)))"
    bad+=1
    echo "---- negcontrol/logfile.txt (tail) ----"
    tail -15 negcontrol/logfile.txt 2>/dev/null
    echo "---------------------------------------"
fi

# --- verdicts ------------------------------------------------------------
echo
echo "== formal gate verdicts =="
printf '%s' "$verdicts"
echo
if [ "$bad" -ne 0 ]; then
    echo "FORMAL GATE: FAIL ($bad of $total)"
    exit 1
fi
echo "FORMAL GATE: PASS ($total of $total, negative control refuted)"
