// hazard_unit.sv
//
// Load-use hazard detection. Forwarding covers every data hazard
// except one: a load result is not ready until the load reaches the
// MEM/WB boundary, so an instruction that needs it in the very next
// cycle (the load is in EX, the consumer is in ID) cannot be handed
// the value by an EX-EX forward. The fix is a one-cycle stall: hold
// the consumer in ID for a cycle, which lets the load advance to WB;
// next cycle the consumer is in EX and the MEM-EX forward delivers the
// loaded data.
//
// Detection: the instruction in EX is a load (mem_read) writing a
// non-x0 register, and that register is one the ID instruction really
// reads.
//
// The "really reads" part matters. Naively matching the ID rs1/rs2
// index fields against the load's rd over-stalls, because for I-type,
// U-type and jump instructions those bit positions are not register
// operands at all (they are immediate bits). Stalling on an accidental
// match there is the plan's predicted "hazard unit too aggressive"
// failure: still correct, but it inflates the cycle count for nothing.
// So I derive reads_rs1 / reads_rs2 from the opcode and only stall on a
// genuine read.

`default_nettype none

module hazard_unit
    import riscv_pkg::*;
(
    // the instruction currently in EX (ID/EX register)
    input  logic       ex_mem_read,
    input  logic [4:0] ex_rd_idx,
    // the instruction currently in ID (IF/ID register)
    input  opcode_e    id_opcode,
    input  logic [4:0] id_rs1_idx,
    input  logic [4:0] id_rs2_idx,
    output logic       stall
);

    // Which source registers each opcode actually reads.
    logic reads_rs1, reads_rs2;
    always_comb begin
        unique case (id_opcode)
            OP_REG:    begin reads_rs1 = 1'b1; reads_rs2 = 1'b1; end // R-type
            OP_STORE:  begin reads_rs1 = 1'b1; reads_rs2 = 1'b1; end // addr + data
            OP_BRANCH: begin reads_rs1 = 1'b1; reads_rs2 = 1'b1; end // both compared
            OP_IMM:    begin reads_rs1 = 1'b1; reads_rs2 = 1'b0; end // I-type ALU
            OP_LOAD:   begin reads_rs1 = 1'b1; reads_rs2 = 1'b0; end // base addr
            OP_JALR:   begin reads_rs1 = 1'b1; reads_rs2 = 1'b0; end // target base
            // LUI, AUIPC, JAL, FENCE, SYSTEM read no GPR source
            default:   begin reads_rs1 = 1'b0; reads_rs2 = 1'b0; end
        endcase
    end

    logic hit_rs1, hit_rs2;
    assign hit_rs1 = reads_rs1 && (ex_rd_idx == id_rs1_idx);
    assign hit_rs2 = reads_rs2 && (ex_rd_idx == id_rs2_idx);

    assign stall = ex_mem_read && (ex_rd_idx != 5'd0) && (hit_rs1 || hit_rs2);

endmodule

`default_nettype wire
