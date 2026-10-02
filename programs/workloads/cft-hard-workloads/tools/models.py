"""Workload definitions. All source literals and inputs are exact rationals."""
from fractions import Fraction as Q


def lit(v):
    v = Q(v)
    return str(v.numerator) if v.denominator == 1 else f"{v.numerator}/{v.denominator}"


def periodic_neighbors(n, i):
    y, x = divmod(i, n)
    return (y*n+(x-1)%n, y*n+(x+1)%n,
            ((y-1)%n)*n+x, ((y+1)%n)*n+x)


def header(case, states, params, lanes=()):
    lines = ["; Substantial numerical workload; see MODELS.md for the definition.",
             f"system {case['id']}", f"format {case['format']}", "round rne",
             "state " + ", ".join(states)]
    if params:
        lines.append("param " + ", ".join(f"{k} = {lit(v)}" for k, v in params.items()))
    if lanes:
        lines.append("lane param " + ", ".join(f"{k} = {lit(v)}" for k, v in lanes))
    return lines


def dot(lines, name, terms):
    """Eight-term FMA blocks; block results added left to right."""
    names = []
    for b, start in enumerate(range(0, len(terms), 8)):
        expr = "0"
        for a, v in terms[start:start+8]:
            expr = f"fma({a}, {v}, {expr})"
        part = f"{name}_b{b}"
        lines.append(f"let {part} = {expr}")
        names.append(part)
    lines.append(f"let {name} = " + " + ".join(names))
    return name


def weights(rows, cols, phase):
    """Version-independent integer mixer; no random module or float."""
    values = (-3, -2, -1, 1, 2, 3)
    denominator = 1 << max(1, (max(rows, cols)-1).bit_length()-3)
    answer = []
    for i in range(rows):
        row = []
        for j in range(cols):
            z = ((i+1)*0x9E3779B1 ^ (j+1)*0x85EBCA77 ^ phase*0xC2B2AE3D) & 0xffffffff
            z ^= z >> 16
            z = (z*0x7FEB352D) & 0xffffffff
            z ^= z >> 15
            z = (z*0x846CA68B) & 0xffffffff
            z ^= z >> 16
            row.append(Q(values[z % 6], denominator))
        answer.append(row)
    return answer


CONFIGS = {
    "gray_scott": dict(title="2D Gray-Scott reaction-diffusion",
                      hard={"n":16}, extended={"n":32},
                      integrator="rk4", h=Q(1), long_steps=4096, endurance_steps=65536),
    "lorenz_tangent": dict(title="Two-scale Lorenz-96 with tangent vectors",
                          hard={"k":24,"j":8,"vectors":4},
                          extended={"k":48,"j":16,"vectors":6},
                          integrator="rk4", h=Q(1,1000), long_steps=8192, endurance_steps=65536),
    "fput": dict(title="Nonlinear alpha-beta FPUT chain",
                 hard={"n":512}, extended={"n":2048},
                 integrator="stormer-verlet", h=Q(1,64), long_steps=8192, endurance_steps=65536),
    "phi4": dict(title="2D double-well Hamiltonian lattice",
                 hard={"n":16}, extended={"n":32},
                 integrator="stormer-verlet", h=Q(1,64), long_steps=8192, endurance_steps=65536),
    "kuramoto_sivashinsky": dict(title="Kuramoto-Sivashinsky periodic spatial discretization",
                               hard={"n":256}, extended={"n":1024},
                               integrator="rk4", h=Q(1,64), long_steps=8192, endurance_steps=65536),
    "reservoir": dict(title="Dense two-layer recurrent reservoir and oscillator",
                      hard={"d":96,"hidden":64}, extended={"d":192,"hidden":128},
                      integrator="map", h=Q(1,32), long_steps=16384, endurance_steps=65536),
    "riccati": dict(title="Dense matrix Riccati differential equation",
                    hard={"n":12}, extended={"n":32},
                    integrator="rk4", h=Q(1,64), long_steps=1024, endurance_steps=16384),
}


def define(family, tier="hard", fmt="fp64"):
    cfg = CONFIGS[family]
    shape = cfg["extended" if tier == "extended" else "hard"].copy()
    case = dict(id=f"{family}_{tier}_{fmt}", family=family, tier=tier,
                format=fmt, title=cfg["title"], shape=shape, kind="valid",
                stress=tier != "hard", compile_steps=1, integrator=cfg["integrator"],
                h=lit(cfg["h"]), long_steps=cfg["long_steps"],
                endurance_steps=cfg["endurance_steps"], halving_steps=32,
                reversal_steps=128 if family in ("fput", "phi4") else None)
    source, state, params, lane, inputs = globals()[family](case)
    case.update(state=state, n_state=sum(x[1] or 1 for x in state),
                params={k:lit(v) for k,v in params.items()},
                lane=[k for k,_ in lane])
    return case, "\n".join(source)+"\n", inputs


