"""Independent parser/evaluator for the finite subset used by these sources.

This is deliberately NOT an implementation of the full CFT language. It
recognizes our generated statements, exact integer/rational arithmetic,
named/indexed lets, FMA, min/max/abs, and the three used step schemes.
Every runtime operator in the source is evaluated. No host float is used
for a bitwise reference value. The float evaluator is for model validation.
"""
import ast
from fractions import Fraction as Q
import re
from exact_oracle import FiniteOracle, decode


def exact_index(expr, env):
    if isinstance(expr,ast.Constant) and type(expr.value) is int:return expr.value
    if isinstance(expr,ast.Name) and expr.id in env:return env[expr.id]
    if isinstance(expr,ast.UnaryOp) and isinstance(expr.op,ast.USub):return -exact_index(expr.operand,env)
    if isinstance(expr,ast.BinOp):
        a,b=exact_index(expr.left,env),exact_index(expr.right,env)
        if isinstance(expr.op,ast.Add):return a+b
        if isinstance(expr.op,ast.Sub):return a-b
        if isinstance(expr.op,ast.Mult):return a*b
    raise ValueError("index outside the generated subset")


def target(text):
    m=re.fullmatch(r"([A-Za-z_]\w*)(?:\[(.*)\])?",text.strip())
    if not m:raise ValueError("bad target "+text)
    return m[1],None if m[2] is None else ast.parse(m[2],mode="eval").body


