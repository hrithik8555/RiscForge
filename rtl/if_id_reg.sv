// if_id_reg.sv
//
// The IF/ID pipeline register: it carries the fetched instruction and
// its PC from the fetch stage into the decode stage, latching once per
// clock.
//
// Two controls beyond the clock:
//   - en=0 holds the current contents (a stall, used for load-use in a
//     later step; tied high for now).
//   - flush=1 replaces the instruction with a NOP bubble on the next
//     edge, which is how a taken branch squashes the wrongly-fetched
//     successor. Flush wins over en: a branch redirect must not be held
//     back by a stall.
//
// The bubble is a real NOP encoding (addi x0, x0, 0) so the decoder
// downstream produces a do-nothing control with no special-casing.

`default_nettype none

module if_id_reg (
    input  logic        clk,
    input  logic        rst,
    input  logic        en,      // 1 = advance, 0 = hold
    input  logic        flush,   // 1 = inject a NOP bubble
    input  logic [31:0] pc_in,
    input  logic [31:0] pc4_in,
    input  logic [31:0] inst_in,
    output logic [31:0] pc,
    output logic [31:0] pc4,
    output logic [31:0] inst
);

    // addi x0, x0, 0
    localparam logic [31:0] NOP_INST = 32'h0000_0013;

    always_ff @(posedge clk) begin
        if (rst) begin
            pc   <= 32'h0;
            pc4  <= 32'h0;
            inst <= NOP_INST;
        end else if (flush) begin
            pc   <= 32'h0;
            pc4  <= 32'h0;
            inst <= NOP_INST;
        end else if (en) begin
            pc   <= pc_in;
            pc4  <= pc4_in;
            inst <= inst_in;
        end
        // else: hold (stall)
    end

endmodule

`default_nettype wire
