# Equations and numerical tasks

Every constant in the source is an exact rational. These descriptions state
the mathematical models; the .cftl text fixes the actual operations,
parentheses, FMA sites and rounding order. All programs use rne.

The PDE discretizations are defined here as finite-dimensional models. Their
larger versions increase the domain at fixed spacing, rather than proving
spatial convergence to a continuum PDE.

## Gray-Scott reaction-diffusion

Two scalar concentrations live at each site of a periodic N by N grid:

~~~text
u' = Du * Lap(u) - u*v*v + feed*(1-u)
v' = Dv * Lap(v) + u*v*v - (feed+kill)*v
Lap(a)[y,x] = a[y,x-1] + a[y,x+1] + a[y-1,x] + a[y+1,x] - 4*a[y,x]
~~~

Du=4/25, Dv=2/25. Both spatial directions wrap independently; a flattened
east/west neighbor never falls into another row. Shared reaction terms are
used by both equations. Classical RK4 uses h=1.

Three lanes provide the exact homogeneous solution (u=1, v=0), a perturbed
central seed, and two seeds with different feed/kill lane parameters.
Measurements include concentration ranges, RMS and spatial roughness.
This tests four coupled grid stages and shared chemistry with material
spatial propagation. The main patterned lane remains nonuniform in the
independent 4,096-step model calibration.

