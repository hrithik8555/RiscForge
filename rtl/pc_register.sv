// pc_register.sv
//
// Program counter register. Synchronous reset to PC_RESET, optional
// stall via en=0. Next-PC comes from the fetch-side mux outside this
// module so the same register works whether next_pc is pc+4, a branch
// target, a jump target, or a flushed predicted target later in the
// project.
//
// I am leaving en in even for stage 1 single-cycle, where it is tied
// high. The pipeline in stage 2 needs it for load-use stalls and the
// cache in stage 4 needs it for miss stalls; wiring it now means
// later stages only change the producer of en, not the PC module.

`default_nettype none

module pc_register #(
    parameter logic [31:0] PC_RESET = 32'h0000_0000
) (
    input  logic        clk,
    input  logic        rst,        // synchronous, active-high
    input  logic        en,         // 1 = advance, 0 = hold (stall)
    input  logic [31:0] next_pc,
    output logic [31:0] pc
);

    always_ff @(posedge clk) begin
        if (rst) begin
            pc <= PC_RESET;
        end else if (en) begin
            pc <= next_pc;
        end
    end

endmodule

`default_nettype wire
