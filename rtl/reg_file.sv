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

module reg_file #(
    // Write-first bypass: when set, a read port reading the register
    // being written this cycle returns the write data instead of the
    // stored value. This is the right behavior for the PIPELINE, where
    // the ID-stage read and the WB-stage write are different
    // instructions in the same cycle and wd comes from a pipeline
    // flop (no combinational loop).
    //
    // In the SINGLE-CYCLE datapath the read and write are the SAME
    // instruction, and the architecture requires the read to see the
    // OLD value (e.g. `addi a0, a0, 1` reads old a0). Enabling the
    // bypass there is both architecturally wrong and a combinational
    // loop (wd -> rd -> alu -> wd). So single-cycle top.sv sets
    // WRITE_FIRST = 0; stage 2's pipeline sets it back to 1.
    parameter bit WRITE_FIRST = 1'b1
) (
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
        end else if (WRITE_FIRST && we && (ws == rs1)) begin
            rd1 = wd;
        end else begin
            rd1 = xregs[rs1];
        end

        if (rs2 == 5'd0) begin
            rd2 = 32'h0;
        end else if (WRITE_FIRST && we && (ws == rs2)) begin
            rd2 = wd;
        end else begin
            rd2 = xregs[rs2];
        end
    end

endmodule

`default_nettype wire
