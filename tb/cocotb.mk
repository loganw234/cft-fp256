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
    $(RTLDIR)/cft_engine.sv \
    $(RTLDIR)/cft_engine_stream.sv \
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
    $(TBDIR)/wrappers/tb_reduce_acc.sv

ifeq ($(SIM),icarus)
COMPILE_ARGS += -g2012
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
