#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# What GPU-C installed in the WSL distro cft-gpu (Ubuntu 24.04), as one script:
# packaged LLVM 22 + SPIRV-LLVM-Translator + PoCL 7.2 + chipStar v1.3.0, into
# /opt/gpu-c (sources in /root/gpu-c). Run as root. No GPU driver. Nothing of
# Ubuntu's toolchain is replaced; the one file placed inside /usr/lib/llvm-22 is
# bin/llvm-spirv (the wrapper). Remove: see the ledger section in the study.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
J=${JOBS:-4}; S=/root/gpu-c; mkdir -p $S /opt/gpu-c
update-alternatives --get-selections > $S/alternatives.before.txt
# 1. apt.llvm.org, LLVM 22 only; key fingerprint 6084 F3CF 814B 57C1 CF12 EFD5 15CF 4D18 AF4F 7421
curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key -o /etc/apt/keyrings/gpu-c-apt.llvm.org.asc
gpg --show-keys --with-fingerprint /etc/apt/keyrings/gpu-c-apt.llvm.org.asc | grep -q "6084 F3CF 814B 57C1 CF12  EFD5 15CF 4D18 AF4F 7421"
echo "deb [signed-by=/etc/apt/keyrings/gpu-c-apt.llvm.org.asc] http://apt.llvm.org/noble/ llvm-toolchain-noble-22 main" \
    > /etc/apt/sources.list.d/gpu-c-llvm22.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    clang-22 clang-tools-22 llvm-22-dev libclang-22-dev libclang-cpp22-dev lld-22 ninja-build \
    ocl-icd-libopencl1 ocl-icd-opencl-dev opencl-headers clinfo spirv-tools spirv-headers libhwloc-dev \
    pkg-config libzstd-dev zlib1g-dev libedit-dev libxml2-dev python3-mpmath python3-pytest
# 2. SPIRV-LLVM-Translator llvm_release_220 with SPIRV-Headers at its pin (Ubuntu's headers are too old),
#    and chipStar's "shuffles need SPIR-V 1.2" patch applied by hand (line 917 of SPIRVEntry.h);
#    measured NOT needed for cft_fma.hip (it uses no sub-group operation), kept for chipStar's warp functions
cd $S
[ -d SPIRV-LLVM-Translator ] || git clone --depth 1 https://github.com/KhronosGroup/SPIRV-LLVM-Translator.git -b llvm_release_220
[ -d SPIRV-Headers ] || git clone https://github.com/KhronosGroup/SPIRV-Headers.git
git -C SPIRV-Headers checkout -q "$(cat SPIRV-LLVM-Translator/spirv-headers-tag.conf)"
sed -i '917s/SPIRV_1_3/SPIRV_1_2/' SPIRV-LLVM-Translator/lib/SPIRV/libSPIRV/SPIRVEntry.h
mkdir -p SPIRV-LLVM-Translator/build && cd SPIRV-LLVM-Translator/build
cmake -G Ninja .. -DCMAKE_BUILD_TYPE=Release -DLLVM_DIR=/usr/lib/llvm-22/lib/cmake/llvm \
    -DCMAKE_INSTALL_PREFIX=/opt/gpu-c/spirv-tr -DLLVM_EXTERNAL_SPIRV_HEADERS_SOURCE_DIR=$S/SPIRV-Headers
nice -n 10 ninja -j$J && ninja install
# 3. the wrapper stock clang-22's HIPSPV driver finds as llvm-spirv
install -m 755 "$here/llvm-spirv-wrapper.sh" /usr/lib/llvm-22/bin/llvm-spirv
# 4. PoCL 7.2 (Canonical's is 5.0), CPU device with SPIR-V
cd $S; [ -d pocl ] || git clone --depth 1 https://github.com/pocl/pocl.git -b v7.2
mkdir -p pocl/build && cd pocl/build
cmake -G Ninja .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/gpu-c/pocl \
    -DWITH_LLVM_CONFIG=/usr/lib/llvm-22/bin/llvm-config -DHOST_LLVM_SPIRV=/opt/gpu-c/spirv-tr/bin/llvm-spirv \
    -DENABLE_TESTS=OFF -DENABLE_EXAMPLES=OFF -DENABLE_ICD=ON
nice -n 10 ninja -j$J && ninja install      # its ICD file lands in /etc/opt/gpu-c/pocl/OpenCL/vendors
# 5. chipStar v1.3.0, samples off (a CUDA sample needs SPIR-V 1.6 and stops the build)
cd $S; [ -d chipStar ] || git clone --depth 1 --recurse-submodules --shallow-submodules https://github.com/CHIP-SPV/chipStar.git -b v1.3.0
mkdir -p chipStar/build && cd chipStar/build
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release -DLLVM_CONFIG_BIN=/usr/lib/llvm-22/bin/llvm-config \
    -DCMAKE_INSTALL_PREFIX=/opt/gpu-c/chipstar -DCHIP_BUILD_TESTS=OFF -DCHIP_BUILD_SAMPLES=OFF
nice -n 10 ninja -j$J install
update-alternatives --get-selections > $S/alternatives.after.txt
diff $S/alternatives.before.txt $S/alternatives.after.txt || true
echo "run with: OCL_ICD_VENDORS=/etc/opt/gpu-c/pocl/OpenCL/vendors CHIP_BE=opencl CHIP_DEVICE_TYPE=pocl"
