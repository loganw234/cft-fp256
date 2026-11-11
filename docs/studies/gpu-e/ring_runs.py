#!/usr/bin/env python3
"""GPU-E: read the records run_ring.sh wrote and print what the study uses.

Usage: python3 ring_runs.py WORKDIR

For every ias15_cft record in WORKDIR (*.rec): its format, form, epsilon,
the steps per orbit in steady state, the corrector passes per step attempt,
and the rejected steps. Steps per orbit come from the last two samples: an
orbit at radius r is 2 pi r^1.5 in these units (G = M = 1), and the step is
taken as constant between the samples, which on a circular orbit it is (the
two halves are printed for that reason).

Then the div/sqrt call identity, a check that can fail: between the 100- and
200-step runs of one setting (two samples each, so sample work cancels),
    d(divsqrt_calls) = c_pass * d(sum of passes) + c_att * d(attempts)
with the coefficients COUNTED from src/ias15_cft.c (cft-rebound 7a7a279):
    REBOUND's form: c_pass = 7 * (8 + 2) + 28 + 1 = 99, c_att = 2 + 5 + 15 + 1 = 23
    the FMA form:   c_pass = 7 * 2 + 1 = 15,              c_att = 2 + 5 + 0 + 1 = 8
(per pass: the predictor's 8 divides a substep, gravity's sqrt and divide, the
corrector's n at substep n, pc_error's 1; per attempt: gravity at the step's
start 2, choose_timestep's 5, the end-of-step update's 15, the ratio's 1).
"""
import glob, math, os, re, sys

def parse(path):
    r = {"label": os.path.basename(path)[:-4], "samples": [], "systems": {}}
    with open(path) as f:
        for line in f:
            if line.startswith("# program="):
                m = re.search(r"format=(\S+).* E=(\d+)", line) or re.search(r"format=(\S+)", line)
                r["format"] = m.group(1)
                r["arith"] = re.search(r"arith=(\S+)", line).group(1)
                r["N"] = int(re.search(r" N=(\d+)", line).group(1))
                r["E"] = int(re.search(r" E=(\d+)", line).group(1)) if " E=" in line else 1
            elif line.startswith("# dt0="):
                r["eps"] = float.fromhex(re.search(r"epsilon= (\S+)", line).group(1))
            elif line.startswith("sample") or line.startswith("system"):
                t = line.split()
                s = 0
                if t[0] == "system":
                    s, t = int(t[1]), t[2:]
                # sample k done t dt dt_last energy x y z vx vy vz ...
                r["samples"].append((s, int(t[1]), int(t[2]), float.fromhex(t[3]), None))
            elif line.startswith("# system ") and "steps_done=" in line:
                m = re.match(r"# system (\d+) steps_done=(\d+) iterations_max_exceeded=(\d+) steps_rejected=(\d+) "
                             r"mean_pc_iterations=([\d.]+) max_pc_iterations=(\d+)", line)
                r["systems"][int(m.group(1))] = dict(done=int(m.group(2)), rej=int(m.group(4)),
                                                     pc=float(m.group(5)), pcmax=int(m.group(6)))
            elif line.startswith("# steps_done="):
                for k in ("steps_done", "steps_rejected", "max_pc_iterations", "calls", "divsqrt_calls",
                          "iterations_max_exceeded"):
                    r[k] = int(re.search(k + r"=(\d+)", line).group(1))
                r["pc"] = float(re.search(r"mean_pc_iterations=([\d.]+)", line).group(1))
                r["secs"] = float(re.search(r"seconds=([\d.]+)", line).group(1))
                m = re.search(r"pc_lane_efficiency=([\d.]+)", line)
                r["lane_eff"] = float(m.group(1)) if m else None
    return r

def steps_per_orbit(samples, s, radius):
    pts = [(k, done, t) for (ss, k, done, t, _) in samples if ss == s]
    (_, d1, t1), (_, d2, t2) = pts[-2], pts[-1]
    period = 2 * math.pi * radius ** 1.5
    return period * (d2 - d1) / (t2 - t1)

def main(work):
    recs = {os.path.basename(p)[:-4]: parse(p) for p in sorted(glob.glob(os.path.join(work, "*.rec")))}
    print("label | format | arith | epsilon | N | E | steps/orbit (two halves) | passes/attempt | max | rejected | cap hits | s")
    for lab, r in recs.items():
        if r["E"] == 1 and r["N"] == 2:
            pts = [p for p in r["samples"]]
            halves = []
            for i in (1, 2):
                if len(pts) > i:
                    (_, _, d1, t1, _), (_, _, d2, t2, _) = pts[i - 1], pts[i]
                    halves.append(2 * math.pi * (d2 - d1) / (t2 - t1))
            spo = " / ".join("%.1f" % h for h in halves)
        elif r["E"] == 1:
            spo = "%.1f (r=1.0)" % steps_per_orbit(r["samples"], 0, 1.0)
        else:
            spo = "per member below"
        print("%s | %s | %s | %.0e | %d | %d | %s | %.3f | %d | %d | %d | %.1f" % (
            lab, r["format"], r["arith"], r["eps"], r["N"], r["E"], spo, r["pc"], r["max_pc_iterations"],
            r["steps_rejected"], r["iterations_max_exceeded"], r["secs"]))
    for lab, r in recs.items():
        if r["E"] > 1:
            print("\n%s: members (r_k = 1 + 0.1 k), pc_lane_efficiency=%s" % (lab, r["lane_eff"]))
            print("member | r | steps/own orbit | passes/attempt | max | rejected | orbits in the run")
            for s in sorted(r["systems"]):
                rad = 1.0 + 0.1 * s
                sy = r["systems"][s]
                tend = [t for (ss, k, d, t, _) in r["samples"] if ss == s][-1]
                print("%d | %.1f | %.1f | %.3f | %d | %d | %.2f" % (s, rad, steps_per_orbit(r["samples"], s, rad),
                      sy["pc"], sy["pcmax"], sy["rej"], tend / (2 * math.pi * rad ** 1.5)))
    print("\ndiv/sqrt identity (d = the 200-step run minus the 100-step run):")
    coef = {"rebound": (99, 23), "fma": (15, 8)}
    for a, b in (("B_fp64_e9_100", "B_fp64_e9_200"), ("B_fp128_e12_100", "B_fp128_e12_200"),
                 ("B_fp256_e16f_100", "B_fp256_e16f_200")):
        if a not in recs or b not in recs:
            print("%s/%s: missing" % (a, b)); continue
        ra, rb = recs[a], recs[b]
        att = lambda r: r["steps_done"] + r["steps_rejected"]
        sp = lambda r: round(r["pc"] * att(r))
        cp, ca = coef[ra["arith"]]
        pred = cp * (sp(rb) - sp(ra)) + ca * (att(rb) - att(ra))
        meas = rb["divsqrt_calls"] - ra["divsqrt_calls"]
        print("%s %s: d_passes=%d d_attempts=%d predicted d_divsqrt=%d measured=%d -> %s" % (
            ra["format"], ra["arith"], sp(rb) - sp(ra), att(rb) - att(ra), pred, meas,
            "IDENTICAL" if pred == meas else "DIFFERS by %d" % (meas - pred)))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
