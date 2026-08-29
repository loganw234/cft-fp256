# cft-golden

The exact reference model for the cft-fp256 tile: integer-only IEEE
754-2019 binary arithmetic for fp32/fp64/fp128/fp256, the operand
steering contract shared with the RTL, and deterministic
conformance-vector generation.

Install for development (optional - the testbenches use PYTHONPATH):

```
pip install -e python/[test]
```

Self-tests, which cross-check the model against two independent
implementations (native binary64 hardware via CPython, and mpmath):

```
pytest python/tests -q
```
