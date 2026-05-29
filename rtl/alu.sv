// alu.sv
//
// 32-bit ALU. Combinational, single-cycle. Implements every operation
// the RV32I integer instructions need. PASS_B is a synthetic op used
// for LUI, where the immediate IS the result (cheaper than threading
// a constant zero into operand A and adding).
//
// Shifts use only the low 5 bits of operand B (Spec 2.4: "the shift
// amount is encoded in the lower 5 bits of the I-immediate field, or
// for register-register shifts the lower 5 bits of rs2"). The upper
// 27 bits are ignored even if nonzero, which is what the spec says
// and what software relies on.
//
// SRA: I cast operand A with $signed before the arithmetic shift.
// Without the cast the shift would zero-fill, which is the bug I am
// pre-empting per the plan.

`default_nettype none

module alu
    import riscv_pkg::*;
(
    input  logic [31:0]  a,
    input  logic [31:0]  b,
    input  alu_op_e      op,
    output logic [31:0]  y
);

    logic [4:0] shamt;
    assign shamt = b[4:0];

    always_comb begin
        unique case (op)
            ALU_ADD:    y = a + b;
            ALU_SUB:    y = a - b;
            ALU_AND:    y = a & b;
            ALU_OR:     y = a | b;
            ALU_XOR:    y = a ^ b;
            ALU_SLL:    y = a << shamt;
            ALU_SRL:    y = a >> shamt;
            ALU_SRA:    y = $unsigned($signed(a) >>> shamt);
            ALU_SLT:    y = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
            ALU_SLTU:   y = (a < b)                   ? 32'd1 : 32'd0;
            ALU_PASS_B: y = b;
            default:    y = 32'h0;
        endcase
    end

endmodule

`default_nettype wire
