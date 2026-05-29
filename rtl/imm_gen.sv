// imm_gen.sv
//
// Pull the immediate out of an instruction, sign-extending as the
// format requires. Five formats: I, S, B, U, J. The format is picked
// from the opcode here so the decoder does not need a separate
// imm_src signal; one less wire to keep in sync.
//
// The B-type and J-type bit scrambles are the standard 'gotcha' of
// RV32I. I hand-traced the spec table for both directions in the
// Python assembler tests; the same bit positions appear here. If
// anything goes wrong with branch or jump targets, this file and
// the matching paths in tools/assembler/assemble.py are the first
// suspects, in that order.
//
// LUI / AUIPC get the U-format immediate, which is the low 20 bits
// of the instruction shifted left 12, sign-extended (the sign just
// preserves whatever bit 31 was, since LUI's "imm" is the top half
// of a 32-bit constant).

`default_nettype none

module imm_gen
    import riscv_pkg::*;
(
    input  logic [31:0] inst,
    output logic [31:0] imm
);

    opcode_e op;
    assign op = opcode_e'(inst[6:0]);

    // I-type: inst[31:20] sign-extended
    logic [31:0] imm_i;
    assign imm_i = {{20{inst[31]}}, inst[31:20]};

    // S-type: {inst[31:25], inst[11:7]}, sign-extended
    logic [31:0] imm_s;
    assign imm_s = {{20{inst[31]}}, inst[31:25], inst[11:7]};

    // B-type: 13-bit, bit 0 is 0
    //   imm[12]    = inst[31]
    //   imm[11]    = inst[7]
    //   imm[10:5]  = inst[30:25]
    //   imm[4:1]   = inst[11:8]
    //   imm[0]     = 0
    logic [31:0] imm_b;
    assign imm_b = {
        {19{inst[31]}},
        inst[31],
        inst[7],
        inst[30:25],
        inst[11:8],
        1'b0
    };

    // U-type: inst[31:12] shifted into the top 20 bits
    logic [31:0] imm_u;
    assign imm_u = {inst[31:12], 12'h0};

    // J-type: 21-bit, bit 0 is 0
    //   imm[20]    = inst[31]
    //   imm[19:12] = inst[19:12]
    //   imm[11]    = inst[20]
    //   imm[10:1]  = inst[30:21]
    //   imm[0]     = 0
    logic [31:0] imm_j;
    assign imm_j = {
        {11{inst[31]}},
        inst[31],
        inst[19:12],
        inst[20],
        inst[30:21],
        1'b0
    };

    always_comb begin
        unique case (op)
            OP_LOAD, OP_IMM, OP_JALR, OP_SYSTEM, OP_FENCE: imm = imm_i;
            OP_STORE:                                      imm = imm_s;
            OP_BRANCH:                                     imm = imm_b;
            OP_LUI, OP_AUIPC:                              imm = imm_u;
            OP_JAL:                                        imm = imm_j;
            OP_REG:                                        imm = 32'h0;
            default:                                       imm = 32'h0;
        endcase
    end

endmodule

`default_nettype wire
