#!/usr/bin/env python3
"""Fault-injection checks of the runner with synthetic backends, not CFT."""
from fractions import Fraction as Q
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import ModuleType, SimpleNamespace
from exact_oracle import FiniteOracle, spelling, round_exact, decode, power2
from models import phi4, lorenz_tangent, lit
from subset_oracle import Source
import run_workloads as runner


class Graph:
    def __init__(self,text):
        self.source=Source(text);self.text=text
        self.n_state=len(self.source.state);self.fmt=SimpleNamespace(width=64,name="fp64");self.rnd="rne"
        self.const=[];self.param=[(name,value,*round_exact(value)) for name,value in self.source.param_values.items()]
    def to_bytes(self):return self.text.encode("ascii")


class Backend:
    def __init__(self,mode="correct"):
        self.mode=mode
        self.lang=SimpleNamespace(render_canonical=lambda g:g.text,
                                  compile_text=lambda text,name:SimpleNamespace(graph=Graph(text)))
    def load_source(self,path):return Graph(path.read_text(encoding="ascii"))
    def clear_cache(self):pass
    def run(self,graph,req):
        out=[];flags=0
        for a,row in enumerate(req["states"]):
            oracle=FiniteOracle()
            y=[int(b,0) for b in row]
            lp=[decode(int(b,0)) for b in req.get("lane_params",[[]]*len(req["states"]))[a]]
            for _ in range(req["steps"]):y=graph.source.step(y,lp,oracle=oracle,h=req.get("h"))
            out.append([spelling(b) for b in y]);flags|=oracle.flags
        result={"states":out,"flags":flags}
        if self.mode=="wrong first bit":result["states"][0][0]=spelling(int(out[0][0],0)^1)
        if self.mode=="wrong first flags":result["flags"]^=1
        if self.mode=="wrong segment" and req["steps"]==2:result["states"][0][0]=spelling(int(out[0][0],0)^1)
        if self.mode=="wrong monolithic" and req["steps"]==8:result["states"][0][0]=spelling(int(out[0][0],0)^1)
        if self.mode=="wrong halved" and req.get("h")==str(Q(1,128)):result["states"][0][0]=spelling(int(out[0][0],0)^1)
        return result


