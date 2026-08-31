// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_simpleops_ref: the flat case(op) form of cft_simpleops, frozen.
//
// This is a byte copy of rtl/cft_simpleops.sv as of 7ab02b3, with the
// module renamed and nothing else changed. It exists so the area
// rewrite is checked against the implementation it replaced rather
// than only against the golden model - the same argument tb_mulshare
// makes for the shared multiplier array. Both halves see the same
// inputs and their outputs must be identical bit for bit, which is a
// stronger and much cheaper claim than "both independently agree with
// Python", and it catches the cases a model comparison would need
// separate vectors to reach: reserved opcodes, the arithmetic group's
// unread default, and flags on operands the model never emits.
//
// It is a testbench artifact. Nothing synthesises it, and it must not
// be edited to track changes in the real module - a reference that
// follows the thing it checks is not a reference.

`timescale 1ns/1ps

module cft_simpleops_ref #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input  logic [7:0]           op,
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    input  logic [EXP_W+MAN_W:0] c,
    output logic                 valid,
    output logic [EXP_W+MAN_W:0] d,
    output logic [4:0]           flags
);

  localparam int W = 1 + EXP_W + MAN_W;
  localparam int FL_INVALID = 0;

  localparam logic [7:0] OP_ABS = 8'd4;
  localparam logic [7:0] OP_NEG = 8'd5;
  localparam logic [7:0] OP_COPYSIGN = 8'd6;
  localparam logic [7:0] OP_MIN = 8'd7;
  localparam logic [7:0] OP_MAX = 8'd8;
  localparam logic [7:0] OP_MINNUM = 8'd9;
  localparam logic [7:0] OP_MAXNUM = 8'd10;
  localparam logic [7:0] OP_SELECT = 8'd11;
  localparam logic [7:0] OP_CMPLT = 8'd12;
  localparam logic [7:0] OP_CMPLE = 8'd13;
  localparam logic [7:0] OP_CMPEQ = 8'd14;
  localparam logic [7:0] OP_IAND   = 8'd16;
  localparam logic [7:0] OP_IOR    = 8'd17;
  localparam logic [7:0] OP_IXOR   = 8'd18;
  localparam logic [7:0] OP_IADD   = 8'd19;
  localparam logic [7:0] OP_ISUB   = 8'd20;
  localparam logic [7:0] OP_ISHL   = 8'd21;
  localparam logic [7:0] OP_ISHR   = 8'd22;
  localparam logic [7:0] OP_ICMPLT = 8'd23;

  localparam int BIAS = (1 << (EXP_W - 1)) - 1;
  localparam int SHB  = $clog2(W);

  logic [W-1:0]     qnan, one, pzero;
  logic [EXP_W-1:0] bias_f;
  assign qnan   = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};
  assign bias_f = BIAS;
  assign one    = {1'b0, bias_f, {MAN_W{1'b0}}};
  assign pzero  = '0;

  logic             sa, sb;
  logic [EXP_W-1:0] ea, eb;
  logic [MAN_W-1:0] fra, frb;
  logic             a_nan, b_nan, a_snan, b_snan, a_zero, b_zero;
  logic [W-2:0]     mag_a, mag_b;
  logic             a_lt_b, both_zero;

  assign sa  = a[W-1];
  assign sb  = b[W-1];
  assign ea  = a[W-2 -: EXP_W];
  assign eb  = b[W-2 -: EXP_W];
  assign fra = a[MAN_W-1:0];
  assign frb = b[MAN_W-1:0];

  assign a_nan  = (&ea) && (fra != 0);
  assign b_nan  = (&eb) && (frb != 0);
  assign a_snan = a_nan && !fra[MAN_W-1];
  assign b_snan = b_nan && !frb[MAN_W-1];
  assign a_zero = (ea == 0) && (fra == 0);
  assign b_zero = (eb == 0) && (frb == 0);

  assign mag_a = a[W-2:0];
  assign mag_b = b[W-2:0];
  assign both_zero = a_zero && b_zero;

  always_comb begin
    if (both_zero)          a_lt_b = 1'b0;
    else if (sa != sb)      a_lt_b = sa;
    else if (sa)            a_lt_b = (mag_a > mag_b);
    else                    a_lt_b = (mag_a < mag_b);
  end

  logic want_max, is_number_form, is_minmax;
  assign want_max       = (op == OP_MAX) || (op == OP_MAXNUM);
  assign is_number_form = (op == OP_MINNUM) || (op == OP_MAXNUM);
  assign is_minmax      = (op == OP_MIN) || (op == OP_MAX) ||
                          (op == OP_MINNUM) || (op == OP_MAXNUM);

  logic eq, unord, is_cmp;
  assign eq     = both_zero || (a == b);
  assign unord  = a_nan || b_nan;
  assign is_cmp = (op == OP_CMPLT) || (op == OP_CMPLE) || (op == OP_CMPEQ);

  logic is_int;
  logic [SHB-1:0] shamt;
  assign shamt  = b[SHB-1:0];
  assign is_int = (op == OP_IAND) || (op == OP_IOR) || (op == OP_IXOR) ||
                  (op == OP_IADD) || (op == OP_ISUB) || (op == OP_ISHL) ||
                  (op == OP_ISHR) || (op == OP_ICMPLT);

  logic is_reserved;
  assign is_reserved = (op == 8'd15) || (op > 8'd23);

  assign valid = (op == OP_ABS) || (op == OP_NEG) ||
                 (op == OP_COPYSIGN) || is_minmax ||
                 (op == OP_SELECT) || is_cmp || is_int || is_reserved;

  generate
    if (W != (1 << SHB)) begin : g_bad_width
      $error("cft_simpleops_ref: format width must be a power of two");
    end
  endgenerate

  always_comb begin
    d     = a;
    flags = 5'b0;
    case (op)
      OP_ABS:      d = {1'b0,  a[W-2:0]};
      OP_NEG:      d = {~sa,   a[W-2:0]};
      OP_COPYSIGN: d = {sb,    a[W-2:0]};
      OP_SELECT:   d = (c[W-2:0] != 0) ? a : b;
      OP_IAND:     d = a & b;
      OP_IOR:      d = a | b;
      OP_IXOR:     d = a ^ b;
      OP_IADD:     d = a + b;
      OP_ISUB:     d = a - b;
      OP_ISHL:     d = a << shamt;
      OP_ISHR:     d = a >> shamt;
      OP_ICMPLT:   d = (a < b) ? one : pzero;
      default: begin
        if (is_minmax) begin
          flags[FL_INVALID] = a_snan || b_snan;
          if (a_nan || b_nan) begin
            if (!is_number_form || (a_nan && b_nan)) d = qnan;
            else                                     d = a_nan ? b : a;
          end else if (both_zero) begin
            if (sa == sb)      d = a;
            else if (want_max) d = sa ? b : a;
            else               d = sa ? a : b;
          end else begin
            if (want_max) d = a_lt_b ? b : a;
            else          d = a_lt_b ? a : b;
          end
        end else if (is_cmp) begin
          flags[FL_INVALID] = a_snan || b_snan;
          if (unord) d = pzero;
          else begin
            case (op)
              OP_CMPLT: d = a_lt_b        ? one : pzero;
              OP_CMPLE: d = (a_lt_b || eq) ? one : pzero;
              default:  d = eq            ? one : pzero;
            endcase
          end
        end else if (is_reserved) begin
          d = qnan;
          flags[FL_INVALID] = 1'b1;
        end
      end
    endcase
  end

endmodule
