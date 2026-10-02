#!/usr/bin/env python3
"""Compile and execute substantial workloads using the returned CFT APIs.

Default: seven hard fp64 cases, exact one-step gates, 8-step differential
execution, and monolithic-vs-segmented comparison. Long runs are explicit.
Only Python's standard library is needed in addition to the CFT checkout.
"""
import argparse
from collections import Counter
from decimal import Decimal as D, localcontext
from fractions import Fraction as Q
import importlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback
from diagnostics import measure, differences, strings, state_digest
from exact_oracle import decode, floor_log2, power2, round_exact, spelling, FORMATS

ROOT=Path(__file__).resolve().parents[1]
CAPACITIES={"scratch-capacity","program-capacity","target-format","target-feature"}


def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=obj if isinstance(obj,str) else json.dumps(obj,indent=2,sort_keys=True)+"\n"
    path.write_bytes(data.encode("utf-8"))


def normalize(result,case):
    width=FORMATS[case["format"]][0]
    rows=[]
    for lane in result["states"]:
        if len(lane)!=case["n_state"]:raise AssertionError("wrong output state shape")
        row=[]
        for v in lane:
            b=int(v,0) if isinstance(v,str) else v
            if type(b) is not int or not 0<=b<(1<<width):raise AssertionError("invalid state encoding")
            row.append(spelling(b,case["format"]))
        rows.append(row)
    flags=result["flags"]
    if type(flags) is not int or not 0<=flags<32:raise AssertionError("invalid FLAGS value")
    return {"states":rows,"flags":flags}


def compare(a,b,label):
    if a["flags"]!=b["flags"]:raise AssertionError(label+": FLAGS differ")
    if len(a["states"])!=len(b["states"]):raise AssertionError(label+": lane count differs")
    for lane,(x,y) in enumerate(zip(a["states"],b["states"])):
        if x!=y:
            i=next(i for i,(u,v) in enumerate(zip(x,y)) if u!=v)
            raise AssertionError(f"{label}: lane {lane}, component {i}: {x[i]} != {y[i]}")


def execute(backend,graph,case,states,lp,steps,h=None):
    req={"states":states,"lane_params":lp,"steps":steps}
    if h is not None:req["h"]=str(h)
    start=time.perf_counter()
    result=normalize(backend.run(graph,req),case)
    if len(result["states"])!=len(states):raise AssertionError("wrong output lane count")
    return result,time.perf_counter()-start


def verify_format(graph,case):
    # Infer layout from the actual checker's encoding of 1; do not silently
    # assume this implementation's binary256 exponent convention.
    K=importlib.import_module("cft_golden.lang.constants")
    one=K.round_once(graph.fmt,graph.rnd,Q(1))[0]
    fraction_bits=(one & -one).bit_length()-1
    actual=(graph.fmt.width,graph.fmt.width-fraction_bits-1,fraction_bits)
    if actual!=FORMATS[case["format"]]:raise AssertionError(f"format layout differs: {actual}")
    # Independent checks of graph constants/defaults under the source's RNE.
    for value,factor,bits,flags in graph.const:
        if round_exact(value,case["format"],"rne")!=(bits,flags):
            raise AssertionError("graph constant rounding differs from the independent oracle")
    for name,value,bits,flags in graph.param:
        if round_exact(value,case["format"],"rne")!=(bits,flags):
            raise AssertionError("parameter default rounding differs for "+name)


def canonical(backend,graph,case,out):
    text=backend.lang.render_canonical(graph)
    write(out/"checked.canonical.cftl",text)
    again=backend.lang.compile_text(text,case["id"]+".canonical.cftl").graph
    if again.to_bytes()!=graph.to_bytes():raise AssertionError("canonical readback changed graph")
    if backend.lang.render_canonical(again)!=text:raise AssertionError("canonical text not a fixed point")
    write(out/"checked.graph.json",graph.to_bytes().decode("ascii"))


