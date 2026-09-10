// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft-resident: the engine's own rate, with the bus taken out of the
// measurement.
//
//   cft-resident <artifact.xclbin> [-n elements] [-r reps]
//                [-f fp32|fp64|fp128|fp256|all] [--op fma|add|mul|all]
//                [--cus N] [--csv]
//
// Everything libcft does on a call - cft_run - stages the operands
// across PCIe into device buffers and the result back, every call,
// which is why docs/BENCHMARKS.md's card numbers all land between 2 and
// 3 GB/s of staged traffic whatever the format and whatever the tile
// count: that is the bus, not the engine. This tool takes the bus out.
// It fills each compute unit's four buffers ONCE, then runs the kernel
// on them back to back and times only the runs. What it measures is the
// pipeline's rate at the card's clock against HBM - the number
// docs/SCALING.md projects from `make cycles` (1.250 cycles a beat
// marginal, 36 fixed: 108 M beats a second at 135 MHz) and this repo
// refused to publish until it was measured. It has been, twice: 59 M
// beats a second a tile on the revision-3 pair (2026-09-09), which is
// 2.25 cycles a beat and named the read path's latency as the wall,
// and 107 M on the read-ahead pair the same day. docs/BENCHMARKS.md,
// "The engine, measured", carries both.
//
// It is not only a stopwatch, because a rate without a correctness
// check is a number about nothing. Every compute unit gets the SAME
// operands, so after the timed runs the results must be identical
// across compute units, identical to one more run, and identical to
// libcft's software backend over the same operands - the last is the
// check the staged card numbers could not make at this rate, since at
// this rate the engine's flow control and its four masters are doing
// what a cocotb memory model only stood in for. STATUS (0x50) is read
// after the runs and must be zero: bits 2:0 are bus faults, bit 3 a
// refusal.
//
// XRT-only and C++ for the reason backend_xrt.cpp is; built with
// `make -C host XRT=1 cft-resident`. Runs on one compute unit or all
// of them at once; the aggregate is what a four-tile image gives when
// each tile has its own HBM group, which hw/link_quad.cfg arranges.

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "xrt/xrt_bo.h"
#include "xrt/xrt_device.h"
#include "xrt/xrt_kernel.h"

#include "cft.h"

namespace {

constexpr uint32_t CSR_FLAGS  = 0x40;
constexpr uint32_t CSR_STATUS = 0x50;
constexpr int ARG_A = 2, ARG_B = 3, ARG_C = 4, ARG_D = 5;

struct Fmt { const char *name; cft_format fmt; size_t esz; };
const Fmt FMTS[] = {{"fp32", CFT_FP32, 4}, {"fp64", CFT_FP64, 8},
                    {"fp128", CFT_FP128, 16}, {"fp256", CFT_FP256, 32}};
struct Op { const char *name; cft_op op; };
const Op OPS[] = {{"fma", CFT_FMA}, {"add", CFT_ADD}, {"mul", CFT_MUL}};

uint64_t xs(uint64_t &s) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }

// Random operands with the exponent held a few binades below one at
// every width - the top byte carries the sign and the exponent's high
// bits, and 0x3F there is "just under the bias" for all four formats -
// so the arithmetic is ordinary finite arithmetic that raises inexact
// and nothing else, rather than a stream of overflows. The point is
// the same result on every path, not a particular result.
void fill(std::vector<uint8_t> &v, size_t esz, uint64_t seed)
{
    uint64_t s = seed | 1;
    for (size_t i = 0; i < v.size(); i += esz) {
        for (size_t j = 0; j < esz; j += 8) {
            uint64_t w = xs(s);
            std::memcpy(&v[i + j], &w, std::min<size_t>(8, esz - j));
        }
        uint8_t &top = v[i + esz - 1];
        top = static_cast<uint8_t>((top & 0x80u) | 0x3Fu);
    }
}

uint64_t fnv(const uint8_t *p, size_t n)
{
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 1099511628211ull; }
    return h;
}

void usage()
{
    std::fprintf(stderr,
        "usage: cft-resident <artifact.xclbin> [-n elements] [-r reps]\n"
        "                    [-f fp32|fp64|fp128|fp256|all] [--op fma|add|mul|all]\n"
        "                    [--cus N] [--csv]\n"
        "  -n      elements per run, a multiple of 8 (default 1048576)\n"
        "  -r      timed repetitions after one warm-up (default 20)\n"
        "  --cus   compute units to run at once (default: all the image has)\n");
}

} // namespace

