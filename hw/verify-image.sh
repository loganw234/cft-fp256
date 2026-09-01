#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Static verifier for a built xclbin: prove the file on disk is the
# build its manifest describes, BEFORE it is loaded onto a card.
#
#   bash hw/verify-image.sh <artifact.xclbin> [manifest]
#
# The manifest defaults to the artifact's sibling: first
# <artifact-minus-.xclbin>.manifest.txt, else the single *manifest*
# file in the same directory. Manifests are the ones rebuild-2022.sh
# writes.
#
# The failure class this exists for is "wrong file staged": a quad
# image under a single manifest, an hw_emu link renamed for card day,
# a stale sweep artifact that looks identical from the outside. Every
# xclbin of this project is a ~35-50 MB opaque blob named cft_hw.xclbin
# at birth; the only trustworthy identity it has is its sha256, and the
# only record of what that hash MEANS is the manifest. So the artifact
# filename is deliberately never checked against the manifest's
# artifact: line - the card-day set is renamed on purpose (cft_hw.xclbin
# -> cft_hw_quad.xclbin), and rebuild-2022.sh's own manifest comment
# promises the hash works "even if the file was copied to another
# machine under a different name".
#
# Reporting contract, which matters more than any single check: a check
# that cannot run on this image is reported as SKIP by name, never
# silently passed - a verifier that quietly checked nothing is the
# failure mode this repo hates most. And a section that OUGHT to exist
# (a hardware image without IP_LAYOUT is not a hardware image) is a
# FAIL, not a SKIP: absence is only excusable where image types
# genuinely differ (hw_emu links carry a different section set).
set -euo pipefail

ART=${1:?usage: verify-image.sh <artifact.xclbin> [manifest]}
[ -f "$ART" ] || { echo "ERROR: no such artifact: $ART" >&2; exit 1; }
ART=$(readlink -f "$ART")
ARTDIR=$(dirname "$ART")

# --- resolve the manifest ---------------------------------------------
# Prefer the derived name (cft_hw_quad.xclbin -> cft_hw_quad.manifest.txt)
# because a directory can legitimately hold several artifact/manifest
# pairs; fall back to a lone *manifest* sibling; refuse to guess among
# several. Guessing wrong here would verify the artifact against the
# OTHER build's manifest, which is the exact confusion this script
# exists to catch, not to commit.
if [ $# -ge 2 ]; then
  MAN=$2
else
  MAN="${ART%.xclbin}.manifest.txt"
  if [ ! -f "$MAN" ]; then
    cands=()
    for m in "$ARTDIR"/*manifest*; do
      if [ -f "$m" ]; then cands+=("$m"); fi
    done
    if [ ${#cands[@]} -eq 1 ]; then
      MAN=${cands[0]}
    elif [ ${#cands[@]} -eq 0 ]; then
      echo "ERROR: no manifest beside $ART" >&2
      echo "       (rebuild-2022.sh writes one; or name it explicitly)" >&2
      exit 1
    else
      echo "ERROR: several manifests beside $ART - pick one explicitly:" >&2
      printf '       %s\n' "${cands[@]}" >&2
      exit 1
    fi
  fi
fi
[ -f "$MAN" ] || { echo "ERROR: no such manifest: $MAN" >&2; exit 1; }
MAN=$(readlink -f "$MAN")

# --- tools ------------------------------------------------------------
# xclbinutil ships with XRT, same sourcing dance as run-device-test.sh.
for r in /opt/xilinx/xrt /usr/local/xrt; do
  [ -f "$r/setup.sh" ] && { set +u; source "$r/setup.sh" >/dev/null; set -u; break; }
done
command -v xclbinutil >/dev/null || {
  echo "ERROR: xclbinutil not found. It ships with XRT:" >&2
  echo "       source /opt/xilinx/xrt/setup.sh   and re-run." >&2
  echo "       Without it only the sha256 could be checked, and a" >&2
  echo "       verifier that runs one check out of eight should say" >&2
  echo "       so loudly rather than exit 0 - so it refuses instead." >&2
  exit 1; }
# The topology sections are JSON; walking nested JSON in awk means a
# hand parser that has to stay in step with xclbinutil's printer, and
# patterns that track a vendor's formatting drift out of step silently
# (run-device-test.sh learned that from socket names). Every XRT host
# has python3 - XRT's own tooling is written in it.
command -v python3 >/dev/null || {
  echo "ERROR: python3 not found (needed to parse xclbinutil's JSON)" >&2
  exit 1; }

SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

# --- manifest keys ----------------------------------------------------
mkey() { sed -n "s/^$1:[[:space:]]*//p" "$MAN" | head -1 \
         | sed 's/[[:space:]]*$//'; }
M_SHA=$(mkey sha256);       M_BYTES=$(mkey bytes)
M_TARGET=$(mkey target);    M_PLATFORM=$(mkey platform)
M_LINKCFG=$(mkey link_cfg); M_FREQ=$(mkey kernel_freq)
M_CUS=$(mkey clock_cus);    M_CLOCKARG=$(mkey clock_arg)
for req in M_SHA:sha256 M_TARGET:target M_PLATFORM:platform \
           M_LINKCFG:link_cfg M_FREQ:kernel_freq M_CUS:clock_cus; do
  v=${req%%:*}; k=${req#*:}
  [ -n "${!v}" ] || { echo "ERROR: manifest has no '$k:' line - not a" >&2
                      echo "       rebuild-2022.sh manifest? $MAN" >&2; exit 1; }
done

echo "== verify-image"
echo "   artifact: $ART"
echo "   manifest: $MAN"
echo "   target:   $M_TARGET"

# --- verdict ledger ---------------------------------------------------
NPASS=0; NFAIL=0; NSKIP=0
LEDGER=()
verdict() {  # PASS|FAIL|SKIP <name> [detail]
  case "$1" in
    PASS) NPASS=$((NPASS+1));; FAIL) NFAIL=$((NFAIL+1));;
    SKIP) NSKIP=$((NSKIP+1));;
  esac
  printf '%s: %s%s\n' "$1" "$2" "${3:+ - $3}"
  LEDGER+=("$1  $2")
}

