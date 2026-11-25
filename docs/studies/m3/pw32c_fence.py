# M3 model: the fence's second process (parcel M3XN2). It imports pw32c FIRST
# (so that any module state pw32c's import changes is in place), then runs
# pw32n_run.py's own main under __main__ with the arguments given, so that the
# four outputs of pown and rootn (costs, live, bound pown 300, bound rootn 300)
# can be regenerated "with pw32c imported" and compared to the committed ones:
#
#   python pw32c_fence.py MODE args      (from docs/studies/m3)
import runpy
import sys

import pw32c                                    # noqa: F401  imported first

sys.argv = ["pw32n_run.py"] + sys.argv[1:]
runpy.run_path("pw32n_run.py", run_name="__main__")
