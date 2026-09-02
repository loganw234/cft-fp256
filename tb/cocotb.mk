# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
# cocotb build glue. Invoked by tb/Makefile with TOPLEVEL/MODULE set;
# not meant to be called directly.

TOPLEVEL_LANG = verilog
SIM ?= icarus

TBDIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
RTLDIR := $(abspath $(TBDIR)/../rtl)

export PYTHONPATH := $(TBDIR):$(abspath $(TBDIR)/../python):$(PYTHONPATH)

VERILOG_SOURCES = \
    $(RTLDIR)/cft_fpfma.sv \
    $(RTLDIR)/cft_fpfma_pipe.sv \
    $(RTLDIR)/cft_opmux.sv \
    $(RTLDIR)/cft_simpleops.sv \
    $(RTLDIR)/cft_csr.sv \
    $(RTLDIR)/cft_fifo.sv \
    $(RTLDIR)/cft_mulfrac.sv \
    $(RTLDIR)/cft_reduce_acc.sv \
    $(RTLDIR)/cft_normseg.sv \
    $(RTLDIR)/cft_seedop.sv \
    $(RTLDIR)/cft_engine.sv \
    $(RTLDIR)/cft_engine_stream.sv \
    $(RTLDIR)/cft_lanes.sv \
    $(RTLDIR)/cft_seq.sv \
    $(RTLDIR)/cft_krnl.sv \
    $(TBDIR)/wrappers/tb_fpfma_fp32.sv \
    $(TBDIR)/wrappers/tb_fpfma_fp64.sv \
    $(TBDIR)/wrappers/tb_fpfma_fp128.sv \
    $(TBDIR)/wrappers/tb_fpfma_fp256.sv \
    $(TBDIR)/wrappers/tb_krnl_quarter.sv \
    $(TBDIR)/wrappers/tb_mulshare.sv \
    $(TBDIR)/wrappers/cft_simpleops_ref.sv \
    $(TBDIR)/wrappers/tb_simpleops.sv \
    $(TBDIR)/wrappers/tb_normseg.sv \
    $(TBDIR)/wrappers/tb_normshare.sv \
    $(TBDIR)/wrappers/tb_seedop.sv \
    $(TBDIR)/wrappers/tb_reduce_acc.sv

ifeq ($(SIM),icarus)
# -I: cft_seedop.sv includes the generated ROM from rtl/.
COMPILE_ARGS += -g2012 -I$(RTLDIR)
# Top-level parameter overrides, Icarus form (-P<top>.<PARAM>=<value>),
# so one bench can run the kernel in a configuration the RTL default
# does not select - the fused-ladder build, for one. Empty by default.
COMPILE_ARGS += $(KRNL_PARAMS)
endif

ifeq ($(SIM),verilator)
# No width warnings are suppressed here any more. The blanket
# -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC that used to sit on this line was a
# concession from Verilator's first run against this suite; the audit
# it asked for has been done. Every site was triaged one at a time with
# the vector suite as the gate: most became explicit widths (zero-fill
# concatenation or a field select, provably the same bits), and the
# handful where a rewrite would obscure working arithmetic carry a
# lint_off pair scoped to the line, with the safety argument beside it
# (cft_fpfma_pipe S6, cft_seedop's exponent algebra, the frozen
# simpleops ref, and cft_engine_stream's hardcoded-width FIFOs - the
# last one an open finding, not a blessing).
#
# So a width warning from a Verilator build is now a regression, and
# fatal by default - which is the point. Argue a new site where it
# lives, not here.
EXTRA_ARGS += -I$(RTLDIR)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
