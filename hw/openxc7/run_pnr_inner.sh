#!/bin/bash
# The openXC7 flow on cft_krnl's board configuration, inside cft-openxc7:
# the source tree read-only at /work, everything written under /pnr.
# Each stage leaves <stage>.log, <stage>.rc and <stage>.secs; the run stops
# at the first stage that fails, and a stage that did not run leaves no .rc.
set -u -o pipefail
cd /work || exit 1
P=/pnr
PART=xc7k325tffg900-2
DB=$PRJXRAY_DB_DIR/kintex7

stage() {  # <name> -- command...
  local name=$1; shift 2
  local t0=$(date +%s)
  echo "== $name: $*"
  "$@" > "$P/$name.log" 2>&1
  local rc=$?
  echo $rc > "$P/$name.rc"
  echo $(( $(date +%s) - t0 )) > "$P/$name.secs"
  echo "== $name rc=$rc in $(cat "$P/$name.secs") s"
  return $rc
}

# Every module in rtl/, globbed as hw/impl_krnl_ooc.tcl and
# hw/package_kernel.tcl do: the list this line held until 2026-09-23 had
# to be edited the day rtl/cft_imul.sv arrived, and a list nobody edits
# fails at hierarchy at best.
RTL=$(ls rtl/*.sv | tr '\n' ' ')

# -defer: elaborate once, at hierarchy, with the parameters the harness
# instantiates - not first at the defaults and again at the board's.
stage synth -- yosys -p "read_verilog -defer -sv -I rtl $RTL $P/cft_pnr_harness.sv; hierarchy -top cft_pnr_harness; synth_xilinx -flatten -abc9 -arch xc7 -top cft_pnr_harness; tee -o $P/stat.txt stat; tee -o $P/stat_tech.txt stat -tech xilinx; write_json $P/harness.json" \
  && stage pnr -- nextpnr-xilinx --chipdb "$CHIPDB/xc7k325tffg900.bin" --xdc "$P/cft_pnr_harness.xdc" \
       --json "$P/harness.json" --fasm "$P/harness.fasm" --freq 100 --timing-allow-fail \
       --report "$P/nextpnr_report.json" \
  && stage frames -- bash -c "fasm2frames --part $PART --db-root $DB $P/harness.fasm > $P/harness.frames" \
  && stage bit -- xc7frames2bit --part_file "$DB/$PART/part.yaml" --part_name "$PART" \
       --frm_file "$P/harness.frames" --output_file "$P/harness.bit"
rc=$?
[ -f "$P/harness.bit" ] && sha256sum "$P/harness.bit" > "$P/harness.bit.sha256"
exit $rc