# --- 1. identity: sha256 ----------------------------------------------
# Size first: a truncated copy fails the hash too, but "51118985 bytes
# expected, 40894464 on disk" names the disease (interrupted scp) where
# a hash mismatch only names the symptom.
if [ -n "$M_BYTES" ]; then
  bytes=$(stat -c%s "$ART")
  if [ "$bytes" != "$M_BYTES" ]; then
    verdict FAIL "size" "$bytes bytes on disk, manifest says $M_BYTES (truncated copy?)"
  fi
fi
sha=$(sha256sum "$ART" | cut -d' ' -f1)
if [ "$sha" = "$M_SHA" ]; then
  verdict PASS "sha256" "$sha"
else
  verdict FAIL "sha256" "artifact $sha != manifest $M_SHA - this is NOT the build the manifest describes; nothing below can rehabilitate it"
fi

# --- dump what the image says about itself ----------------------------
INFO="$SCRATCH/info.txt"
xclbinutil -i "$ART" --info >"$INFO" 2>"$SCRATCH/info.err" || {
  echo "ERROR: xclbinutil cannot read $ART:" >&2
  cat "$SCRATCH/info.err" >&2
  exit 1; }
# Trailing whitespace is trimmed because xclbinutil pads some lines to
# a fixed width, and an invisible trailing space breaks an = compare.
ikey() { sed -n "s/^[[:space:]]*$1:[[:space:]]*//p" "$INFO" | head -1 \
         | sed 's/[[:space:]]*$//'; }

# Section presence is probed by attempting the dump, not by parsing
# --info's "Sections:" list - that list line-wraps at the tool's whim.
# A missing section leaves no file and says "does not exists" (vendor
# spelling); anything else stderr says is a real error and stops the
# run rather than becoming a quiet SKIP.
dump() {  # <SECTION> <FORMAT> -> path on stdout, or "" if absent
  local sec=$1 fmt=$2 out="$SCRATCH/$1.$2"
  if xclbinutil -i "$ART" --dump-section "$sec:$fmt:$out" \
       >/dev/null 2>"$SCRATCH/$sec.err"; then
    echo "$out"
  elif grep -qi "does not exist" "$SCRATCH/$sec.err"; then
    echo ""
  else
    echo "ERROR: xclbinutil failed dumping $sec:" >&2
    cat "$SCRATCH/$sec.err" >&2
    exit 1
  fi
}
IPL=$(dump IP_LAYOUT JSON)
CON=$(dump CONNECTIVITY JSON)
MEM=$(dump MEM_TOPOLOGY JSON)
CLK=$(dump CLOCK_FREQ_TOPOLOGY JSON)
BMD=$(dump BUILD_METADATA JSON)
EMB=$(dump EMBEDDED_METADATA RAW)

