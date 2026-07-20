// mem_wb_reg.sv
//
// The MEM/WB pipeline register: the last one. It carries everything the
// writeback stage needs to pick the value for rd and write it: the ALU
// result, the data read from memory (for loads), PC+4 (for JAL/JALR
// link), the destination index, and the control bundle (for reg_write
// and wb_src).
//
// flush is here for uniformity but stays tied low in the stage-1
// pipeline; an instruction this far down the pipe is committed.

`default_nettype none

module mem_wb_reg
    import riscv_pkg::*;
(
    input  logic        clk,
    input  logic        rst,
    input  logic        en,
    input  logic        flush,

    input  control_t    ctrl_in,
    input  logic [31:0] alu_y_in,
    input  logic [31:0] mem_rdata_in,
    input  logic [4:0]  rd_idx_in,
    input  logic [31:0] pc4_in,

    output control_t    ctrl,
    output logic [31:0] alu_y,
    output logic [31:0] mem_rdata,
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
            ctrl      <= bubble();
            alu_y     <= 32'h0;
            mem_rdata <= 32'h0;
            rd_idx    <= 5'h0;
            pc4       <= 32'h0;
        end else if (en) begin
            ctrl      <= ctrl_in;
            alu_y     <= alu_y_in;
            mem_rdata <= mem_rdata_in;
            rd_idx    <= rd_idx_in;
            pc4       <= pc4_in;
        end
    end

endmodule

`default_nettype wire
