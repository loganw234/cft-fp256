#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Installed as <LLVM>/bin/llvm-spirv (the real translator elsewhere). Stock
# clang-22's HIPSPV driver calls llvm-spirv with --spirv-max-version=1.1 and
# --spirv-ext=+all; chipStar's LLVM-22 patch (llvm-patches/llvm/0001-0004-
# spirv-version-and-extensions-llvm22.patch) makes it 1.2 and a short list.
# This wrapper applies the same two argument changes, so a PACKAGED clang-22
# can be used without a source build of LLVM.
REAL=${GPUC_REAL_LLVM_SPIRV:-/opt/gpu-c/spirv-tr/bin/llvm-spirv}
args=()
for a in "$@"; do
    case "$a" in
    --spirv-max-version=1.1) a=--spirv-max-version=1.2 ;;
    --spirv-ext=+all) a=--spirv-ext=-all,+SPV_INTEL_function_pointers,+SPV_INTEL_subgroups,+SPV_EXT_shader_atomic_float_add,+SPV_EXT_relaxed_printf_string_address_space ;;
    esac
    args+=("$a")
done
exec "$REAL" "${args[@]}"
