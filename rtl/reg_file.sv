// reg_file.sv
//
// 32-entry, 32-bit-wide architectural register file. Two read ports,
// one write port. x0 is hardwired to zero: writes to it are silently
// dropped and reads of it return zero regardless of internal state.
//
// Write-first bypass: when we is asserted and rs_addr matches ws_addr
// in the same cycle, the read port returns wd, not the stale stored
// value. In the single-cycle stage this never fires because the same
// instruction does both the read and the write at the same edge, but
// I am defining the behavior now because stage 2's pipeline reads in
// ID and writes in WB on the same cycle, and the textbook way to
// handle that is a write-first reg file.
//
// Reset clears every entry to zero. Strictly speaking the
// architecture only requires x0 to read as zero; clearing the rest
// keeps simulation traces deterministic and makes "writes never
// happened" obvious in waveforms.

`default_nettype none

module reg_file (
    input  logic        clk,
    input  logic        rst,
    // write port
    input  logic        we,
    input  logic [4:0]  ws,
    input  logic [31:0] wd,
    // read ports
    input  logic [4:0]  rs1,
    input  logic [4:0]  rs2,
    output logic [31:0] rd1,
    output logic [31:0] rd2
);

    logic [31:0] xregs [1:31];

    // write port: only writes to non-x0 take effect.
    integer i;
    always_ff @(posedge clk) begin
        if (rst) begin
            for (i = 1; i < 32; i = i + 1) begin
                xregs[i] <= 32'h0;
            end
        end else if (we && (ws != 5'd0)) begin
            xregs[ws] <= wd;
        end
    end

    // read ports: combinational, x0 hardwired to zero, write-first
    // bypass when reading the register being written this cycle.
    always_comb begin
        if (rs1 == 5'd0) begin
            rd1 = 32'h0;
        end else if (we && (ws == rs1)) begin
            rd1 = wd;
        end else begin
            rd1 = xregs[rs1];
        end

        if (rs2 == 5'd0) begin
            rd2 = 32'h0;
        end else if (we && (ws == rs2)) begin
            rd2 = wd;
        end else begin
            rd2 = xregs[rs2];
        end
    end

endmodule

`default_nettype wire