def gray_scott(case):
    n=case["shape"]["n"]; m=n*n
    params={"Du":Q(4,25),"Dv":Q(2,25)}
    lanes=[("feed",Q(7,200)),("kill",Q(31,500))]
    lines=header(case,[f"u[{m}]",f"v[{m}]"],params,lanes)
    lines += ["; A genuine 2D torus: east/west never cross into another row.",
              "let loss = -(feed + kill)",
              f"let reaction[i] = u[i] * v[i] * v[i] for i in 0..{m-1}"]
    for i in range(m):
        nb=periodic_neighbors(n,i)
        for a in ("u","v"):
            lines.append(f"let lap{a}[{i}] = " + " + ".join(f"{a}[{b}]" for b in nb)+f" - 4 * {a}[{i}]")
        lines += [f"d/dt u[{i}] = fma(Du, lapu[{i}], fma(feed, 1 - u[{i}], -reaction[{i}]))",
                  f"d/dt v[{i}] = fma(Dv, lapv[{i}], fma(loss, v[{i}], reaction[{i}]))"]
    lines.append(f"step rk4, h = {case['h']}")
    rows=[]
    for lane in range(3):
        u=[Q(1)]*m; v=[Q(0)]*m
        if lane:
            for i in range(m):
                y,x=divmod(i,n)
                if abs(x-n//2)<=n//8 and abs(y-n//2)<=n//8:
                    u[i]=Q(1,2)+Q(((x*13+y*7+lane)%7)-3,1024)
                    v[i]=Q(1,4)+Q(((x*5+y*11+lane)%7)-3,1024)
            if lane==2:
                for i in range(m):
                    y,x=divmod(i,n)
                    if abs(x-n//4)<=max(1,n//16) and abs(y-n//4)<=max(1,n//16):
                        u[i]=Q(1,2);v[i]=Q(1,4)
        lp=[Q(7,200),Q(31,500)] if lane!=2 else [Q(1,40),Q(11,200)]
        rows.append(dict(name=("homogeneous","seeded_patch","two_seeds_other_rates")[lane],state=u+v,lane_params=lp))
    return lines,[["u",m],["v",m]],params,lanes,rows


def lorenz_tangent(case):
    k,j,r=(case["shape"][s] for s in ("k","j","vectors")); m=k*j
    params={"forcing":Q(10),"damping":Q(10),"advection":Q(100)}
    lanes=[("gain",Q(1))]
    states=[f"X[{k}] cyclic",f"Y[{m}] cyclic"]
    state=[["X",k],["Y",m]]
    for v in range(r):
        states += [f"dx{v}[{k}] cyclic",f"dy{v}[{m}] cyclic"]
        state += [[f"dx{v}",k],[f"dy{v}",m]]
    lines=header(case,states,params,lanes)
    lines += ["; Y is ONE fast ring of K*J elements, across sector boundaries.",
              "; The tangent equations are J(X,Y) times each perturbation.",
              "let drag = -damping",
              f"let ax[i] = X[i+1] - X[i-2] for i in 0..{k-1}",
              f"let ay[i] = Y[i-1] - Y[i+2] for i in 0..{m-1}",
              f"let speed[i] = advection * Y[i+1] for i in 0..{m-1}"]
    for a in range(k):
        sy=" + ".join(f"Y[{a*j+b}]" for b in range(j))
        lines += [f"d/dt X[{a}] = fma(X[{(a-1)%k}], ax[{a}], forcing - X[{a}]) - gain * ({sy})",
                  f"d/dt Y[i] = fma(speed[i], ay[i], fma(drag, Y[i], gain * X[{a}])) for i in {a*j}..{(a+1)*j-1}"]
        for v in range(r):
            ds=" + ".join(f"dy{v}[{a*j+b}]" for b in range(j))
            lines += [f"d/dt dx{v}[{a}] = fma(dx{v}[{(a-1)%k}], ax[{a}], fma(X[{(a-1)%k}], dx{v}[{(a+1)%k}] - dx{v}[{(a-2)%k}], -dx{v}[{a}])) - gain * ({ds})",
                      f"d/dt dy{v}[i] = fma(speed[i], dy{v}[i-1] - dy{v}[i+2], fma(advection * dy{v}[i+1], ay[i], fma(drag, dy{v}[i], gain * dx{v}[{a}]))) for i in {a*j}..{(a+1)*j-1}"]
    lines.append(f"step rk4, h = {case['h']}")
    rows=[]
    for lane in range(3):
        x=[Q(6)+Q((a*7+lane*3)%17-8,128) for a in range(k)]
        y=[Q(3,10)+Q((a*11+lane*5)%19-9,256) for a in range(m)]
        row=x+y
        for v in range(r):
            t=[Q(0)]*(k+m)
            if v<2:
                t[0 if v==0 else k]=Q(1)
            else:
                t=[Q(((a*17+v*13)%31)-15,64) for a in range(k+m)]
            row += t
        rows.append(dict(name=f"multiscale_ensemble_{lane}",state=row,
                         lane_params=[[Q(1)],[Q(3,4)],[Q(5,4)]][lane]))
    return lines,state,params,lanes,rows


def fput(case):
    n=case["shape"]["n"]
    params={"alpha":Q(1,4),"beta":Q(1)}
    lines=header(case,[f"q[{n}] cyclic",f"p[{n}] cyclic"],params)
    lines += [f"let strain[i] = q[i+1] - q[i] for i in 0..{n-1}",
              f"let strain2[i] = strain[i] * strain[i] for i in 0..{n-1}",
              f"let tension[i] = fma(beta * strain[i], strain2[i], fma(alpha, strain2[i], strain[i])) for i in 0..{n-1}",
              "d/dt q[i] = p[i]"]
    for i in range(n):
        lines.append(f"d/dt p[{i}] = tension[{i}] - tension[{(i-1)%n}]")
    lines.append(f"step stormer-verlet, h = {case['h']}, q = (q), p = (p)")
    rows=[]
    for lane in range(3):
        q=[Q(0)]*n;p=[Q(0)]*n
        if lane==1:
            for i in range(n):q[i]=Q(max(0,8-abs(i-n//2)),16)
        if lane==2:
            for i in range(n):
                if abs(i-n//2)<16:q[i]=Q(1 if i%2 else -1,8)
            p[n//4]=Q(1,4);p[(n//4+1)%n]=Q(-1,4)
        rows.append(dict(name=("rest","localized_strain_packet","high_frequency_and_momentum_packet")[lane],state=q+p,lane_params=[]))
    return lines,[["q",n],["p",n]],params,[],rows


def phi4(case):
    n=case["shape"]["n"];m=n*n
    params={"kappa":Q(1,4)}
    lines=header(case,[f"q[{m}]",f"p[{m}]"],params)
    lines += [f"let cube[i] = q[i] * q[i] * q[i] for i in 0..{m-1}","d/dt q[i] = p[i]"]
    for i in range(m):
        nb=periodic_neighbors(n,i)
        lines.append(f"let lap[{i}] = "+" + ".join(f"q[{b}]" for b in nb)+f" - 4 * q[{i}]")
        lines.append(f"d/dt p[{i}] = fma(kappa, lap[{i}], q[{i}] - cube[{i}])")
    lines.append(f"step stormer-verlet, h = {case['h']}, q = (q), p = (p)")
    rows=[]
    for lane in range(3):
        q=[];p=[]
        for i in range(m):
            y,x=divmod(i,n)
            if lane==0:a=Q(1);b=Q(0)
            elif lane==1:
                a=Q(3 if (x-n//2)**2+(y-n//2)**2<(n//4)**2 else -3,4)
                b=Q((x*7+y*11)%7-3,256)
            else:
                a=Q(3 if (x//4+y//4)%2 else -3,4);b=Q((x*13+y*5)%9-4,256)
            q.append(a);p.append(b)
        rows.append(dict(name=("uniform_well","droplet","interacting_domains")[lane],state=q+p,lane_params=[]))
    return lines,[["q",m],["p",m]],params,[],rows


def kuramoto_sivashinsky(case):
    n=case["shape"]["n"]
    lines=header(case,[f"u[{n}] cyclic"],{})
    lines += ["; dx = 1. Conservative centered flux; centered D2 and D4.",
              f"let square[i] = u[i] * u[i] for i in 0..{n-1}",
              f"let d2[i] = fma(-2, u[i], u[i+1] + u[i-1]) for i in 0..{n-1}",
              f"let d4[i] = ((u[i+2] + u[i-2]) - 4 * (u[i+1] + u[i-1])) + 6 * u[i] for i in 0..{n-1}"]
    for i in range(n):
        lines.append(f"d/dt u[{i}] = fma(-1/4, square[{(i+1)%n}] - square[{(i-1)%n}], -d2[{i}] - d4[{i}])")
    lines.append(f"step rk4, h = {case['h']}")
    rows=[]
    for lane in range(3):
        if lane==0:u=[Q(0)]*n
        else:
            raw=[Q((i%32 if i%32<16 else 32-i%32)-8,32)+Q(((i*29+lane*7)%31)-15,1024) for i in range(n)]
            mean=sum(raw,Q(0))/n
            u=[v-mean for v in raw]
        rows.append(dict(name=("zero","broadband_zero_mean","shifted_broadband")[lane],state=u,lane_params=[]))
    return lines,[["u",n]],{},[],rows


def reservoir(case):
    d,hid=(case["shape"][k] for k in ("d","hidden"))
    params={"leak":Q(1,4),"input_gain":Q(1,4)}
    lanes=[("drive",Q(1))]
    lines=header(case,[f"r[{d}]","z[8]","q","p"],params,lanes)
    lines += ["; All dense dots use eight-term FMA blocks, then a left sum.",
              "let inputq = input_gain * drive * q",
              "let inputp = input_gain * drive * p"]
    w1=weights(hid,d,1);w2=weights(d,hid,2)
    for a in range(hid):
        name=dot(lines,f"hidden_dot_{a}",[(lit(w1[a][b]),f"r[{b}]") for b in range(d)])
        bias=f"fma({lit(Q(a%5-2,64))}, drive, "+("inputq" if a%2 else "inputp")+")"
        lines.append(f"let H[{a}] = max(-1, min(1, {name} + {bias}))")
    for a in range(d):
        name=dot(lines,f"recurrent_dot_{a}",[(lit(w2[a][b]),f"H[{b}]") for b in range(hid)])
        bias=f"fma({lit(Q(a%7-3,64))}, drive, "+("inputp" if a%2 else "inputq")+")"
        lines += [f"let target[{a}] = max(-1, min(1, {name} + {bias}))",
                  f"next r[{a}] = fma(leak, target[{a}] - r[{a}], r[{a}])"]
    span=d//8
    for a in range(8):
        avg=" + ".join(f"r[{b}]" for b in range(a*span,(a+1)*span))
        lines.append(f"next z[{a}] = fma(1/16, ({avg}) * (1/{span}) - z[{a}], z[{a}])")
    lines += ["let qnew = fma(h, p, q)", "next q = qnew", "next p = fma(-h, qnew, p)",
              f"step map, h = {case['h']}"]
    rows=[]
    for lane in range(3):
        r=[Q(0)]*d if lane==0 else [Q(((a*19+lane*5)%97)-48,128) for a in range(d)]
        rows.append(dict(name=("zero_drive","driven_memory","stronger_drive")[lane],state=r+[Q(0)]*8+[Q(1),Q(0)],
                         lane_params=[[Q(0)],[Q(1)],[Q(5,4)]][lane]))
    return lines,[["r",d],["z",8],["q",None],["p",None]],params,lanes,rows


def riccati(case):
    n=case["shape"]["n"];m=n*n
    params={"decay":Q(1,8),"omega":Q(1,2),"gamma":Q(1,4)}
    lines=header(case,[f"P[{m}]"],params)
    lines += ["; Pdot = A P + P A^T + Q - gamma P^2.",
              "; Q = I + v v^T/16; v_i = ((7*i+3)%11 - 5)/8, fixed.",
              "; A = -decay I + omega (forward_shift - backward_shift).",
              "let drag = -2 * decay"]
    for i in range(n):
        for j in range(n):
            a=i*n+j
            name=dot(lines,f"product_{i}_{j}",[(f"P[{i*n+k}]",f"P[{k*n+j}]") for k in range(n)])
            rotate=f"(P[{((i+1)%n)*n+j}] - P[{((i-1)%n)*n+j}]) + (P[{i*n+(j+1)%n}] - P[{i*n+(j-1)%n}])"
            vi,vj=Q((7*i+3)%11-5,8),Q((7*j+3)%11-5,8)
            forcing=Q(int(i==j))+vi*vj/16
            lines.append(f"d/dt P[{a}] = fma(-gamma, {name}, fma(omega, {rotate}, fma(drag, P[{a}], {lit(forcing)})))")
    lines.append(f"step rk4, h = {case['h']}")
    rows=[]
    for lane in range(3):
        p=[]
        for i in range(n):
            for j in range(n):
                if lane==0:v=Q(int(i==j))
                else:
                    bi,bj=Q(i%5-2,8),Q(j%5-2,8)
                    ci,cj=Q(i%7-3,16),Q(j%7-3,16)
                    v=Q(int(i==j),2) + bi*bj + ci*cj
                    if lane==2:v=2*Q(int(i==j))+2*bi*bj+ci*cj
                p.append(v)
        rows.append(dict(name=("isotropic_covariance","dense_rank_two_covariance","larger_dense_covariance")[lane],state=p,lane_params=[]))
    return lines,[["P",m]],params,[],rows