# A section a hardware image always carries (every hw link this repo
# has ever produced has all six) may only be absent from other image
# types; for those the honest answer is SKIP by name. For target hw,
# absence IS the finding.
absent() {  # <check-name> <section-name>
  if [ "$M_TARGET" = "hw" ]; then
    verdict FAIL "$1" "$2 section absent from a target-hw image - no hardware link produces that; wrong or mutilated file"
  else
    verdict SKIP "$1" "$2 section absent from this $M_TARGET image, so this check checked NOTHING - do not read the final verdict as covering it"
  fi
}

# --- 2. platform ------------------------------------------------------
vbnv=$(ikey "Platform VBNV")
if [ -z "$vbnv" ]; then
  verdict FAIL "platform" "no Platform VBNV in xclbinutil --info output"
elif [ "$vbnv" = "$M_PLATFORM" ]; then
  verdict PASS "platform" "$vbnv"
else
  verdict FAIL "platform" "image $vbnv != manifest $M_PLATFORM"
fi

# --- 3. content vs target ---------------------------------------------
# An hw_emu build renamed to look like hardware loads nowhere and eats
# card time diagnosing it; the header's Content field tells them apart
# without guessing from filenames.
content=$(ikey "Content")
case "$M_TARGET" in
  hw)
    if [ "$content" = "Bitstream" ]; then
      verdict PASS "content" "Bitstream, as a hw target must be"
    else
      verdict FAIL "content" "manifest says target hw but image content is '$content' - an emulation build staged as hardware?"
    fi ;;
  *)
    if [ "$content" = "Bitstream" ]; then
      verdict FAIL "content" "manifest says target $M_TARGET but image is a hardware Bitstream - a hardware build staged under an emulation manifest"
    else
      verdict PASS "content" "'$content' for target $M_TARGET"
    fi ;;
esac

# --- 4. compute units -------------------------------------------------
# The manifest's clock_cus is derived from the link cfg's nk= line
# (rebuild-2022.sh insists on that single source of truth), so it is
# exactly the CU list the build intended. The image's IP_LAYOUT is the
# CU list the build PRODUCED. Set-equal, both directions: a missing CU
# is a wrong image, an extra one is a wrong image with company.
if [ -n "$IPL" ]; then
  img_cus=$(python3 - "$IPL" <<'PYEOF'
import json, sys
ips = json.load(open(sys.argv[1]))["ip_layout"]["m_ip_data"]
insts = [ip["m_name"].split(":", 1)[1] for ip in ips
         if ip.get("m_type") == "IP_KERNEL"]
print(" ".join(sorted(insts)))
PYEOF
)
  man_cus=$(echo "$M_CUS" | tr '.' '\n' | sort | paste -sd' ')
  if [ "$img_cus" = "$man_cus" ]; then
    n=$(echo "$img_cus" | wc -w)
    verdict PASS "compute units" "$n CU(s): $img_cus"
  else
    verdict FAIL "compute units" "image has [$img_cus], manifest clock_cus says [$man_cus]"
  fi
else
  absent "compute units" IP_LAYOUT
fi

