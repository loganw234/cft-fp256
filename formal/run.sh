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
# The gate is four proofs and a tripwire, in this order:
#
#   fifo.sby      prove+cover   cft_fifo contract, unbounded (pdr)
#   seedop.sby    check+cover   cft_seedop special-case routing
#   equiv.sby     check+cover   cft_simpleops == frozen pre-rewrite ref
#   negcontrol.sby              a deliberately broken property that MUST
#                               be refuted - a gate that cannot fail
#                               proves nothing, and this run discovered
#                               exactly that failure mode once already
#                               (a bind that silently dropped every
#                               assertion and "passed")
#
# Before any proof runs, a vacuity preflight elaborates each model and
# counts its assertion cells: at least the number the harness source
# declares must survive into the netlist, because the frontend's
# failure mode for unsupported constructs is silence, not an error.

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
# cells with FLAVOR=assert after prep. Thresholds are minimums, not
# exact counts, so adding a property never breaks the preflight - the
# guarded failure mode is wholesale silent loss.
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
vacuity negcontrol tb_negcontrol_formal 1 ../rtl/cft_fifo.sv tb_negcontrol_formal.sv

if [ "$preflight_bad" -ne 0 ]; then
    echo
    echo "GATE BROKEN: a harness elaborated without its assertions."
    exit 1
fi
echo

# --- the proofs ----------------------------------------------------------
declare -i bad=0
verdicts=""

note() { verdicts="${verdicts}$1
"; }

run_proof() { # label, sbyfile, task (may be empty), detail
    local label=$1 sbyfile=$2 task=$3 detail=$4
    local -i t0 t1 rc
    t0=$(date +%s)
    sby -f "$sbyfile" $task >/dev/null 2>&1
    rc=$?
    t1=$(date +%s)
    local dir=${sbyfile%.sby}${task:+_$task}
    if [ $rc -eq 0 ]; then
        note "$(printf 'PASS  %-22s %-38s %4ds' "$sbyfile${task:+ $task}" "$detail" $((t1 - t0)))"
    else
        note "$(printf 'FAIL  %-22s %-38s %4ds' "$sbyfile${task:+ $task}" "$detail" $((t1 - t0)))"
        bad+=1
        echo "---- $dir/logfile.txt (tail) ----"
        tail -15 "$dir/logfile.txt" 2>/dev/null
        echo "---------------------------------"
    fi
}

run_proof fifo   fifo.sby   prove "cft_fifo contract, unbounded (abc pdr)"
run_proof fifo   fifo.sby   cover "cft_fifo control shapes reachable"
run_proof seedop seedop.sby check "cft_seedop routing, all 2^40 inputs"
run_proof seedop seedop.sby cover "cft_seedop operand classes reachable"
run_proof equiv  equiv.sby  check "cft_simpleops == frozen ref (op != 26,27)"
run_proof equiv  equiv.sby  cover "carve-out neighbours reachable"

# --- the negative control ------------------------------------------------
# expect fail in negcontrol.sby means: rc 0 == the broken property was
# refuted (required), rc != 0 == it was NOT refuted, i.e. the gate has
# stopped being able to catch a real bug. The logfile is checked too,
# so an sby that errored out cannot masquerade as a refutation.
t0=$(date +%s)
sby -f negcontrol.sby >/dev/null 2>&1
rc=$?
t1=$(date +%s)
if [ $rc -eq 0 ] && grep -q 'DONE (FAIL, rc=0)' negcontrol/logfile.txt 2>/dev/null; then
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
    echo "FORMAL GATE: FAIL ($bad of 7)"
    exit 1
fi
echo "FORMAL GATE: PASS (7 of 7, negative control refuted)"
