// branch_unit.sv
//
// Decide whether a control-transfer instruction is taken. Pure
// combinational: given the branch kind and the two source operands,
// output `taken`.
//
// For the six conditional branches it does the comparison. For
// BR_JUMP (JAL and JALR) it is unconditionally taken. For BR_NONE
// (everything else) it is not taken.
//
// Signedness matters and is the named bug class from the plan: BLT /
// BGE compare as signed, BLTU / BGEU as unsigned. I cast with $signed
// for the signed forms and compare raw for the unsigned forms.
//
// Placement note: in stage 1 single-cycle this sits logically in the
// EX stage next to the ALU. Stage 2 moves branch resolution to ID so
// the misprediction penalty is one cycle; this module's logic does
// not change when it moves, only where top.sv instantiates it.

`default_nettype none

module branch_unit
    import riscv_pkg::*;
(
    input  branch_op_e   branch_op,
    input  logic [31:0]  rs1,
    input  logic [31:0]  rs2,
    output logic         taken
);

    always_comb begin
        unique case (branch_op)
            BR_NONE: taken = 1'b0;
            BR_EQ:   taken = (rs1 == rs2);
            BR_NE:   taken = (rs1 != rs2);
            BR_LT:   taken = ($signed(rs1) <  $signed(rs2));
            BR_GE:   taken = ($signed(rs1) >= $signed(rs2));
            BR_LTU:  taken = (rs1 <  rs2);
            BR_GEU:  taken = (rs1 >= rs2);
            BR_JUMP: taken = 1'b1;  // JAL / JALR always transfer control
            default: taken = 1'b0;
        endcase
    end

endmodule

`default_nettype wire
