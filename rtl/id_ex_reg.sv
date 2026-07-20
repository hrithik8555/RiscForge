// id_ex_reg.sv
//
// The ID/EX pipeline register: it carries the decoded control bundle
// and the operands the execute stage needs (the two register values,
// the immediate, the PC and PC+4 for target and link math, and the
// source/destination register indices, which the forwarding unit in a
// later step will need).
//
// flush forces the control bundle to all-zero, which is a NOP: an
// all-zero control_t has reg_write=0, mem_read=0, mem_write=0, and
// branch_op=BR_NONE, so the squashed instruction commits nothing. This
// is the bubble inserted on a taken branch (to kill the wrong-path
// instruction that was in decode) and, later, on a load-use stall.
// flush wins over en for the same reason as in if_id_reg.
//
// I carry the full control_t through every pipeline register on
// purpose (the cross-cutting decision): adding a new control signal is
// then a one-line change to the package, and the compiler catches any
// stage that forgot to thread it.

`default_nettype none

module id_ex_reg
    import riscv_pkg::*;
(
    input  logic        clk,
    input  logic        rst,
    input  logic        en,        // 1 = advance, 0 = hold
    input  logic        flush,     // 1 = inject a NOP bubble

    input  control_t    ctrl_in,
    input  logic [31:0] pc_in,
    input  logic [31:0] pc4_in,
    input  logic [31:0] rs1_val_in,
    input  logic [31:0] rs2_val_in,
    input  logic [31:0] imm_in,
    input  logic [4:0]  rs1_idx_in,
    input  logic [4:0]  rs2_idx_in,
    input  logic [4:0]  rd_idx_in,

    output control_t    ctrl,
    output logic [31:0] pc,
    output logic [31:0] pc4,
    output logic [31:0] rs1_val,
    output logic [31:0] rs2_val,
    output logic [31:0] imm,
    output logic [4:0]  rs1_idx,
    output logic [4:0]  rs2_idx,
    output logic [4:0]  rd_idx
);

    function automatic control_t bubble();
        control_t c;
        c = '0;   // reg_write=0, mem_read/write=0, branch_op=BR_NONE
        return c;
    endfunction

    always_ff @(posedge clk) begin
        if (rst || flush) begin
            ctrl    <= bubble();
            pc      <= 32'h0;
            pc4     <= 32'h0;
            rs1_val <= 32'h0;
            rs2_val <= 32'h0;
            imm     <= 32'h0;
            rs1_idx <= 5'h0;
            rs2_idx <= 5'h0;
            rd_idx  <= 5'h0;
        end else if (en) begin
            ctrl    <= ctrl_in;
            pc      <= pc_in;
            pc4     <= pc4_in;
            rs1_val <= rs1_val_in;
            rs2_val <= rs2_val_in;
            imm     <= imm_in;
            rs1_idx <= rs1_idx_in;
            rs2_idx <= rs2_idx_in;
            rd_idx  <= rd_idx_in;
        end
        // else: hold (stall)
    end

endmodule

`default_nettype wire
