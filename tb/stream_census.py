"""Which cases of tb/test_seq_core.py run a program that STREAMS - one
longer than the instruction store - at a build's store and capacity,
counted without a simulator (2026-10-05, for tb/Makefile's seq_corestr).

Every case of the bench is run with cocotb stubbed and the Bench's steps
that touch the DUT made no-ops; each program the Bench is asked to run is
counted where Bench._budget sees it, which every run path calls. A program
streams when it has more instructions than the store holds - the bench's
own rule (Bench._budget: STREAMS and len(prog.insns) > IMEM_D).

A case that checks a cycle count or a planted fault stops at that check
here, since nothing ran: only its runs before it are counted, and the
census names each such case STOPPED with the assertion that stopped it.
So it counts programs, never results.

    python tb/stream_census.py [IMEM_D [STREAM_D]]    # default 64 65536
"""
import os
import sys
import types
from collections import defaultdict
from pathlib import Path

IMEM = sys.argv[1] if len(sys.argv) > 1 else "64"
STREAM = sys.argv[2] if len(sys.argv) > 2 else "65536"
os.environ["CFT_GENERICS"] = f"IMEM_D={IMEM} STREAM_D={STREAM}"
os.environ["CFT_SEQ_LAT"] = "0,125,256"


# ---- a cocotb that does nothing --------------------------------------
class _Now:
    def __await__(self):
        return
        yield


def _trig(*a, **k):
    return _Now()


async def _with_timeout(trigger, *a, **k):
    if hasattr(trigger, "__await__"):
        await trigger
    return None


class _Task:
    def kill(self):
        pass

    def cancel(self):
        pass

    def done(self):
        return True


def _start_soon(coro):
    try:
        coro.close()
    except Exception:
        pass
    return _Task()


def _test(*a, **k):
    if a and callable(a[0]) and not k:
        a[0]._is_test = True
        return a[0]

    def deco(f):
        f._is_test = True
        return f
    return deco


cocotb = types.ModuleType("cocotb")
cocotb.test = _test
cocotb.start_soon = cocotb.start = cocotb.fork = _start_soon
trig = types.ModuleType("cocotb.triggers")
for _name in ("ClockCycles", "ReadOnly", "RisingEdge", "FallingEdge", "Timer",
              "ReadWrite", "NextTimeStep", "Edge", "First", "Combine",
              "Event"):
    setattr(trig, _name, _trig)
trig.with_timeout = _with_timeout
clk = types.ModuleType("cocotb.clock")


class Clock:
    def __init__(self, *a, **k):
        pass

    async def start(self, *a, **k):
        return None


clk.Clock = Clock
utils = types.ModuleType("cocotb.utils")
_now = [0]


def get_sim_time(units="ns"):
    _now[0] += 4
    return _now[0]


utils.get_sim_time = get_sim_time
res = types.ModuleType("cocotb.result")


class SimTimeoutError(Exception):
    pass


res.SimTimeoutError = trig.SimTimeoutError = SimTimeoutError
cocotb.triggers, cocotb.clock, cocotb.utils, cocotb.result = \
    trig, clk, utils, res
for _m in (cocotb, trig, clk, utils, res):
    sys.modules[_m.__name__] = _m


# ---- a DUT whose every signal reads 0 ---------------------------------
class _Sig:
    def __init__(self):
        self.value = 0

    def __int__(self):
        return 0

    def __getitem__(self, k):
        return _Sig()

    def setimmediatevalue(self, v):
        self.value = v


class _Log:
    def info(self, *a, **k):
        pass

    warning = error = debug = info


class _Dut:
    def __init__(self):
        object.__setattr__(self, "_sigs", {})
        object.__setattr__(self, "_log", _Log())

    def __getattr__(self, name):
        s = self._sigs.get(name)
        if s is None:
            s = self._sigs[name] = _Sig()
        return s

    def __setattr__(self, name, v):
        self._sigs[name] = v


sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_seq_core as T  # noqa: E402

CUR = [None]
SEEN = defaultdict(list)


def _counting(orig):
    def budget(self, fmt, prog, n, image_bytes):
        SEEN[CUR[0]].append(len(prog.insns))
        return orig(self, fmt, prog, n, image_bytes)
    return budget


async def _nothing_async(self, *a, **k):
    return None


def _nothing(self, *a, **k):
    return None


async def _go(self, budget, label):
    self.lat = 0
    self.nrun += 1
    self.last_cycles = 0
    return 0, 0, 0


T.Bench._budget = _counting(T.Bench._budget)
T.Bench.start = _nothing_async
T.Bench._go = _go
for _name in ("_stage", "_drive_cfg", "_padding_selfcheck", "_compare",
              "_compare_masked", "_compare_lane_flags", "_compare_scratch_out",
              "_check_gather_reads", "_check_mask_reads"):
    if hasattr(T.Bench, _name):
        setattr(T.Bench, _name, _nothing)
for _name in ("assert_writes_inside", "assert_guards"):
    if hasattr(T.SeqRam, _name):
        setattr(T.SeqRam, _name, _nothing)
if hasattr(T, "_check_partial"):
    T._check_partial = lambda *a, **k: None


def _run(coro):
    try:
        while True:
            coro.send(None)
    except StopIteration:
        return None


def main():
    cases = [(n, f) for n, f in vars(T).items()
             if callable(f) and getattr(f, "_is_test", False)]
    cases.sort(key=lambda nf: nf[1].__code__.co_firstlineno)
    print(f"IMEM_D={T.IMEM_D} STREAM_D={T.STREAM_D} STREAMS={T.STREAMS}; "
          f"{len(cases)} cases")
    rows = []
    for name, f in cases:
        CUR[0] = name
        stop = ""
        try:
            _run(f(_Dut()))
        except BaseException as e:  # noqa: BLE001 - a stop is reported
            stop = f"{type(e).__name__}: {str(e)[:90]}"
        lens = SEEN[name]
        nstream = sum(1 for k in lens if k > T.IMEM_D)
        rows.append((name, len(lens), nstream, stop))
        print(f"{name:66s} runs {len(lens):5d} streamed {nstream:5d} "
              f"max {max(lens) if lens else 0:6d}"
              f"{'  STOPPED ' + stop if stop else ''}")
    print(f"TOTAL runs {sum(r[1] for r in rows)}, streamed "
          f"{sum(r[2] for r in rows)}; cases with a streamed run "
          f"{sum(1 for r in rows if r[2])} of {len(rows)}; stopped early "
          f"{sum(1 for r in rows if r[3])}")


if __name__ == "__main__":
    main()