# --- v++'s own record of the link -------------------------------------
# BUILD_METADATA carries the verbatim v++ command line, and three of
# the manifest's claims (link_cfg, kernel_freq, clock_arg) live nowhere
# else in the image. In particular the kernel clock: on this shell the
# constraint is implemented by a clocking wizard configured statically
# INSIDE the bitstream (clk_out1_ulp_clk_wiz_0 - the same net the
# manifest's timing split keys on), so CLOCK_FREQ_TOPOLOGY never hears
# about it; see check 6.
VPP=""
if [ -n "$BMD" ]; then
  VPP=$(python3 - "$BMD" <<'PYEOF'
import json, sys
b = json.load(open(sys.argv[1]))["build_metadata"]
print(b["xclbin"]["generated_by"].get("options", ""))
PYEOF
)
fi
# <flag> -> its value in the recorded command line ("" if not present)
vpp_opt() {
  printf '%s\n' "$VPP" | awk -v f="$1" \
    '{ for (i=1; i<NF; i++) if ($i == f) { print $(i+1); exit } }'
}

# A present BUILD_METADATA that records no options is its own state,
# distinct from an absent section - the message must not claim a
# section is missing when it is merely empty.
vpp_gone() {  # <check-name>
  if [ -z "$BMD" ]; then
    absent "$1" BUILD_METADATA
  elif [ "$M_TARGET" = "hw" ]; then
    verdict FAIL "$1" "BUILD_METADATA present but records no v++ command line"
  else
    verdict SKIP "$1" "BUILD_METADATA present but records no v++ command line, so this check checked NOTHING"
  fi
}

# --- 5a. link config --------------------------------------------------
if [ -n "$VPP" ]; then
  cfg=$(vpp_opt --config)
  if [ -z "$cfg" ]; then
    verdict FAIL "link config" "v++ command line records no --config"
  elif [ "$cfg" = "$M_LINKCFG" ]; then
    verdict PASS "link config" "$cfg"
  elif [ "$(basename "$cfg")" = "$(basename "$M_LINKCFG")" ]; then
    # Same file reached by a different path (a sweep links from its own
    # directory). The basename is what distinguishes link.cfg from
    # link_quad.cfg, which is the mix-up that matters.
    verdict PASS "link config" "$cfg (path differs from manifest's $M_LINKCFG; same file name)"
  else
    verdict FAIL "link config" "image built with --config $cfg, manifest says $M_LINKCFG"
  fi
else
  vpp_gone "link config"
fi

# --- 5b. kernel clock constraint --------------------------------------
if [ -n "$VPP" ]; then
  carg=$(vpp_opt --clock.freqHz)
  if [ -z "$carg" ]; then
    if [ "$M_TARGET" = "hw" ]; then
      # rebuild-2022.sh always passes the constraint for -t hw, and a
      # hw image without it runs the CUs at the platform default -
      # roughly double this design's ceiling, the expensive silent
      # failure that script's CLOCK_CUS validation exists to prevent.
      verdict FAIL "kernel clock" "no --clock.freqHz on the recorded v++ line of a target-hw image"
    else
      verdict SKIP "kernel clock" "no --clock.freqHz recorded; rebuild-2022.sh only applies the constraint to hw links, so for $M_TARGET there is nothing to check"
    fi
  else
    freq=${carg%%:*}
    cus=$(echo "${carg#*:}" | tr ',' '\n' | sed 's/\.ap_clk$//' | sort | paste -sd' ')
    want_cus=$(echo "$M_CUS" | tr '.' '\n' | sort | paste -sd' ')
    if [ "$freq" != "$M_FREQ" ]; then
      verdict FAIL "kernel clock" "image linked at ${freq} Hz, manifest says ${M_FREQ} Hz"
    elif [ "$cus" != "$want_cus" ]; then
      verdict FAIL "kernel clock" "constraint names [$cus], manifest clock_cus says [$want_cus] - unnamed CUs run at the platform default"
    elif [ -n "$M_CLOCKARG" ] && [ "$carg" != "$M_CLOCKARG" ]; then
      verdict FAIL "kernel clock" "constraint '$carg' != manifest clock_arg '$M_CLOCKARG'"
    else
      verdict PASS "kernel clock" "${freq} Hz on $(echo "$cus" | wc -w) CU(s)"
    fi
  fi
else
  vpp_gone "kernel clock"
fi