Model reference: John E. Pearson, "Complex Patterns in a Simple System,"
1993, [author's paper](https://arxiv.org/abs/patt-sol/9304003).
The grid, initial conditions and run settings here are our workload choices,
not an attempted reproduction of a particular published experiment.

## Two-scale Lorenz-96 with a tangent bundle

There are K slow variables, K*J fast variables, and R tangent vectors.
The fast variables form one cyclic ring across slow-sector boundaries.
For fast index l, owner(l) is its slow sector. The source writes one range
per owner, so no runtime division or unsupported index operation is needed.

~~~text
X'_k = X_(k-1)*(X_(k+1)-X_(k-2)) - X_k + 10
       - gain * sum_(l in sector k) Y_l
Y'_l = 100*Y_(l+1)*(Y_(l-1)-Y_(l+2)) - 10*Y_l
       + gain*X_owner(l)

dx'_k = dx_(k-1)*(X_(k+1)-X_(k-2))
        + X_(k-1)*(dx_(k+1)-dx_(k-2)) - dx_k
        - gain * sum_(l in sector k) dy_l
dy'_l = 100*dy_(l+1)*(Y_(l-1)-Y_(l+2))
        + 100*Y_(l+1)*(dy_(l-1)-dy_(l+2)) - 10*dy_l
        + gain*dx_owner(l)
~~~

The tangent equations are the analytic Jacobian of the primal field applied
to each vector. Shared primal differences and fast advection coefficients
are read by every tangent column. The whole primal-plus-tangent system
advances with RK4, h=1/1000: each tangent stage reads its corresponding
primal stage.

Main: K=24, J=8, R=4, giving 1,080 state values. Larger: K=48, J=16, R=6,
giving 5,712. The three gain lane parameters are 1, 3/4 and 5/4.
Initial tangent columns include unit slow/fast perturbations and broad
directions. Long runs log finite time growth rates and exact rescalings.
The fixed coefficients correspond to c=b=10 and zero separate fast forcing;
changing J changes the aggregate coupling in this chosen variant.

Reference for the two-scale model, ring boundaries and tangent dynamics:
Carlu et al., 2019, [Lyapunov analysis of multiscale dynamics](https://npg.copernicus.org/articles/26/73/2019/index.html),
equations 1, 2 and 11. This workload does not implement their full covariant
vector algorithm or compute a Lyapunov spectrum.

## Nonlinear alpha-beta FPUT chain

A periodic ring has positions q_i, momenta p_i, and bond strains
r_i=q_(i+1)-q_i:

~~~text
V(r) = r*r/2 + r*r*r/12 + r*r*r*r/4
T(r) = r + r*r/4 + r*r*r
q'_i = p_i
p'_i = T(r_i) - T(r_(i-1))
H = sum_i (p_i*p_i/2 + V(r_i))
~~~

This is the alpha-beta model with alpha=1/4, beta=1. Stormer-Verlet's
drift-kick-drift scheme uses h=1/64. Bond forces are shared between adjacent
momentum updates. Main: 512 particles. Larger: 2,048.

Lanes are rest, a localized strain packet, and a high-frequency displacement
packet with opposite momentum impulses. Energy, total momentum, mean
position and reversal error are useful measurements. Energy is not exactly
conserved by the discrete integrator; short halving probes show second-order
behavior. Global momentum conservation provides a separate measurement.

Historical source for nonlinear chains: Fermi, Pasta, Ulam and Tsingou,
[Studies of the Nonlinear Problems, LA-1940](https://digital.library.unt.edu/ark:/67531/metadc1018377/).
Our periodic alpha-beta variant and packets differ from the original
fixed-end experiment.

## Two-dimensional double-well lattice

At each site, a nonlinear oscillator sits in a quartic double well and
couples to its four periodic neighbors:

~~~text
q' = p
p' = (1/4)*Lap(q) + q - q*q*q
H = sum_sites (p*p/2 - q*q/2 + q*q*q*q/4)
    + (1/8)*sum_forward_horizontal_and_vertical_bonds (q_neighbor-q)^2
~~~

Each bond is counted once in H. This Hamiltonian is separable and therefore
fits Stormer-Verlet, h=1/64. Main: 16x16 oscillators. Larger: 32x32.
Initial lanes are a uniform well, a droplet embedded in the opposite phase,
and interacting blocks of both phases. Droplet and domain evolution
exercise genuinely two-dimensional coupling and nonlinear onsite forces.
Energy and momentum-reversal measurements are reported. Total momentum is
not a conservation law here because of the onsite potential.

## Kuramoto-Sivashinsky spatial discretization

On a periodic one-dimensional grid with spacing 1:

~~~text
u'_i = -(u_(i+1)^2-u_(i-1)^2)/4 - D2(u)_i - D4(u)_i
D2(u)_i = u_(i+1) - 2*u_i + u_(i-1)
D4(u)_i = u_(i+2) - 4*u_(i+1) + 6*u_i - 4*u_(i-1) + u_(i-2)
~~~

This discretizes u_t=-(u^2)_x/2-u_xx-u_xxxx using a centered conservative
flux and centered differences. Shared squares feed the neighboring fluxes.
The nonlinear transport, destabilizing second derivative and stabilizing
fourth derivative all participate in each RK4 stage. h=1/64.

Main: 256 sites. Larger: 1,024. Lanes are zero and two exactly zero-mean
broadband perturbations. Measurements include mean drift, RMS, extrema,
linear drive and biharmonic dissipation. The conservative difference field
has zero sum in exact arithmetic. Its energy budget is not identical to
the continuum energy budget: the centered nonlinear flux does not satisfy
an exact discrete product rule.

Continuum reference: Cvitanovic, Davidchack and Siminos,
[On the State Space Geometry of the Kuramoto-Sivashinsky Flow](https://cns.gatech.edu/~siminos/papers/CDS10.pdf),
equation 2.1. We use the explicitly stated finite differences, not that
paper's Fourier implementation.

## Dense two-layer recurrent reservoir

An autonomous oscillator drives a bounded, recurrent neural map:

~~~text
hidden = clip(W1*r + input_gain*drive*(alternating q or p) + b1*drive)
target = clip(W2*hidden + input_gain*drive*(alternating p or q) + b2*drive)
r_next = r + leak*(target-r)
z_next = z + (eight group averages of old r - z)/16
q_next = q + h*p
p_next = p - h*q_next
clip(x) = max(-1,min(1,x))
~~~

Main: 96 recurrent values, 64 hidden values, eight readouts, q and p.
Larger: 192 recurrent values and 128 hidden values. Hidden/target values are
intermediates, not extra states. W1 and W2 are dense, deterministic signed
rational matrices; the integer mixer and every coefficient are in models.py.
Weights are nonzero, so every hidden result participates in every recurrent
output. Dot products use eight-term FMA blocks, then a left-to-right sum.
This fixes accumulation order without an excessively deep source expression.

leak=1/4, input_gain=1/4, h=1/32. The three drive lanes are 0, 1 and 5/4.
Clipping bounds the recurrent state, and the independent calibration reaches
both clipping regions. The driver conserves q^2+p^2+h*q*p in exact arithmetic.
Diagnostics measure its drift, recurrent range/RMS, readouts and the fraction
of recurrent values close to a clipping boundary.

This is a specified synthetic reservoir workload; its weights are not
trained for a prediction task. The map mixes one reservoir iteration with
an oscillator step, so h/2 plus twice the iterations is not a convergence
test of the same continuous system. Step-halving probes skip this family.

## Dense matrix Riccati flow

Every entry of P is a state component:

~~~text
P' = A*P + P*A^T + Q - gamma*P*P
A = -decay*I + omega*(forward_cyclic_shift - backward_cyclic_shift)
Q = I + v*v^T/16
v_i = ((7*i+3) modulo 11 - 5)/8
decay=1/8, omega=1/2, gamma=1/4
~~~

The source expands the linear shift terms per entry and computes every
dense matrix-product entry with the specified blocked FMA dots.
The fixed rational Q is positive definite and does not generally commute
with the rotation generator A. It sustains an anisotropic dense covariance.
Modulo is evaluated by the source generator, never by a runtime operation.

Main: 12x12 matrix. Larger: 32x32. Classical RK4 uses h=1/64.
Each matrix multiplication costs O(N^3), repeated at four stages.
The main state is relatively small while its stage graph is large; the
larger case combines 1,024 outputs and approximately 179,204 operations
per step. Lanes begin with an isotropic positive matrix and two dense
positive matrices built from a diagonal plus rank-two terms.

Diagnostics report trace, Frobenius norm, symmetry residual and an LDLT
factorization of the symmetrized result using 90-digit Decimal arithmetic.
The positive-pivot indicator is a numerical diagnostic, not a formal
positivity proof. It complements exact execution comparisons.
