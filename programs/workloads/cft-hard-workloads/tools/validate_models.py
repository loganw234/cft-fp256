#!/usr/bin/env python3
"""Validate generated equations and run choices without a CFT installation.

Requires NumPy. This performs mathematical/source checks and independent
double simulations. It does not compile CFT or certify compiler acceptance.
"""
from collections import Counter
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import random
import struct
import time
import numpy as np
from exact_oracle import FORMATS, decode, round_exact
from models import define
import numpy_models as nm
from subset_oracle import Source

ROOT=Path(__file__).resolve().parents[1]


def max_nesting(text):
    d=best=0
    for line in text.splitlines():
        for c in line.split(";",1)[0]:
            if c in "([":d+=1;best=max(best,d)
            elif c in ")]":d-=1
            if d<0:raise AssertionError("unbalanced source")
    if d:raise AssertionError("unbalanced source")
    return best


def relative_difference(a,b):
    return float(np.max(np.abs(a-b))/max(1,float(np.max(np.abs(a))),float(np.max(np.abs(b)))))


def long_run(case,initial,lp):
    y=initial.copy();steps=case["long_steps"];start=time.perf_counter()
    maximum=0.0
    for at in range(0,steps,128):
        y=nm.advance(case,y,lp,min(128,steps-at))
        assert np.isfinite(y).all(),case["id"]+" nonfinite"
        maximum=max(maximum,float(np.max(np.abs(y))))
        if case["family"]=="lorenz_tangent":
            dim=case["shape"]["k"]*(case["shape"]["j"]+1)
            for v in range(case["shape"]["vectors"]):
                a=y[(v+1)*dim:(v+2)*dim];norm=np.max(np.abs(a))
                if norm:a/=2.0**int(np.floor(np.log2(norm)))
    result={"steps":steps,"elapsed_seconds":round(time.perf_counter()-start,3),
            "finite":True,"maximum_state_magnitude_seen":maximum,
            "final_rms":float(np.sqrt(np.mean(y*y))),
            "relative_state_change":relative_difference(y,initial)}
    f=case["family"]
    if f in ("fput","phi4"):
        e0=nm.energy(case,initial);e1=nm.energy(case,y)
        result.update(initial_energy=e0,final_energy=e1,relative_energy_drift=(e1-e0)/abs(e0))
    if f=="fput":result["momentum_change"]=float(np.sum(y[len(y)//2:])-np.sum(initial[len(initial)//2:]))
    if f=="kuramoto_sivashinsky":result["mean_change"]=float(y.mean()-initial.mean())
    if f=="gray_scott":
        m=case["shape"]["n"]**2;result.update(u_range=[float(y[:m].min()),float(y[:m].max())],
                                               v_range=[float(y[m:].min()),float(y[m:].max())],
                                               final_v_std=float(y[m:].std()))
    if f=="reservoir":
        d=case["shape"]["d"];q,p=y[-2:];h=float(Q(case["h"]))
        result.update(r_range=[float(y[:d].min()),float(y[:d].max())],r_std=float(y[:d].std()),
                      oscillator_invariant=q*q+p*p+h*q*p)
        assert np.max(np.abs(y[:d]))<=1+1e-12
    if f=="riccati":
        n=case["shape"]["n"];a=y.reshape(n,n)
        result.update(symmetry_residual=float(np.max(np.abs(a-a.T))),
                      smallest_symmetric_eigenvalue=float(np.linalg.eigvalsh((a+a.T)/2)[0]))
        assert result["smallest_symmetric_eigenvalue"]>0
    return y,result


def main():
    catalog=json.loads((ROOT/"catalog.json").read_bytes())
    rows=[]
    for case in catalog["cases"]:
        raw=(ROOT/case["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==case["source_sha256"]
        # Deterministic regeneration must reproduce exact bytes on any OS.
        again,source,inputs=define(case["family"],case["tier"],case["format"])
        assert source.encode("ascii")==raw
        assert max_nesting(source)<100
        checker=Source(source);assert len(checker.out)==case["n_state"]<=32768
        assert len(checker.lane)+case["n_state"]<=32768
        constants={r[1] for op,refs in checker.nodes for r in refs if r[0]=="c"}
        upper=len(constants)+len(checker.params)+8
        assert upper<=512
        data=json.loads((ROOT/case["inputs"]).read_bytes())
        assert hashlib.sha256((ROOT/case["inputs"]).read_bytes()).hexdigest()==case["input_sha256"]
        ref=json.loads((ROOT/case["reference"]).read_bytes())
        assert ref["source_sha256"]==case["source_sha256"] and ref["input_sha256"]==case["input_sha256"]
        error=0.0
        for row in data["rows"]:
            y=np.asarray([float(Q(v)) for v in row["state"]]);lp=[Q(v) for v in row["lane_params"]]
            actual=np.asarray(checker.evaluate(y,lp))
            expected=nm.map_step(case,y,lp) if case["integrator"]=="map" else nm.field(case,y,lp)
            err=relative_difference(actual,expected);error=max(error,err)
            assert err<1e-12,(case["id"],err)
        rows.append(dict(id=case["id"],state_values=case["n_state"],max_source_nesting=max_nesting(source),
                         bank_upper_bound=upper,source_vs_independent_math_relative_error=error,
                         field_operations=len(checker.nodes),step_operations=checker.step_operations))
        print("MATH PASS",case["id"],"relative field error",error,flush=True)
    rng=random.Random(20261002)
    rounding={}
    for fmt in FORMATS:
        n=0;sign=1<<(FORMATS[fmt][0]-1)
        for _ in range(300):
            x=Q(rng.randrange(1,1<<61),rng.randrange(1,1<<31))*Q(2)**rng.randrange(-64,65)
            b,flags=round_exact(x,fmt)
            v=decode(b,fmt);lo=(decode(b-1,fmt)+v)/2;hi=(v+decode(b+1,fmt))/2
            assert lo<=x<=hi
            if x in (lo,hi):assert b%2==0
            assert round_exact(-x,fmt)[0]==b^sign
            assert flags==(0 if x==v else 16)
            if fmt in ("fp32","fp64"):
                code="f" if fmt=="fp32" else "d";ucode="I" if fmt=="fp32" else "Q"
                host=struct.unpack(">"+ucode,struct.pack(">"+code,float(x)))[0]
                assert b==host
            n+=1
        rounding[fmt]=n
    extras={};longs={}
    for case in catalog["cases"]:
        if case["tier"]!="hard":continue
        data=json.loads((ROOT/case["inputs"]).read_bytes())["rows"][1]
        y=np.asarray([float(Q(x)) for x in data["state"]]);lp=[Q(x) for x in data["lane_params"]]
        f=case["family"]
        if f=="lorenz_tangent":
            k,j,r=(case["shape"][x] for x in ("k","j","vectors"));dim=k*(j+1)
            full=nm.field(case,y,lp);errors=[];eps=2.0**-18
            for v in range(r):
                t=y[(v+1)*dim:(v+2)*dim];plus=y.copy();minus=y.copy()
                plus[:dim]+=eps*t;minus[:dim]-=eps*t
                numeric=(nm.field(case,plus,lp)[:dim]-nm.field(case,minus,lp)[:dim])/(2*eps)
                err=relative_difference(numeric,full[(v+1)*dim:(v+2)*dim])
                errors.append(err);assert err<1e-7
            extras[f]={"centered_Jacobian_directional_errors":errors}
        if f in ("fput","phi4"):
            m=len(y)//2;direction=np.asarray([(i*11)%17-8 for i in range(m)])/32
            eps=2.0**-18;plus=y.copy();minus=y.copy()
            plus[:m]+=eps*direction;minus[:m]-=eps*direction
            numeric=(nm.energy(case,plus)-nm.energy(case,minus))/(2*eps)
            force=-float(nm.field(case,y,lp)[m:]@direction)
            assert abs(numeric-force)/max(1,abs(force))<1e-6
            e0=nm.energy(case,y);a=nm.advance(case,y,lp,128)
            half=nm.advance(case,y,lp,256,h=Q(case["h"])/2)
            double=nm.advance(case,y,lp,64,h=Q(case["h"])*2)
            e1=abs(nm.energy(case,a)-e0);e2=abs(nm.energy(case,half)-e0)
            e4=abs(nm.energy(case,double)-e0)
            returned=nm.advance(case,np.concatenate((a[:m],-a[m:])),lp,128)
            returned[m:]*=-1
            extras[f]={"energy_gradient_error":abs(numeric-force),
                       "short_energy_error_h":e1,"short_energy_error_h2":e2,"short_energy_error_2h":e4,
                       "energy_error_ratio_h_over_h2":e1/e2 if e2 else None,
                       "momentum_reversal_max_abs_error":float(np.max(np.abs(returned-y)))}
            assert 2.5<e1/e2<6
            assert float(np.max(np.abs(returned-y)))<1e-11
        if f!="reservoir":
            a=nm.advance(case,y,lp,32);b=nm.advance(case,y,lp,64,h=Q(case["h"])/2)
            c=nm.advance(case,y,lp,128,h=Q(case["h"])/4)
            e1=float(np.linalg.norm(a-b));e2=float(np.linalg.norm(b-c))
            extras.setdefault(f,{})["short_endpoint_h_vs_h2_norm"]=e1
            extras[f]["short_endpoint_h2_vs_h4_norm"]=e2
            extras[f]["observed_step_halving_ratio"]=e1/e2 if e2 else None
        final,report=long_run(case,y,lp);longs[case["id"]]=report
        print("LONG MATH PASS",case["id"],case["long_steps"],"steps",flush=True)
    report={"status":"PASS","actual_CFT_compilation":"NOT RUN: no CFT checkout supplied in this workspace",
            "checks":{"generated_sources":len(rows),"source_equations_vs_independent_NumPy":len(rows)*3,
                      "normal_RNE_rounding_interval_samples":rounding,"exact_vectors":"21 independent one-step vectors, three lanes each"},
            "sources":rows,"model_identity_checks":extras,"independent_double_long_runs":longs,
            "limitations":["NumPy runs use doubles and different evaluation order; they are not bitwise CFT results.",
                           "Long tangent integrations rescale each vector between 128-step chunks; no QR or Lyapunov spectrum.",
                           "No physical hardware was exercised. Actual acceptance and image execution await the user's checkout."]}
    (ROOT/"evidence"/"model-validation.json").write_bytes((json.dumps(report,indent=2,sort_keys=True)+"\n").encode())
    print(json.dumps(report["checks"],sort_keys=True),flush=True)


if __name__=="__main__":main()
