// ex_mem_reg.sv
//
// The EX/MEM pipeline register: it carries the execute-stage result
// into the memory stage. That is the ALU result (which is either the
// value to write back or the address for a load/store), the store data
// (rs2), the destination register index, and PC+4 for the link case.
// The control bundle rides along so the memory stage knows the access
// size and the writeback stage knows the writeback source.
//
// Branches are already resolved in EX, so nothing branch-related needs
// to travel past this point. flush is here for uniformity (forces a
// NOP bubble) but in the stage-1 pipeline it stays tied low: a taken
// branch only squashes the two youngest instructions (in IF/ID and
// ID/EX), and an instruction that has reached EX/MEM is older than the
// branch and must complete.

`default_nettype none

module ex_mem_reg
    import riscv_pkg::*;
(
    input  logic        clk,
    input  logic        rst,
    input  logic        en,
    input  logic        flush,

    input  control_t    ctrl_in,
    input  logic [31:0] alu_y_in,
    input  logic [31:0] rs2_val_in,   // store data
    input  logic [4:0]  rd_idx_in,
    input  logic [31:0] pc4_in,

    output control_t    ctrl,
    output logic [31:0] alu_y,
    output logic [31:0] rs2_val,
    output logic [4:0]  rd_idx,
    output logic [31:0] pc4
);

    function automatic control_t bubble();
        control_t c;
        c = '0;
        return c;
    endfunction

    always_ff @(posedge clk) begin
        if (rst || flush) begin
            ctrl    <= bubble();
            alu_y   <= 32'h0;
            rs2_val <= 32'h0;
            rd_idx  <= 5'h0;
            pc4     <= 32'h0;
        end else if (en) begin
            ctrl    <= ctrl_in;
            alu_y   <= alu_y_in;
            rs2_val <= rs2_val_in;
            rd_idx  <= rd_idx_in;
            pc4     <= pc4_in;
        end
    end

endmodule

`default_nettype wire