# --- 6. clock topology ------------------------------------------------
# Sanity only, and deliberately NOT where kernel_freq is asserted. The
# section lists the SHELL's scalable clocks (hbm_aclk 450, KERNEL_CLK
# 500, DATA_CLK 300 on this platform) - the clock-wizard INPUTS, which
# XRT programs at load. The wizard's 130 MHz output exists only in the
# bitstream and the v++ line. Asserting manifest kernel_freq against
# KERNEL_CLK here would fail every good image ever built; asserting
# nothing while claiming to have "checked clocks" would be worse.
if [ -n "$CLK" ]; then
  clocks=$(python3 - "$CLK" <<'PYEOF'
import json, sys
cf = json.load(open(sys.argv[1]))["clock_freq_topology"]["m_clock_freq"]
kern = [c for c in cf if c.get("m_type") == "KERNEL"]
if not kern:
    print("NOKERNEL")
else:
    print("; ".join(f'{c["m_name"]} {c["m_freq_Mhz"]} MHz ({c["m_type"]})'
                    for c in cf))
PYEOF
)
  if [ "$clocks" = "NOKERNEL" ]; then
    verdict FAIL "clock topology" "no KERNEL-type clock in CLOCK_FREQ_TOPOLOGY"
  else
    verdict PASS "clock topology" "shell clocks: $clocks (kernel constraint checked from BUILD_METADATA, not here - see comment)"
  fi
else
  absent "clock topology" CLOCK_FREQ_TOPOLOGY
fi

# --- 7. memory topology intent ----------------------------------------
# The property the link cfgs exist to establish: every AXI master of
# every CU talks to HBM pseudo-channels, and NO pseudo-channel is
# shared between two masters, anywhere in the image.
#
# Disjointness is load-bearing for correctness, not just bandwidth.
# The engine pipelines ARs on a single AXI ID with no reorder buffer;
# AXI only guarantees same-ID responses return in issue order. A
# master whose channels are its own gets that ordering from the
# channel; two masters meeting in one channel puts back both the
# contention and the ordering dependence the split exists to remove.
# And a wrong sp= line does not fail the BUILD - v++ links it quietly
# (hw/link_quad.cfg documents this) - so the image is the only place
# the mistake shows.
#
# One channel per master, exactly, is the current cfgs' stricter form
# of the same intent (ordering by construction rather than by trusting
# the HBM switch across destinations - the 2026-08-30 audit). Earlier
# links, the card-day pair included, span a master across 2 or 4
# channels, still disjoint. Disjointness is asserted; the span per
# master is reported so a pre-audit layout is visible, not failed.
#
# CONNECTIVITY is per-ARGUMENT; the arg->port map in the embedded
# kernel XML folds args into the masters that actually issue the AXI
# transactions. (For cft_krnl they are 1:1 - hw/kernel.xml gives each
# operand stream its own master precisely so the channel split can
# exist.) Without EMBEDDED_METADATA the check falls back to
# per-argument granularity, which for this kernel is the same thing -
# and says so, rather than silently meaning something different.
if [ -n "$CON" ] && [ -n "$MEM" ] && [ -n "$IPL" ]; then
  memrep="$SCRATCH/memcheck.txt"
  memok=0
  python3 - "$IPL" "$MEM" "$CON" "${EMB:-}" >"$memrep" 2>&1 <<'PYEOF' || memok=$?
import json, re, sys

ipl, mem, con = (json.load(open(p)) for p in sys.argv[1:4])
ips  = ipl["ip_layout"]["m_ip_data"]
mems = mem["mem_topology"]["m_mem_data"]
cons = con["connectivity"]["m_connection"]

# arg id -> port name, from the kernel XML v++ embeds. Attribute order
# is not assumed.
argport = {}
if len(sys.argv) > 4 and sys.argv[4]:
    xml = open(sys.argv[4], errors="replace").read()
    for tag in re.findall(r"<arg\b[^>]*>", xml):
        m_id   = re.search(r'\bid="(\d+)"', tag)
        m_port = re.search(r'\bport="([^"]+)"', tag)
        if m_id and m_port:
            argport[int(m_id.group(1))] = m_port.group(1)

fail = []
masters = {}          # (cu, port) -> sorted set of channel tags
cu_of = {}
for i, ip in enumerate(ips):
    if ip.get("m_type") == "IP_KERNEL":
        cu_of[i] = ip["m_name"].split(":", 1)[1]

