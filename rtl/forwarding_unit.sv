// forwarding_unit.sv
//
// Data-hazard forwarding for the EX stage. An instruction in EX may
// need a register value that a still-in-flight older instruction has
// computed but not yet written back. Rather than stall, we route that
// value straight to the EX operand from wherever it currently lives.
//
// Two forwarding sources, one per later stage:
//   - EX/MEM (the instruction now in MEM): forward its result. This is
//     the most recent producer, so it wins.
//   - MEM/WB (the instruction now in WB): forward its writeback value.
//
// Per operand the unit emits a 2-bit select:
//   FWD_NONE  (00): use the value read from the register file
//   FWD_EXMEM (01): take the EX/MEM stage's result
//   FWD_MEMWB (10): take the MEM/WB stage's writeback value
//
// Predicted-failure notes from the plan, handled here:
//   - "Forwarding when rs = x0 must NOT forward." The rd != 0 guard
//     covers it: a write to x0 is dropped, and if rs is x0 then a
//     match would require rd == 0, which the guard already excludes.
//   - "EX-EX vs MEM-EX priority, younger wins." EX/MEM is checked
//     first, so a value produced by the MEM-stage instruction beats an
//     older one sitting in WB.
//
// What is NOT solved here: forwarding a LOAD result out of EX/MEM. The
// loaded data is not ready until the end of MEM, so an EX-EX forward
// of a load would hand over the address, not the data. That case is
// the load-use hazard, resolved by a one-cycle stall in the hazard
// unit (stage 2.3). This unit only picks the source; the datapath
// decides what value each source carries (and forwards the load's data
// correctly once it reaches MEM/WB).

`default_nettype none

module forwarding_unit (
    input  logic [4:0] ex_rs1_idx,
    input  logic [4:0] ex_rs2_idx,
    // the instruction currently in MEM (EX/MEM register)
    input  logic       ex_mem_reg_write,
    input  logic [4:0] ex_mem_rd,
    // the instruction currently in WB (MEM/WB register)
    input  logic       mem_wb_reg_write,
    input  logic [4:0] mem_wb_rd,
    output logic [1:0] forward_a,
    output logic [1:0] forward_b
);

    localparam logic [1:0] FWD_NONE  = 2'b00;
    localparam logic [1:0] FWD_EXMEM = 2'b01;
    localparam logic [1:0] FWD_MEMWB = 2'b10;

    function automatic logic [1:0] pick(input logic [4:0] rs);
        // EX/MEM first: it is the younger (more recent) producer.
        if (ex_mem_reg_write && (ex_mem_rd != 5'd0) && (ex_mem_rd == rs)) begin
            return FWD_EXMEM;
        end else if (mem_wb_reg_write && (mem_wb_rd != 5'd0) && (mem_wb_rd == rs)) begin
            return FWD_MEMWB;
        end else begin
            return FWD_NONE;
        end
    endfunction

    assign forward_a = pick(ex_rs1_idx);
    assign forward_b = pick(ex_rs2_idx);

endmodule

`default_nettype wire
