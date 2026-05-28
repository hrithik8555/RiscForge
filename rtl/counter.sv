// counter.sv
//
// Trivial 4-bit synchronous counter. This module is not part of the actual
// processor. It exists only as a "hello flip-flop" so I can verify the toolchain
// works end to end (Verilator compiles it, cocotb drives it, GTKWave opens the
// VCD) before I write any real RTL. I will delete this once a real module has
// a test passing on the same toolchain.
//
// The reset is synchronous and active-high, which is the convention I will use
// for the whole project. Documenting it here so I do not forget on day two.

`default_nettype none

module counter #(
    parameter int WIDTH = 4
) (
    input  logic              clk,
    input  logic              rst,    // synchronous, active-high
    input  logic              en,     // count enable
    output logic [WIDTH-1:0]  count
);

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= '0;
        end else if (en) begin
            count <= count + 1'b1;
        end
    end

endmodule

`default_nettype wire
