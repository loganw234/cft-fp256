# The `hopf` photograph: a GPU's answer, as a program case

One real workload whose expected output this project did not compute.

atlas-engine's darkroom renders a plate by firing a deterministic camera
at it: one sample per lane, the sample index as the only input, and for
each sample five 32-bit words out - the pixel it lands on (`x`, `y`) and
three fixed-point colour channels (`r`, `g`, `b`). On 2026-09-18 that
camera, around the `hopf` plate, was lowered to a cft-fp256 sequencer
program - 1,081 instructions, straight-line, binary32, using `IMUL`,
indexed constants and thirty-two registers - and run for four passes of
1,048,576 samples each.

| file | what |
|---|---|
| `camera.cftp` | the program image (`BANK_EXT`: the constants arrive per run) |
| `camera.p0000.bank` ... `camera.p0003.bank` | one constant bank a pass |
| `deposits.SHA256` | the SHA-256 of each pass's deposit buffer **as an NVIDIA GPU recorded it** |
| `camera.json` | the case record: the frame, the levers, every file's hash, the GPU and its driver |
| `photo-gpu.json` | the GPU run's own record: the pinned GLSL's hashes, the uniforms, what each pass deposited (line endings normalised to LF; otherwise as handed over) |
| `print.png` | what the four passes add up to |

## Where the expected bits come from

Not from this project. The hashes in `deposits.SHA256` are of buffers an
**NVIDIA GeForce RTX 5060 Ti (driver 591.86, OpenGL 4.3)** wrote while
rendering the same frame from atlas-engine's pinned GLSL - 20,971,520
bytes a pass, five `u32` a sample, `x = 0xFFFFFFFF` where a sample
deposited nothing. The input needs no file: stream `a` is the sample
index, which `positive-run --iota 1048576` generates.

So this case asks one question of whatever runs it: **do you produce the
GPU's bytes?** On 2026-09-18 three implementations did, for all four
passes - the GPU that made the record, the U50's round-2 tile (1.2 s a
pass, atlas-engine's run), and this library's software backend (about
90 s a pass on one desktop core, this project's run). That is
docs/DETERMINISM.md's promise - same bits on any implementation of the
contract - met from the other side: the GPU was pinned to the contract's
primitives by atlas-engine's emitter, the tile has them by construction,
and they agree on a million samples of a real image.

## Running it

    python host/tests/photograph_check.py            # the software backend
    python host/tests/photograph_check.py --device <image.xclbin>

`verify/run.sh`'s `photograph` stage is the first of those. The four
passes run side by side, so it is about a minute and a half on a desktop
and the four hashes are the whole verdict. A pass that differs is named
with the hash it produced.

## Provenance

atlas-engine d4178cc, `tools/photo-gpu.py` and `tools/photo-cft.mjs
--pack`; handed over in `build/cft/handoff-2026-09-18.tar.gz`, whose
`photographs/hopf/` this directory is (without the 20 MB copy of pass
0's buffer and the GPU's summed planes, which the hashes stand for). Its
`docs/CFT-PHOTOGRAPH.md` is the narrative; this project's record is
docs/VALIDATION.md, 2026-09-18.
