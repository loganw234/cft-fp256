"""Decimal postprocessing of actual returned state encodings.

These are scientific diagnostics, not pass/fail compiler invariants. All
state encodings remain in snapshots. No binary64 conversion precedes a
wide-format measurement; Decimal arithmetic uses 90 significant digits.
"""
from decimal import Decimal as D, localcontext
from fractions import Fraction
from hashlib import sha256
from exact_oracle import decode, FORMATS
from models import periodic_neighbors


def decimal(v):
    if isinstance(v,D):return v
    v=Fraction(v)
    return D(v.numerator)/D(v.denominator)


def rms(v):
    return (sum(x*x for x in v)/len(v)).sqrt()


def strings(value):
    if isinstance(value,D):return str(value)
    if isinstance(value,dict):return {k:strings(v) for k,v in value.items()}
    if isinstance(value,list):return [strings(v) for v in value]
    return value


def measure(case,bits):
    fmt=case["format"];width,eb,fb=FORMATS[fmt]
    values=[];infs=nans=0
    for b in bits:
        b=int(b,0) if isinstance(b,str) else b
        if ((b>>fb)&((1<<eb)-1))==((1<<eb)-1):
            if b&((1<<fb)-1):nans+=1
            else:infs+=1
        else:values.append(b)
    if infs or nans:return {"nonfinite":True,"infinities":infs,"nans":nans}
    with localcontext() as ctx:
        ctx.prec=90
        y=[decimal(decode(b,fmt)) for b in values]
        out={"nonfinite":False}
        f=case["family"];s=case["shape"]
        if f=="gray_scott":
            n=s["n"];m=n*n;u=y[:m];v=y[m:]
            rough=sum((v[i]-v[periodic_neighbors(n,i)[1]])**2+(v[i]-v[periodic_neighbors(n,i)[3]])**2 for i in range(m))/m
            out.update(u_min=min(u),u_max=max(u),u_mean=sum(u)/m,
                       v_min=min(v),v_max=max(v),v_mean=sum(v)/m,v_rms=rms(v),spatial_roughness=rough)
        elif f=="lorenz_tangent":
            k,j,r=(s[x] for x in ("k","j","vectors"));m=k*j;dim=k+m
            out.update(slow_mean=sum(y[:k])/k,slow_rms=rms(y[:k]),fast_rms=rms(y[k:dim]),
                       tangent_max=[max(abs(v) for v in y[(a+1)*dim:(a+2)*dim]) for a in range(r)])
        elif f in ("fput","phi4"):
            n=s["n"];m=n if f=="fput" else n*n;q=y[:m];p=y[m:]
            kinetic=sum(v*v/2 for v in p)
            if f=="fput":
                strain=[q[(i+1)%m]-q[i] for i in range(m)]
                potential=sum(v*v/2+v*v*v/12+v*v*v*v/4 for v in strain)
                out["total_momentum"]=sum(p)
            else:
                potential=sum(-v*v/2+v*v*v*v/4 for v in q)
                potential+=sum((q[i]-q[periodic_neighbors(n,i)[1]])**2/8+(q[i]-q[periodic_neighbors(n,i)[3]])**2/8 for i in range(m))
            out.update(energy=kinetic+potential,kinetic=kinetic,potential=potential,
                       mean_position=sum(q)/m,q_rms=rms(q),p_rms=rms(p))
        elif f=="kuramoto_sivashinsky":
            n=len(y);grad=[y[(i+1)%n]-y[i] for i in range(n)]
            d2=[y[(i+1)%n]-2*y[i]+y[(i-1)%n] for i in range(n)]
            out.update(mean=sum(y)/n,rms=rms(y),u_min=min(y),u_max=max(y),
                       linear_drive=sum(v*v for v in grad)/n,biharmonic_dissipation=sum(v*v for v in d2)/n)
        elif f=="reservoir":
            d=s["d"];r=y[:d];z=y[d:d+8];q,p=y[-2:];h=decimal(Fraction(case["h"]))
            out.update(r_min=min(r),r_max=max(r),r_rms=rms(r),z_rms=rms(z),
                       near_clip_fraction=D(sum(abs(v)>D("0.95") for v in r))/d,
                       oscillator_invariant=q*q+p*p+h*q*p)
        elif f=="riccati":
            n=s["n"];a=[[y[i*n+j] for j in range(n)] for i in range(n)]
            sym=max(abs(a[i][j]-a[j][i]) for i in range(n) for j in range(n))
            b=[[(a[i][j]+a[j][i])/2 for j in range(n)] for i in range(n)]
            L=[[D(int(i==j)) for j in range(n)] for i in range(n)];diag=[];positive=True
            for i in range(n):
                pivot=b[i][i]-sum(L[i][k]**2*diag[k] for k in range(i))
                diag.append(pivot)
                if pivot<=0:positive=False;break
                for j in range(i+1,n):
                    L[j][i]=(b[j][i]-sum(L[j][k]*L[i][k]*diag[k] for k in range(i)))/pivot
            out.update(trace=sum(a[i][i] for i in range(n)),frobenius=(sum(v*v for v in y)).sqrt(),
                       symmetry_residual=sym,min_diagonal=min(a[i][i] for i in range(n)),
                       decimal_ldlt_positive=positive,min_ldlt_pivot=min(diag))
        return strings(out)


def differences(case,a,b):
    with localcontext() as ctx:
        ctx.prec=90
        d=[abs(decimal(decode(int(x,0) if isinstance(x,str) else x,case["format"]))-
               decimal(decode(int(z,0) if isinstance(z,str) else z,case["format"]))) for x,z in zip(a,b)]
        return strings({"max_abs":max(d),"rms":rms(d)})


def state_digest(rows):
    return sha256(("\n".join(",".join(r) for r in rows)+"\n").encode("ascii")).hexdigest()