for c in cons:
    ipi  = int(c["m_ip_layout_index"])
    argi = int(c["arg_index"])
    memi = int(c["mem_data_index"])
    if ipi not in cu_of:
        fail.append(f"connection from non-kernel IP index {ipi}")
        continue
    cu = cu_of[ipi]
    port = argport.get(argi, f"arg{argi}")
    if memi >= len(mems):
        fail.append(f"{cu}.{port}: mem index {memi} beyond MEM_TOPOLOGY")
        continue
    bank = mems[memi]
    tag = bank.get("m_tag", "?")
    # Match the tag, not m_type: v++ types HBM[0] as MEM_HBM and
    # HBM[1..31] as MEM_DRAM in the same image. The tag is what the
    # sp= lines named and is the stable identity.
    if not re.fullmatch(r"HBM\[\d+\]", tag):
        fail.append(f"{cu}.{port} connects to {tag}, not an HBM pseudo-channel")
    if str(bank.get("m_used", "1")) not in ("1", "true"):
        fail.append(f"{cu}.{port} connects to {tag} which MEM_TOPOLOGY marks unused")
    masters.setdefault((cu, port), set()).add(tag)

if not masters:
    fail.append("CONNECTIVITY has no kernel master connections at all")

for cu in cu_of.values():
    if not any(k[0] == cu for k in masters):
        fail.append(f"{cu} has no AXI master connections")

# The heart of it: no channel in two masters' sets.
owner = {}
for (cu, port), chans in sorted(masters.items()):
    for ch in chans:
        if ch in owner:
            fail.append(f"{ch} shared between {owner[ch]} and {cu}.{port} "
                        f"- same-ID ordering and bandwidth isolation both lost")
        else:
            owner[ch] = f"{cu}.{port}"

# Numeric where the tag is HBM[n]; a failing image may have carried a
# non-HBM tag this far and a report about a broken image must not
# crash on the brokenness it is reporting.
def hkey(t):
    m = re.fullmatch(r"HBM\[(\d+)\]", t)
    return (0, int(m.group(1)), t) if m else (1, 0, t)
spans = set()
for (cu, port), chans in sorted(masters.items()):
    spans.add(len(chans))
    print(f"    {cu}.{port} -> {' '.join(sorted(chans, key=hkey))}")
if spans - {1}:
    print("    note: master(s) span >1 channel - a pre-audit layout; "
          "disjointness holds, but same-ID ordering rests on the HBM "
          "switch, not on the channel (see hw/link.cfg)")

for f in fail:
    print("    FAIL:", f)
sys.exit(1 if fail else 0)
PYEOF
  cat "$memrep"
  nmast=$(grep -c ' -> ' "$memrep" || true)
  if [ "$memok" -eq 0 ]; then
    detail="$nmast masters, all channels HBM, no channel shared"
    [ -z "$EMB" ] && detail="$detail (per-argument granularity: EMBEDDED_METADATA absent)"
    verdict PASS "memory intent" "$detail"
  else
    verdict FAIL "memory intent" "see lines above"
  fi
else
  missing=""
  [ -z "$CON" ] && missing="CONNECTIVITY"
  [ -z "$MEM" ] && missing="${missing:+$missing,}MEM_TOPOLOGY"
  [ -z "$IPL" ] && missing="${missing:+$missing,}IP_LAYOUT"
  absent "memory intent" "$missing"
fi

# --- verdict ----------------------------------------------------------
echo "== verdicts"
printf '   %s\n' "${LEDGER[@]}"
if [ "$NFAIL" -gt 0 ]; then
  echo "== FAIL: $NFAIL of $((NPASS+NFAIL+NSKIP)) checks failed - do not stage this pairing"
  exit 1
fi
if [ "$NPASS" -eq 0 ]; then
  # All-SKIP is not a pass. Nothing was verified, and exit 0 here
  # would be the quiet nothing-check this script exists to kill.
  echo "== FAIL: every check skipped; nothing was actually verified"
  exit 1
fi
if [ "$NSKIP" -gt 0 ]; then
  echo "== PASS with gaps: $NPASS passed, $NSKIP skipped BY NAME above ($M_TARGET image) - passed checks are green, skipped ones are unknown, not green"
else
  echo "== PASS: all $NPASS checks passed - image matches its manifest"
fi