def main():
    constants=ModuleType("cft_golden.lang.constants")
    constants.round_once=lambda fmt,rnd,value:round_exact(value,fmt.name,rnd)
    # The module replacement exists only in this short self-test process.
    sys.modules[constants.__name__]=constants
    with tempfile.TemporaryDirectory(prefix="hard-runner-test-") as temp:
        root=Path(temp)
        case={"id":"phi4_fixture","family":"phi4","format":"fp64","shape":{"n":4},
              "integrator":"stormer-verlet","h":"1/64","halving_steps":8,"reversal_steps":8,
              "file":"program.cftl","reference":"reference.json","n_state":32,
              "source_sha256":"fixture","input_sha256":"fixture"}
        lines,state,params,lp,inputs=phi4(case);text="\n".join(lines)+"\n"
        (root/case["file"]).write_bytes(text.encode())
        source=Source(text);states=[];out=[];flags=0
        for row in inputs:
            oracle=FiniteOracle();y=[oracle.constant(v) for v in row["state"]]
            states.append([spelling(b) for b in y]);z=source.step(y,oracle=oracle)
            out.append([spelling(b) for b in z]);flags|=oracle.flags
        ref={"source_sha256":"fixture","input_sha256":"fixture",
             "request":{"states":states,"lane_params":[[],[],[]],"steps":1},
             "expected":{"states":out,"flags":flags}}
        (root/case["reference"]).write_bytes(json.dumps(ref).encode())
        runner.ROOT=root
        args=SimpleNamespace(no_emit=True,compile_only=False,profile="verify",steps=8,
                             chunk=128,compare_all=True,step_halving=True,reversal=True)
        reports={}
        for mode in ("correct","wrong first bit","wrong first flags","wrong segment","wrong monolithic","wrong halved"):
            directory=root/mode.replace(" ","_");directory.mkdir();rows=[]
            try:
                result=runner.run_case(case,args,Backend(mode),Backend(),directory,rows.append)
            except AssertionError as exc:
                assert mode!="correct"
                reports[mode]={"verdict":"DETECTED","detail":str(exc)}
            else:
                assert mode=="correct",mode+" was missed"
                assert result["verdict"]=="PASS"
                assert result["final"]["step"]==8
                assert {x["phase"] for x in rows}>={"independent one-step oracle","monolithic versus segmented","step halving","momentum reversal"}
                reports[mode]={"verdict":"PASS","journal_rows":len(rows)}
        tiny=dict(case,id="tangent_fixture",family="lorenz_tangent",shape={"k":4,"j":2,"vectors":2},
                  integrator="rk4",h="1/1000",n_state=36,long_steps=24,reversal_steps=None)
        lines,state,params,lp,inputs=lorenz_tangent(tiny);text="\n".join(lines)+"\n"
        (root/tiny["file"]).write_bytes(text.encode())
        source=Source(text);states=[];out=[];lanes=[];flags=0
        for row in inputs:
            oracle=FiniteOracle();y=[oracle.constant(v) for v in row["state"]]
            states.append([spelling(b) for b in y]);z=source.step(y,row["lane_params"],oracle)
            lanes.append([spelling(oracle.constant(v)) for v in row["lane_params"]])
            out.append([spelling(b) for b in z]);flags|=oracle.flags
        ref["request"]={"states":states,"lane_params":lanes,"steps":1}
        ref["expected"]={"states":out,"flags":flags}
        (root/tiny["reference"]).write_bytes(json.dumps(ref).encode())
        # Force both positive and negative scaling exponents and preserve -0.
        fixture=[list(r) for r in states]
        fixture[0][12]=spelling(round_exact(Q(16))[0])
        fixture[0][24:36]=[spelling(0)]*12
        fixture[0][24]=spelling(round_exact(Q(1,16))[0])
        fixture[0][25]="0x8000000000000000"
        scaled,powers=runner.rescale_tangents(tiny,fixture)
        assert powers[0]==[4,-4]
        assert scaled[0][25]=="0x8000000000000000"
        for a,row in enumerate(fixture):
            for v,e in enumerate(powers[a]):
                for i in range((v+1)*12,(v+2)*12):
                    assert decode(int(scaled[a][i],0))==decode(int(row[i],0))*power2(-e)
        directory=root/"tangent_long";directory.mkdir();rows=[]
        args.profile="long";args.steps=24;args.step_halving=False;args.reversal=False
        result=runner.run_case(tiny,args,Backend(),Backend(),directory,rows.append)
        assert result["verdict"]=="PASS"
        assert len([r for r in rows if "finite_time_tangent_growth_rates" in r])==2
        assert all(r["exact_backend_comparison"] for r in rows if r["phase"]=="evolution")
        reports["long tangent rescaling"]={"verdict":"PASS","signed_zero_preserved":True,
                                          "growth_rate_checkpoints":2,"exact_power_of_two_scaling":True}
        script=Path(__file__).resolve().parent/"compile_cases.py"
        for label,code,expected,rc in [
                ("accepted synthetic compiler","pass","PASS",0),
                ("capacity synthetic compiler","import sys;print('scratch-capacity');sys.exit(3)","TARGET-LIMIT",0),
                ("internal synthetic compiler","import sys;sys.exit(70)","INTERNAL-ERROR",1)]:
            output=root/(label.replace(" ","_")+".jsonl")
            argv=[sys.executable,"-c",code,"{source}"]
            done=subprocess.run([sys.executable,str(script),"--command-json",json.dumps(argv),
                                 "--only","riccati_hard_fp64","--results",str(output)],capture_output=True,text=True)
            assert done.returncode==rc,(done.returncode,done.stdout,done.stderr)
            entries=[json.loads(x) for x in output.read_text().splitlines()]
            assert len(entries)==1 and entries[0]["verdict"]==expected
            reports[label]={"verdict":"PASS","expected_classification":expected}
        print(json.dumps(reports,sort_keys=True))
    output=Path(__file__).resolve().parents[1]/"evidence"/"runner-validation.json"
    output.write_bytes((json.dumps({"status":"PASS","synthetic_only":True,"checks":reports},indent=2,sort_keys=True)+"\n").encode())


if __name__=="__main__":main()