def emit(case,args,out):
    directory=out/"artifacts";directory.mkdir(parents=True)
    argv=[sys.executable,str(Path(args.repo)/"python"/"cftc"),str(ROOT/case["file"]),
          "--steps","1","--target",args.target,"--out",str(directory)]
    print("COMPILING",case["id"],flush=True);start=time.perf_counter()
    try:
        done=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=args.timeout)
    except subprocess.TimeoutExpired as exc:
        (out/"compiler.stdout.txt").write_bytes(exc.stdout or b"")
        (out/"compiler.stderr.txt").write_bytes(exc.stderr or b"")
        row={"argv":argv,"verdict":"TIMEOUT","seconds":time.perf_counter()-start}
        write(out/"compilation.json",row)
        return row
    (out/"compiler.stdout.txt").write_bytes(done.stdout);(out/"compiler.stderr.txt").write_bytes(done.stderr)
    row={"argv":argv,"returncode":done.returncode,"seconds":time.perf_counter()-start,
         "source_sha256":case["source_sha256"],
         "artifacts":{f.relative_to(directory).as_posix():hashlib.sha256(f.read_bytes()).hexdigest()
                      for f in sorted(directory.rglob("*")) if f.is_file()}}
    msg=(done.stdout+b"\n"+done.stderr).decode("utf-8",errors="replace")
    if done.returncode==70 or "cftc: internal error" in msg:
        row["verdict"]="INTERNAL-ERROR"
    elif done.returncode==0:
        missing=[s for s in ("graph.json","cftp","manifest.json") if not list(directory.glob("*."+s))]
        row["verdict"]="FAIL" if missing else "PASS"
        if missing:row["missing_artifacts"]=missing
    elif done.returncode<0 or done.returncode>=0xC0000000:row["verdict"]="CRASH"
    else:
        refusals=[n for n in CAPACITIES if re.search(r"(?<![a-z0-9_-])"+n+r"(?![a-z0-9_-])",msg)]
        row["verdict"]="TARGET-LIMIT" if refusals else "FAIL"
        row["capacity_refusals"]=refusals
    write(out/"compilation.json",row)
    return row


def rescale_tangents(case,states):
    """Exact binary rescaling of tangent inputs between program segments.

    Each vector's largest magnitude becomes [1,2). This avoids overflow in
    long instability runs. These external operations are logged separately
    and do NOT contribute to program FLAGS. No QR orthogonalization is done.
    """
    if case["family"]!="lorenz_tangent":return states,[]
    k,j,r=(case["shape"][x] for x in ("k","j","vectors"));dim=k*(j+1)
    answer=[list(v) for v in states];powers=[]
    for a,row in enumerate(states):
        exps=[]
        for v in range(r):
            lo=(v+1)*dim;hi=(v+2)*dim
            values=[decode(int(b,0),case["format"]) for b in row[lo:hi]]
            maximum=max(abs(x) for x in values)
            e=floor_log2(maximum) if maximum else 0;exps.append(e)
            for i,(b,x) in enumerate(zip(row[lo:hi],values),lo):
                sign=int(b,0)>>(FORMATS[case["format"]][0]-1)
                bit,flag=round_exact(x*power2(-e),case["format"],zero_sign=sign)
                if flag:raise ArithmeticError("external tangent scaling lost exactness")
                answer[a][i]=spelling(bit,case["format"])
        powers.append(exps)
    return answer,powers


def flip_momenta(case,states):
    mask=1<<(FORMATS[case["format"]][0]-1);n=case["n_state"]//2
    return [row[:n]+[spelling(int(b,0)^mask,case["format"]) for b in row[n:]] for row in states]


def checkpoint(case,result,initial_metrics,step):
    metrics=[measure(case,row) for row in result["states"]]
    with localcontext() as ctx:
        ctx.prec=90
        for m,base in zip(metrics,initial_metrics):
            if m["nonfinite"]:continue
            for key in ("energy","total_momentum","mean","mean_position","oscillator_invariant"):
                if key in m and key in base:
                    change=D(m[key])-D(base[key]);m[key+"_change"]=str(change)
                    if key in ("energy","oscillator_invariant") and D(base[key])!=0:
                        m[key+"_relative_change"]=str(change/abs(D(base[key])))
    return dict(step=step,flags=result["flags"],state_sha256=state_digest(result["states"]),metrics=metrics)


