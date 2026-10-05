# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Print the U50's sequencer capacities as cft_seq generics.

Since revision 7 (2026-09-29) rtl/cft_krnl.sv declares SEQ_MAXD,
SEQ_IMEM_D and SEQ_SCRATCH_D as parameters whose defaults are the U50's,
and nothing else writes those numbers down; revision 8 (R8S) added
SEQ_STREAM_D, the instruction capacity, beside SEQ_IMEM_D, which became
the store's depth. tb/Makefile's seq_coreu50
runs the unit bench (tb/test_seq_core.py) against cft_seq built at them:
it takes this script's one line, hands each word to the simulator as
-Pcft_seq.<word> and the whole line to the bench as CFT_GENERICS - so a
change to the kernel's defaults moves the bench with it, and the two can
never be told different numbers.

    $ python tb/krnl_caps.py
    MAXD=1024 IMEM_D=4096 SCRATCH_D=2048 STREAM_D=16777216 EN_AUGADD=1

Since R21's decode (revision 8's round 2) it also prints EN_AUGADD, the
build parameter that says whether R21 is built, so seq_coreu50's cft_seq
decodes codes 10 and 11 exactly when the U50's kernel does.

Exits non-zero, naming the parameter, if the kernel stops declaring one.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "rtl" / "cft_krnl.sv"


def main():
    src = SRC.read_text(encoding="utf-8")
    words = []
    for krnl, own in (("SEQ_MAXD", "MAXD"), ("SEQ_IMEM_D", "IMEM_D"),
                      ("SEQ_SCRATCH_D", "SCRATCH_D"),
                      ("SEQ_STREAM_D", "STREAM_D")):
        m = re.search(r"^\s*parameter\s+int\s+%s\s*=\s*(\d+)\s*[,)]" % krnl,
                      src, re.MULTILINE)
        if not m:
            sys.exit(f"krnl_caps.py: {SRC.name} declares no "
                     f"`parameter int {krnl}`")
        words.append(f"{own}={m.group(1)}")
    m = re.search(r"^\s*parameter\s+bit\s+EN_AUGADD\s*=\s*1'b([01])",
                  src, re.MULTILINE)
    if not m:
        sys.exit(f"krnl_caps.py: {SRC.name} declares no "
                 f"`parameter bit EN_AUGADD`")
    words.append(f"EN_AUGADD={m.group(1)}")
    print(" ".join(words))


if __name__ == "__main__":
    main()