class Source:
    def __init__(self,text):
        self.state=[];self.arrays={};self.scalars={};self.params={};self.lane={}
        self.const={};self.lets={};self.equations={};self.nodes=[];self.cache={}
        self.used=set();self.integrator=None;self.h=None;self.q=[];self.p=[]
        statements=[]
        for raw in text.splitlines():
            line=raw.split(";",1)[0].strip()
            if line:statements.append(line)
        for line in statements:
            if line.startswith("format "):self.fmt=line.split()[1]
            elif line.startswith("round "):self.rnd=line.split()[1]
            elif line.startswith("state "):
                for s in line[6:].split(","):
                    m=re.fullmatch(r"\s*(\w+)(?:\[(\d+)\])?(?:\s+(cyclic))?\s*",s)
                    if not m:raise ValueError("bad state")
                    name,size,cyclic=m.groups();off=len(self.state)
                    if size is None:
                        self.scalars[name]=off;self.state.append((name,None))
                    else:
                        n=int(size);self.arrays[name]=(off,n,bool(cyclic))
                        self.state.extend((name,i) for i in range(n))
            elif line.startswith(("param ","lane param ","const ")):
                kind="lane" if line.startswith("lane") else line.split()[0]
                tail=line[len("lane param ") if kind=="lane" else len(kind)+1:]
                d={"param":self.params,"lane":self.lane,"const":self.const}[kind]
                for part in tail.split(","):
                    name,value=part.split("=",1)
                    d[name.strip()]=ast.parse(value.strip(),mode="eval").body
            elif line.startswith("step "):
                self.integrator=line[5:].split(",",1)[0].strip()
                m=re.search(r"\bh\s*=\s*([^,]+)",line)
                if m:self.h=Q(m[1].strip())
                for name in ("q","p"):
                    m=re.search(r"\b"+name+r"\s*=\s*\(([^)]+)\)",line)
                    if m:
                        indexes=[]
                        for s in m[1].split(","):
                            s=s.strip()
                            indexes.extend(range(self.arrays[s][0],self.arrays[s][0]+self.arrays[s][1])
                                           if s in self.arrays else [self.scalars[s]])
                        setattr(self,name,indexes)
        if not hasattr(self,"rnd"):self.rnd="rne"
        for line in statements:
            if not line.startswith(("let ","next ","d/dt ")):continue
            islet=line.startswith("let ")
            tail=line[4:] if islet else line[5:]
            left,right=tail.split("=",1)
            name,index=target(left)
            envs=[{}]
            m=re.search(r"\s+for\s+(\w+)\s+in\s+(.+)\.\.(.+)$",right)
            if m:
                var,lo,hi=m.groups()
                lo=exact_index(ast.parse(lo.strip(),mode="eval").body,{})
                hi=exact_index(ast.parse(hi.strip(),mode="eval").body,{})
                envs=[{var:i} for i in range(lo,hi+1)]
                right=right[:m.start()]
            elif index is not None and isinstance(index,ast.Name):
                if islet:raise ValueError("generated lets must have an explicit range")
                envs=[{index.id:i} for i in range(self.arrays[name][1])]
            expr=ast.parse(right.strip(),mode="eval").body
            for env in envs:
                i=None if index is None else exact_index(index,env)
                key=(name,i)
                d=self.lets if islet else self.equations
                if key in d:raise ValueError("duplicate definition "+str(key))
                d[key]=(expr,env.copy())
        self.out=[self.build(*self.equations[s]) for s in self.state]
        dead=set(self.lets)-{x[1] for x in self.used if x[0]=="let"}
        if dead:raise ValueError("unused generated lets "+repr(sorted(dead)[:5]))
        for kind,d in [("param",self.params),("lane",self.lane),("const",self.const)]:
            if set(d)-{x[1] for x in self.used if x[0]==kind}:raise ValueError("unused "+kind)
        self.param_values={k:self.constant(v) for k,v in self.params.items()}
        self.lane_values={k:self.constant(v) for k,v in self.lane.items()}
        self.active={}

    def constant(self,expr):
        ref=self.build(expr,{})
        if ref[0]!="c":raise ValueError("expected a constant")
        return ref[1]

    def let(self,key):
        self.used.add(("let",key))
        if key not in self.cache:
            self.cache[key]=self.build(*self.lets[key])
        return self.cache[key]

    def build(self,x,env):
        if isinstance(x,ast.Constant):
            if type(x.value) is not int:raise ValueError("only integer literals are generated")
            return ("c",Q(x.value))
        if isinstance(x,ast.Name):
            name=x.id
            if name in env:return ("c",Q(env[name]))
            if name=="h":return ("c",self.h)
            if name in self.scalars:return ("s",self.scalars[name])
            if name in self.params:self.used.add(("param",name));return ("p",name)
            if name in self.lane:self.used.add(("lane",name));return ("l",name)
            if name in self.const:
                self.used.add(("const",name));return self.build(self.const[name],{})
            if (name,None) in self.lets:return self.let((name,None))
            raise ValueError("undefined name "+name)
        if isinstance(x,ast.Subscript) and isinstance(x.value,ast.Name):
            name=x.value.id;i=exact_index(x.slice,env)
            if name in self.arrays:
                off,n,cyclic=self.arrays[name]
                if cyclic:i%=n
                if not 0<=i<n:raise ValueError("out of range "+name)
                return ("s",off+i)
            return self.let((name,i))
        if isinstance(x,ast.UnaryOp) and isinstance(x.op,ast.USub):
            op="neg";args=[self.build(x.operand,env)]
        elif isinstance(x,ast.BinOp):
            op={ast.Add:"add",ast.Sub:"sub",ast.Mult:"mul",ast.Div:"div"}.get(type(x.op))
            if op is None:raise ValueError("unsupported binary op")
            args=[self.build(x.left,env),self.build(x.right,env)]
        elif isinstance(x,ast.Call) and isinstance(x.func,ast.Name):
            op=x.func.id
            if op not in ("fma","min","max","abs"):raise ValueError("unsupported call "+op)
            args=[self.build(a,env) for a in x.args]
        else:raise ValueError("expression outside generated subset")
        if all(a[0]=="c" for a in args):
            v=[a[1] for a in args]
            value={"add":lambda:v[0]+v[1],"sub":lambda:v[0]-v[1],
                   "mul":lambda:v[0]*v[1],"div":lambda:v[0]/v[1],
                   "neg":lambda:-v[0],"abs":lambda:abs(v[0]),
                   "min":lambda:min(v),"max":lambda:max(v),
                   "fma":lambda:v[0]*v[1]+v[2]}[op]()
            return ("c",value)
        if op=="div":raise ValueError("runtime division")
        self.nodes.append((op,args))
        return ("n",len(self.nodes)-1)

    def needed(self,outputs):
        key=tuple(outputs)
        if key not in self.active:
            used=set();todo=[self.out[i] for i in outputs]
            while todo:
                r=todo.pop()
                if r[0]=="n" and r[1] not in used:
                    used.add(r[1]);todo.extend(self.nodes[r[1]][1])
            self.active[key]=used
        return self.active[key]

    def evaluate(self,state,lanes=(),oracle=None,outputs=None,params=None):
        """oracle=None uses host doubles ONLY for approximate model checks."""
        outputs=list(range(len(self.out))) if outputs is None else outputs
        active=self.needed(outputs)
        values=[None]*len(self.nodes);constants={}
        p=self.param_values if params is None else params
        l=dict(zip(self.lane,lanes)) if lanes else self.lane_values
        def leaf(r):
            kind,v=r
            if kind=="n":return values[v]
            if kind=="s":return state[v]
            if kind in ("p","l"):
                a=(p if kind=="p" else l)[v]
                return oracle.constant(a) if oracle else float(a)
            if r not in constants:constants[r]=oracle.constant(v) if oracle else float(v)
            return constants[r]
        for i,(op,args) in enumerate(self.nodes):
            if i not in active:continue
            v=[leaf(a) for a in args]
            if oracle:
                if op in ("min","max"):
                    a,b=v
                    da,db=decode(a,self.fmt),decode(b,self.fmt)
                    if da==db==0:values[i]=(a|b) if op=="min" else (a&b)
                    else:values[i]=(a if da<=db else b) if op=="min" else (a if da>=db else b)
                else:values[i]=getattr(oracle,op)(*v)
            else:
                values[i]={"add":lambda:v[0]+v[1],"sub":lambda:v[0]-v[1],
                           "mul":lambda:v[0]*v[1],"neg":lambda:-v[0],"abs":lambda:abs(v[0]),
                           "fma":lambda:v[0]*v[1]+v[2],"min":lambda:min(v),"max":lambda:max(v)}[op]()
        return [leaf(self.out[i]) for i in outputs]

    def step(self,state,lanes=(),oracle=None,h=None):
        if oracle is None:oracle=FiniteOracle(self.fmt,self.rnd)
        h=self.h if h is None else Q(h)
        if self.integrator=="map":return self.evaluate(state,lanes,oracle)
        if self.integrator in ("rk4","euler"):
            return oracle.integrate(state,lambda y:self.evaluate(y,lanes,oracle),self.integrator,h)
        if self.integrator!="stormer-verlet":raise ValueError(self.integrator)
        h1,h2=oracle.constant(h),oracle.constant(h/2)
        q1=list(state)
        velocity=self.evaluate(state,lanes,oracle,self.q)
        for i,v in zip(self.q,velocity):q1[i]=oracle.fma(h2,v,state[i])
        p1=list(q1)
        force=self.evaluate(q1,lanes,oracle,self.p)
        for i,a in zip(self.p,force):p1[i]=oracle.fma(h1,a,state[i])
        out=list(p1)
        velocity=self.evaluate(p1,lanes,oracle,self.q)
        for i,v in zip(self.q,velocity):out[i]=oracle.fma(h2,v,q1[i])
        return out

    @property
    def step_operations(self):
        n=len(self.state)
        if self.integrator=="rk4":return 4*len(self.nodes)+7*n
        if self.integrator=="euler":return len(self.nodes)+n
        if self.integrator=="map":return len(self.nodes)
        return len(self.needed(self.p))+2*len(self.needed(self.q))+2*len(self.q)+len(self.p)
