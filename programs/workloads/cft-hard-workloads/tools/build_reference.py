#!/usr/bin/env python3
"""Generate exact one-step vectors independently of cft_golden and cftc."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time
from exact_oracle import FiniteOracle, FORMATS, spelling
from subset_oracle import Source

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--only")
    args=p.parse_args()
    catalog=json.loads((ROOT/"catalog.json").read_bytes());summary=[]
    for case in catalog["cases"]:
        if args.only and args.only not in case["id"]:continue
        start=time.perf_counter();source=Source((ROOT/case["file"]).read_text(encoding="ascii"))
        inp=json.loads((ROOT/case["inputs"]).read_bytes())
        states=[];lanes=[];out=[];lane_flags=[]
        for row in inp["rows"]:
            oracle=FiniteOracle(case["format"])
            y=[oracle.constant(Fraction(v)) for v in row["state"]]
            lp=[Fraction(v) for v in row["lane_params"]]
            states.append([spelling(v,case["format"]) for v in y])
            lanes.append([spelling(oracle.constant(v),case["format"]) for v in lp])
            result=source.step(y,lp,oracle)
            out.append([spelling(v,case["format"]) for v in result])
            lane_flags.append(oracle.flags)
        flags=0
        for f in lane_flags:flags|=f
        ref=dict(id=case["id"],source_sha256=case["source_sha256"],input_sha256=case["input_sha256"],
                 format_layout=dict(zip(("width","exponent_bits","fraction_bits"),FORMATS[case["format"]])),
                 request={"steps":1,"states":states,"lane_params":lanes},
                 expected={"states":out,"flags":flags},expected_lane_flags=lane_flags,
                 independent_field_operations=len(source.nodes),independent_step_operations=source.step_operations,
                 runtime_operations=dict(Counter(n[0] for n in source.nodes)),
                 generator="Independent source subset parser and integer/Fraction IEEE rounding; no CFT imports.")
        path=ROOT/"reference"/(case["id"]+".json")
        path.write_bytes((json.dumps(ref,indent=2,sort_keys=True)+"\n").encode())
        summary.append(dict(id=case["id"],field_operations=len(source.nodes),
                            step_operations=source.step_operations,seconds=round(time.perf_counter()-start,3),
                            reference_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),lane_flags=lane_flags))
        print(case["id"],source.step_operations,"ops/step",summary[-1]["seconds"],"seconds",flush=True)
    if not args.only:
        (ROOT/"evidence"/"reference-build.json").write_bytes((json.dumps(summary,indent=2)+"\n").encode())


if __name__=="__main__":main()