int main(int argc, char **argv)
{
    if (argc < 2) { usage(); return 2; }
    const char *art = argv[1];
    size_t n = 1u << 20;
    int reps = 20, want_cus = 0;
    bool csv = false;
    std::string fsel = "all", osel = "fma";
    for (int i = 2; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&](const char *what) -> const char * {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s needs a value\n", what); std::exit(2); }
            return argv[++i];
        };
        if (a == "-n") n = std::strtoull(next("-n"), nullptr, 10);
        else if (a == "-r") reps = std::atoi(next("-r"));
        else if (a == "-f") fsel = next("-f");
        else if (a == "--op") osel = next("--op");
        else if (a == "--cus") want_cus = std::atoi(next("--cus"));
        else if (a == "--csv") csv = true;
        else { usage(); return 2; }
    }
    if (n < 8 || n % 8 != 0 || reps < 1) { usage(); return 2; }

    xrt::device dev;
    xrt::uuid uuid;
    std::vector<xrt::kernel> ks;
    try {
        dev = xrt::device(0u);
        uuid = dev.load_xclbin(art);
        for (int i = 1; i <= 64; i++) {
            std::string nm = "cft_krnl:{cft_krnl_" + std::to_string(i) + "}";
            try {
                ks.emplace_back(dev, uuid, nm, xrt::kernel::cu_access_mode::exclusive);
            } catch (const std::exception &) {
                break;
            }
            if (want_cus > 0 && static_cast<int>(ks.size()) == want_cus)
                break;
        }
    } catch (const std::exception &e) {
        std::fprintf(stderr, "cft-resident: %s: %s\n", art, e.what());
        return 1;
    }
    if (ks.empty()) {
        std::fprintf(stderr, "cft-resident: no cft_krnl compute unit in %s\n", art);
        return 1;
    }
    const size_t cus = ks.size();

    cft_device *sw = nullptr;
    if (cft_open(nullptr, 0, &sw) != CFT_OK) {
        std::fprintf(stderr, "cft-resident: the software backend did not open\n");
        return 1;
    }

    std::printf("cft-resident: %s, %zu compute unit%s, n=%zu, %d timed reps after a warm-up; "
                "libcft ABI %u.%u\n", art, cus, cus == 1 ? "" : "s", n, reps,
                cft_abi_version() >> 16, cft_abi_version() & 0xFFFFu);
    if (csv)
        std::printf("format,op,cus,n,reps,ns_per_elem,melem_per_s,gb_per_s,mbeat_per_s_per_cu,"
                    "one_run_ms,status,flags_hw,flags_sw,sw_match,cu_match,repeat_match\n");
    else
        std::printf("%-6s %-4s %3s %10s %5s %9s %9s %8s %10s %9s  %s\n",
                    "format", "op", "cus", "n", "reps", "ns/elem", "Melem/s", "GB/s",
                    "Mbeat/s/cu", "1 run ms", "checks");

    int failures = 0;
    for (const Fmt &F : FMTS) {
        if (fsel != "all" && fsel != F.name) continue;
        for (const Op &O : OPS) {
            if (osel != "all" && osel != O.name) continue;
            const size_t bytes = n * F.esz;
            std::vector<uint8_t> a(bytes), b(bytes), c(bytes), d_sw(bytes);
            fill(a, F.esz, 0x9E3779B97F4A7C15ull);
            fill(b, F.esz, 0xD1B54A32D192ED03ull);
            fill(c, F.esz, 0x8CB92BA72F3D8DD7ull);
            uint32_t flags_sw = 0;
            if (cft_run(sw, O.op, F.fmt, CFT_RNE, a.data(), b.data(), c.data(),
                        d_sw.data(), n, &flags_sw, nullptr) != CFT_OK) {
                std::fprintf(stderr, "software cft_run failed for %s %s\n", F.name, O.name);
                return 1;
            }

            const uint32_t mode = static_cast<uint32_t>(O.op & 0xFF) |
                                  (static_cast<uint32_t>(F.fmt & 0xF) << 8) |
                                  (static_cast<uint32_t>(CFT_RNE & 0x7) << 12);
            std::vector<xrt::bo> ba, bb, bc, bd;
            try {
                for (size_t u = 0; u < cus; u++) {
                    ba.emplace_back(dev, bytes, xrt::bo::flags::normal, ks[u].group_id(ARG_A));
                    bb.emplace_back(dev, bytes, xrt::bo::flags::normal, ks[u].group_id(ARG_B));
                    bc.emplace_back(dev, bytes, xrt::bo::flags::normal, ks[u].group_id(ARG_C));
                    bd.emplace_back(dev, bytes, xrt::bo::flags::normal, ks[u].group_id(ARG_D));
                    std::memcpy(ba[u].map<uint8_t *>(), a.data(), bytes);
                    std::memcpy(bb[u].map<uint8_t *>(), b.data(), bytes);
                    std::memcpy(bc[u].map<uint8_t *>(), c.data(), bytes);
                    ba[u].sync(XCL_BO_SYNC_BO_TO_DEVICE);
                    bb[u].sync(XCL_BO_SYNC_BO_TO_DEVICE);
                    bc[u].sync(XCL_BO_SYNC_BO_TO_DEVICE);
                }
            } catch (const std::exception &e) {
                std::fprintf(stderr, "buffers for %s %s: %s\n", F.name, O.name, e.what());
                return 1;
            }

            auto launch = [&](size_t u) {
                return ks[u](mode, static_cast<uint64_t>(n), ba[u], bb[u], bc[u], bd[u]);
            };
            auto finish = [&](xrt::run &r) {
                ert_cmd_state st = r.wait(std::chrono::milliseconds(60000));
                if (st != ERT_CMD_STATE_COMPLETED) {
                    std::fprintf(stderr, "a compute unit did not complete (state %d)\n",
                                 static_cast<int>(st));
                    std::exit(1);
                }
            };

            // warm-up, and the one-run latency on the first unit alone
            for (size_t u = 0; u < cus; u++) { auto r = launch(u); finish(r); }
            auto t0 = std::chrono::steady_clock::now();
            { auto r = launch(0); finish(r); }
            auto t1 = std::chrono::steady_clock::now();
            const double one_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

            // the timed runs: every unit started, then every unit waited on
            std::vector<xrt::run> runs(cus);
            t0 = std::chrono::steady_clock::now();
            for (int rep = 0; rep < reps; rep++) {
                for (size_t u = 0; u < cus; u++) runs[u] = launch(u);
                for (size_t u = 0; u < cus; u++) finish(runs[u]);
            }
            t1 = std::chrono::steady_clock::now();
            const double secs = std::chrono::duration<double>(t1 - t0).count();
            const double elems = static_cast<double>(n) * cus * reps;
            const double ns_per = secs * 1e9 / elems;
            const double melem = elems / secs / 1e6;
            const double gbs = 4.0 * static_cast<double>(bytes) * cus * reps / secs / 1e9;
            const double mbeat_cu = (static_cast<double>(bytes) / 32.0) * reps / secs / 1e6;

            // the checks: status and flags per unit, results across
            // units, against software, and against one more run
            uint32_t status = 0, flags_hw = 0;
            for (size_t u = 0; u < cus; u++) {
                status |= ks[u].read_register(CSR_STATUS);
                flags_hw |= ks[u].read_register(CSR_FLAGS);
            }
            std::vector<uint8_t> d0(bytes), du(bytes);
            bd[0].sync(XCL_BO_SYNC_BO_FROM_DEVICE);
            std::memcpy(d0.data(), bd[0].map<uint8_t *>(), bytes);
            bool cu_match = true;
            for (size_t u = 1; u < cus; u++) {
                bd[u].sync(XCL_BO_SYNC_BO_FROM_DEVICE);
                std::memcpy(du.data(), bd[u].map<uint8_t *>(), bytes);
                if (std::memcmp(d0.data(), du.data(), bytes) != 0) cu_match = false;
            }
            const bool sw_match = std::memcmp(d0.data(), d_sw.data(), bytes) == 0;
            { auto r = launch(0); finish(r); }
            bd[0].sync(XCL_BO_SYNC_BO_FROM_DEVICE);
            const bool rep_match = std::memcmp(d0.data(), bd[0].map<uint8_t *>(), bytes) == 0;
            const bool ok = status == 0 && sw_match && cu_match && rep_match;
            if (!ok) failures++;

            if (csv)
                std::printf("%s,%s,%zu,%zu,%d,%.4f,%.2f,%.3f,%.2f,%.3f,0x%x,0x%x,0x%x,%d,%d,%d\n",
                            F.name, O.name, cus, n, reps, ns_per, melem, gbs, mbeat_cu, one_ms,
                            status, flags_hw, flags_sw, sw_match, cu_match, rep_match);
            else
                std::printf("%-6s %-4s %3zu %10zu %5d %9.4f %9.2f %8.3f %10.2f %9.3f  "
                            "status 0x%x flags hw 0x%x sw 0x%x  software %s  units %s  repeat %s  "
                            "d %016llx\n",
                            F.name, O.name, cus, n, reps, ns_per, melem, gbs, mbeat_cu, one_ms,
                            status, flags_hw, flags_sw,
                            sw_match ? "same" : "DIFFER", cu_match ? "same" : "DIFFER",
                            rep_match ? "same" : "DIFFER",
                            static_cast<unsigned long long>(fnv(d0.data(), bytes)));
            std::fflush(stdout);
        }
    }
    cft_close(sw);
    if (failures) {
        std::printf("%d row(s) FAILED a check\n", failures);
        return 1;
    }
    std::printf("every row: status clean, the same bytes on every unit, on repeat, and in software\n");
    return 0;
}
