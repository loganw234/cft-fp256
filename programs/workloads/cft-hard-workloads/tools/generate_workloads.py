#!/usr/bin/env python3
"""Deterministically regenerate sources, rational inputs, and the catalog."""
from pathlib import Path
import hashlib
import json
from models import CONFIGS, define, lit

ROOT=Path(__file__).resolve().parents[1]


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not isinstance(data,str):data=json.dumps(data,indent=2,sort_keys=True)+"\n"
    path.write_bytes(data.encode("utf-8"))


def main():
    cases=[]
    for tier,fmt in [("hard","fp64"),("extended","fp64"),("wide","fp256")]:
        for family in CONFIGS:
            case,source,rows=define(family,tier,fmt)
            rel=f"programs/{case['id']}.cftl";inputs=f"inputs/{case['id']}.json"
            write(ROOT/rel,source)
            write(ROOT/inputs,{"layout":case["state"],"lanes":case["lane"],
                              "rows":[dict(name=r["name"],state=[lit(v) for v in r["state"]],
                                           lane_params=[lit(v) for v in r["lane_params"]]) for r in rows]})
            case.update(file=rel,source_sha256=hashlib.sha256(source.encode()).hexdigest(),inputs=inputs,
                        input_sha256=hashlib.sha256((ROOT/inputs).read_bytes()).hexdigest(),
                        sha256=hashlib.sha256(source.encode()).hexdigest(),
                        reference=f"reference/{case['id']}.json",
                        allowed_target_refusals=["scratch-capacity","program-capacity","target-format","target-feature"])
            cases.append(case)
    write(ROOT/"catalog.json",{"suite":"cft-hard-workloads","version":1,"cases":cases,
                              "language_spec_sha256":"ab70205f3e026770fb5e655b3f86c96218a283f2b547ad587ae5b0ef1a4a9c68",
                              "smoke_order":[c["id"] for c in cases if c["tier"]=="hard"],
                              "refusal_names":["scratch-capacity","program-capacity","loader-bound","target-format",
                                               "target-feature","segment-steps","halving-underflow","bank-capacity",
                                               "too-deep","unused","h-nonlinear","h-scope","syntax","graph-format"]})
    index=["# Programs","",
           "All sources are intended to be accepted. Capacity refusals are recorded separately.",
           "The wide cases repeat the hard geometry at fp256. Larger grids increase domain size at fixed spacing.","",
           "| ID | State values/lane | Integrator | Long run steps |",
           "|---|---:|---|---:|"]
    for c in cases:
        index.append(f"| [{c['id']}]({c['file']}) | {c['n_state']} | {c['integrator']} | {c['long_steps']} |")
    write(ROOT/"PROGRAMS.md","\n".join(index)+"\n")
    print(f"Generated {len(cases)} sources and their exact rational initial conditions.")


if __name__=="__main__":main()
