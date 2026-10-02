"""Independent vectorized mathematical models for offline validation.

NumPy's doubles and matmul do not implement the source's rounding sequence.
These functions validate the intended equations and stable run choices.
They are not bitwise compiler oracles. The runtime harness needs no NumPy.
"""
import numpy as np
from fractions import Fraction
from models import weights


def field(case, y, lanes):
    f=case["family"];s=case["shape"];y=np.asarray(y,dtype=float)
    if f=="gray_scott":
        n=s["n"];m=n*n;u=y[:m].reshape(n,n);v=y[m:].reshape(n,n);feed,kill=map(float,lanes)
        def lap(a):return sum(np.roll(a,d,axis=ax) for ax in (0,1) for d in (-1,1))-4*a
        reaction=u*v*v
        return np.concatenate(((0.16*lap(u)-reaction+feed*(1-u)).ravel(),
                               (0.08*lap(v)+reaction-(feed+kill)*v).ravel()))
    if f=="lorenz_tangent":
        k,j,r=(s[x] for x in ("k","j","vectors"));m=k*j;g=float(lanes[0])
        x=y[:k];v=y[k:k+m];adx=np.roll(x,-1)-np.roll(x,2)
        ady=np.roll(v,1)-np.roll(v,-2);speed=100*np.roll(v,-1)
        out=[np.roll(x,1)*adx+10-x-g*v.reshape(k,j).sum(axis=1),
             speed*ady-10*v+g*np.repeat(x,j)]
        for a in range(r):
            t=y[(a+1)*(k+m):(a+2)*(k+m)];tx=t[:k];ty=t[k:]
            out += [np.roll(tx,1)*adx+np.roll(x,1)*(np.roll(tx,-1)-np.roll(tx,2))-tx-g*ty.reshape(k,j).sum(axis=1),
                    speed*(np.roll(ty,1)-np.roll(ty,-2))+100*np.roll(ty,-1)*ady-10*ty+g*np.repeat(tx,j)]
        return np.concatenate(out)
    if f=="fput":
        n=s["n"];q,p=y[:n],y[n:];r=np.roll(q,-1)-q
        tension=r+0.25*r*r+r*r*r
        return np.concatenate((p,tension-np.roll(tension,1)))
    if f=="phi4":
        n=s["n"];m=n*n;q=y[:m].reshape(n,n);p=y[m:]
        lap=sum(np.roll(q,d,axis=ax) for ax in (0,1) for d in (-1,1))-4*q
        return np.concatenate((p,(0.25*lap+q-q*q*q).ravel()))
    if f=="kuramoto_sivashinsky":
        u=y;plus=np.roll(u,-1);minus=np.roll(u,1)
        d2=plus-2*u+minus
        d4=np.roll(u,-2)-4*plus+6*u-4*minus+np.roll(u,2)
        return -0.25*(plus*plus-minus*minus)-d2-d4
    if f=="riccati":
        n=s["n"];p=y.reshape(n,n)
        rotate=np.roll(p,-1,axis=0)-np.roll(p,1,axis=0)+np.roll(p,-1,axis=1)-np.roll(p,1,axis=1)
        v=np.asarray([(7*i+3)%11-5 for i in range(n)])/8
        forcing=np.eye(n)+np.outer(v,v)/16
        return (-0.25*p+0.5*rotate+forcing-0.25*(p@p)).ravel()
    raise ValueError(f)


def reservoir_setup(case):
    d,h=(case["shape"][x] for x in ("d","hidden"))
    return (np.asarray(weights(h,d,1),dtype=float),np.asarray(weights(d,h,2),dtype=float),
            np.asarray([a%5-2 for a in range(h)])/64,
            np.asarray([a%7-3 for a in range(d)])/64)


def map_step(case,y,lanes,setup=None):
    d,h=(case["shape"][x] for x in ("d","hidden"));w1,w2,b1,b2=setup or reservoir_setup(case)
    r=y[:d];z=y[d:d+8];q,p=y[-2:];drive=float(lanes[0]);dt=float(Fraction(case["h"]))
    hidden=np.clip(w1@r+0.25*drive*np.where(np.arange(h)%2,q,p)+b1*drive,-1,1)
    target=np.clip(w2@hidden+0.25*drive*np.where(np.arange(d)%2,p,q)+b2*drive,-1,1)
    newr=r+0.25*(target-r);newz=z+(r.reshape(8,d//8).mean(axis=1)-z)/16
    newq=q+dt*p;newp=p-dt*newq
    return np.concatenate((newr,newz,[newq,newp]))


def advance(case,y,lanes,steps,h=None):
    from fractions import Fraction
    dt=float(Fraction(case["h"]) if h is None else h);y=np.asarray(y,dtype=float).copy()
    setup=reservoir_setup(case) if case["family"]=="reservoir" else None
    for _ in range(steps):
        if case["integrator"]=="map":y=map_step(case,y,lanes,setup);continue
        if case["integrator"]=="stormer-verlet":
            n=len(y)//2;y[:n]+=dt/2*y[n:]
            y[n:]+=dt*field(case,y,lanes)[n:]
            y[:n]+=dt/2*y[n:]
        else:
            k1=field(case,y,lanes);k2=field(case,y+dt/2*k1,lanes)
            k3=field(case,y+dt/2*k2,lanes);k4=field(case,y+dt*k3,lanes)
            y=y+dt/6*(k1+2*k2+2*k3+k4)
    return y


def energy(case,y):
    f=case["family"];n=case["shape"]["n"];m=n*n if f=="phi4" else n
    q=y[:m];p=y[m:]
    if f=="fput":
        r=np.roll(q,-1)-q
        return float(np.sum(p*p/2+r*r/2+r*r*r/12+r*r*r*r/4))
    q=q.reshape(n,n)
    bonds=sum((np.roll(q,-1,axis=ax)-q)**2 for ax in (0,1))
    return float(np.sum(p*p/2)+np.sum(-q*q/2+q*q*q*q/4+0.125*bonds))