def run_case(case,args,backend,golden,caseout,journal):
    phase="source"
    compilation=emit(case,args,caseout) if not args.no_emit else None
    if compilation and compilation["verdict"]!="PASS":
        return dict(id=case["id"],verdict=compilation["verdict"],phase="compiler CLI")
    if args.compile_only:return dict(id=case["id"],verdict="COMPILED",phase="compiler CLI")
    graph=backend.load_source(ROOT/case["file"])
    if graph.n_state!=case["n_state"]:raise AssertionError("source layout changed")
    verify_format(graph,case)
    canonical(backend,graph,case,caseout)
    if compilation:
        file=next((caseout/"artifacts").glob("*.graph.json"))
        if file.read_bytes()!=graph.to_bytes():raise AssertionError("CLI graph differs from loaded source graph")
    ref=json.loads((ROOT/case["reference"]).read_bytes())
    if ref["source_sha256"]!=case["source_sha256"] or ref["input_sha256"]!=case["input_sha256"]:
        raise AssertionError("reference vector belongs to different source/inputs")
    request=ref["request"];initial=request["states"];lp=request["lane_params"]
    initial_metrics=[measure(case,row) for row in initial]
    write(caseout/"initial.json",dict(states=initial,lane_params=lp,metrics=initial_metrics))
    phase="independent one-step oracle"
    first,seconds=execute(backend,graph,case,initial,lp,1)
    compare(first,ref["expected"],phase)
    gfirst,gseconds=execute(golden,graph,case,initial,lp,1)
    compare(gfirst,ref["expected"],"golden against independent one-step oracle")
    initial_row=dict(id=case["id"],phase=phase,verdict="PASS",compiled_seconds=seconds,golden_seconds=gseconds)
    journal(initial_row);print("ORACLE PASS",case["id"],flush=True)
    total=8 if args.profile=="verify" else case[args.profile+"_steps"]
    if args.steps is not None:total=args.steps
    if total<1:raise ValueError("steps must be positive")
    states=initial;golden_states=initial;flags=gflags=0;at=0
    history=[];exponents=[[0]*case["shape"].get("vectors",0) for _ in states]
    while at<total:
        # Short endpoints 1,2,4,8; later chunks never exceed the requested
        # chunk size. Long runs compare both backends when --compare-all.
        stop=min(total,(1 if at==0 else 2*at) if at<8 else at+args.chunk)
        count=stop-at
        if at==0:actual,secs=first,seconds
        else:actual,secs=execute(backend,graph,case,states,lp,count)
        differential=args.profile=="verify" or args.compare_all or stop<=8
        if differential:
            expected,gsecs=(gfirst,gseconds) if at==0 else execute(golden,graph,case,golden_states,lp,count)
            compare(actual,expected,f"segment {at}..{stop}")
            golden_states=expected["states"];gflags|=expected["flags"]
        flags|=actual["flags"];at=stop;states=actual["states"]
        row=checkpoint(case,dict(states=states,flags=flags),initial_metrics,at)
        row.update(id=case["id"],phase="evolution",segment_steps=count,
                   verdict="PASS",exact_backend_comparison=differential,compiled_seconds=secs)
        if any(m["nonfinite"] for m in row["metrics"]):
            row["verdict"]="MODEL-NONFINITE";journal(row)
            raise ArithmeticError("the actual numerical trajectory became nonfinite")
        # Full snapshots at powers of two and at the end; every chunk gets
        # metrics and a digest. This keeps extended/endurance archives usable.
        if at&(at-1)==0 or at==total:
            write(caseout/"snapshots"/f"{at:08d}.json",dict(row,states=states))
        if case["family"]=="lorenz_tangent" and args.profile!="verify" and at>=8:
            row["output_tangent_scaling_power2"]=[x[:] for x in exponents]
            with localcontext() as ctx:
                ctx.prec=90
                horizon=D(at)*D(Q(case["h"]).numerator)/D(Q(case["h"]).denominator)
                rates=[]
                for a,m in enumerate(row["metrics"]):
                    lane=[]
                    for v,norm in enumerate(m["tangent_max"]):
                        initial_norm=D(initial_metrics[a]["tangent_max"][v])
                        norm=D(norm)
                        lane.append(None if not norm or not initial_norm else
                                    str((norm.ln()-initial_norm.ln()+D(exponents[a][v])*D(2).ln())/horizon))
                    rates.append(lane)
                row["finite_time_tangent_growth_rates"]=rates
            states,powers=rescale_tangents(case,states)
            if differential:golden_states=states
            for a,es in enumerate(powers):
                for v,e in enumerate(es):exponents[a][v]+=e
            row["external_tangent_scaling_power2"]=powers
            row["cumulative_tangent_scaling_power2"]=[x[:] for x in exponents]
            row["next_input_sha256"]=state_digest(states)
        history.append(row);journal(row)
        print("RUN",case["id"],at,"/",total,"FLAGS",flags,"compared" if differential else "compiled",flush=True)
    if args.profile=="verify":
        phase="monolithic versus segmented"
        whole,wsecs=execute(backend,graph,case,initial,lp,total)
        compare(whole,dict(states=states,flags=flags),phase)
        journal(dict(id=case["id"],phase=phase,steps=total,verdict="PASS",compiled_seconds=wsecs))
    probes={}
    if args.step_halving and case["integrator"]!="map":
        phase="step halving";s=case["halving_steps"];h=Q(case["h"]);ends=[]
        for divisor in (1,2,4):
            actual,secs=execute(backend,graph,case,initial,lp,s*divisor,h/divisor)
            if args.compare_all:
                expected,_=execute(golden,graph,case,initial,lp,s*divisor,h/divisor)
                compare(actual,expected,phase)
            write(caseout/"probes"/f"halving_{divisor}.json",dict(actual,steps=s*divisor,h=str(h/divisor),seconds=secs))
            ends.append(actual)
        probes["step_halving"]={"physical_horizon":str(s*h),
                               "h_vs_h2":[differences(case,a,b) for a,b in zip(ends[0]["states"],ends[1]["states"])],
                               "h2_vs_h4":[differences(case,a,b) for a,b in zip(ends[1]["states"],ends[2]["states"])]}
        journal(dict(id=case["id"],phase=phase,verdict="MEASURED",**probes["step_halving"]))
    if args.reversal and case["reversal_steps"]:
        phase="momentum reversal";s=case["reversal_steps"]
        forward,_=execute(backend,graph,case,initial,lp,s)
        backward,_=execute(backend,graph,case,flip_momenta(case,forward["states"]),lp,s)
        returned=flip_momenta(case,backward["states"])
        probes["momentum_reversal"]={"steps_each_way":s,
                                     "errors":[differences(case,a,b) for a,b in zip(initial,returned)]}
        write(caseout/"probes"/"reversal.json",dict(states=returned,flags=forward["flags"]|backward["flags"],**probes["momentum_reversal"]))
        journal(dict(id=case["id"],phase=phase,verdict="MEASURED",**probes["momentum_reversal"]))
    summary=dict(id=case["id"],verdict="PASS",steps=total,flags=flags,
                 differential_every_segment=args.profile=="verify" or args.compare_all,
                 one_step_independent_oracle=True,probes=probes,final=history[-1])
    write(caseout/"summary.json",summary)
    backend.clear_cache()
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",default=os.environ.get("CFT_REPO"),help="CFT checkout (or set CFT_REPO)")
    p.add_argument("--target",default=os.environ.get("CFT_TARGET","sw:32768"))
    p.add_argument("--tier",choices=("hard","extended","wide","all"),default="hard")
    p.add_argument("--only",help="regular expression on IDs")
    p.add_argument("--profile",choices=("verify","long","endurance"),default="verify")
    p.add_argument("--steps",type=int,help="override the profile's endpoint")
    p.add_argument("--chunk",type=int,default=128)
    p.add_argument("--compare-all",action="store_true",help="golden interpreter at every long-run segment")
    p.add_argument("--step-halving",action="store_true")
    p.add_argument("--reversal",action="store_true")
    p.add_argument("--compile-only",action="store_true")
    p.add_argument("--no-emit",action="store_true",help="skip CLI artifacts, still compile live images for execution")
    p.add_argument("--timeout",type=float,default=600)
    p.add_argument("--out",default="hard-results",help="parent for a new, uniquely named run directory")
    args=p.parse_args()
    if not args.repo:p.error("--repo or CFT_REPO is required")
    if not (Path(args.repo)/"python"/"cftc").is_file():p.error("checkout has no python/cftc")
    if args.chunk<1 or args.timeout<=0:p.error("chunk and timeout must be positive")
    if args.compile_only and args.no_emit:p.error("--compile-only cannot use --no-emit")
    if args.steps is not None and args.steps<1:p.error("steps must be positive")
    os.environ["CFT_REPO"]=str(Path(args.repo).resolve());os.environ["CFT_TARGET"]=args.target
    backend=importlib.import_module("compiled_adapter");golden=importlib.import_module("golden_adapter")
    catalog=json.loads((ROOT/"catalog.json").read_bytes())
    cases=[c for c in catalog["cases"] if (args.tier=="all" or c["tier"]==args.tier)
           and (not args.only or re.search(args.only,c["id"]))]
    if not cases:p.error("no cases selected")
    # Only hashes are used to identify the checkout; no compiler code is copied.
    try:
        git=subprocess.run(["git","-C",args.repo,"rev-parse","HEAD"],capture_output=True,text=True,timeout=10)
        revision=git.stdout.strip() if git.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):revision=None
    run=Path(args.out).resolve()/("run-"+time.strftime("%Y%m%d-%H%M%S",time.gmtime())+"-"+str(time.time_ns()%1000000000))
    run.mkdir(parents=True)
    write(run/"environment.json",dict(python=sys.version,platform=platform.platform(),revision=revision,
                                     target=args.target,args=vars(args),cases=[c["id"] for c in cases],
                                     catalog_sha256=hashlib.sha256((ROOT/"catalog.json").read_bytes()).hexdigest()))
    counts=Counter();summaries=[]
    with (run/"runtime-results.jsonl").open("w",encoding="utf-8",newline="\n",buffering=1) as log:
        def journal(row):log.write(json.dumps(row,sort_keys=True)+"\n")
        for case in cases:
            out=run/case["id"];out.mkdir()
            try:
                if hashlib.sha256((ROOT/case["file"]).read_bytes()).hexdigest()!=case["source_sha256"]:
                    raise AssertionError("source changed; regenerate references before running")
                if hashlib.sha256((ROOT/case["inputs"]).read_bytes()).hexdigest()!=case["input_sha256"]:
                    raise AssertionError("initial conditions changed; regenerate references before running")
                row=run_case(case,args,backend,golden,out,journal)
            except Exception as exc:
                name=backend.refusal_name(exc)
                row=dict(id=case["id"],verdict="TARGET-LIMIT" if name in CAPACITIES else "FAIL",
                         refusal=name,detail=repr(exc))
                write(out/"exception.txt",traceback.format_exc());backend.clear_cache()
            summaries.append(row);counts[row["verdict"]]+=1;journal(dict(row,phase="case result"))
            print(row["verdict"],case["id"],flush=True)
    write(run/"summary.json",dict(counts=dict(counts),cases=summaries))
    print(json.dumps(dict(counts),sort_keys=True));print("RESULT DIRECTORY",run)
    return int(any(counts[k] for k in ("FAIL","INTERNAL-ERROR","CRASH","TIMEOUT","MODEL-NONFINITE")))


if __name__=="__main__":raise SystemExit(main())
