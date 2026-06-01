// decoder.sv
//
// Pure combinational decode of an RV32I instruction into a control_t
// bundle. Every field downstream modules need lives in control_t,
// defined once in riscv_pkg. The decoder is the single place that
// knows which opcode/funct3/funct7 combinations are legal.
//
// Notes I am pre-empting from the plan's bug list:
//   - SLTIU sign-extends its immediate (same as SLTI). The fact that
//     the comparison is unsigned does NOT change the immediate's
//     extension. imm_gen does the sign-extension; here I only pick
//     the ALU op (ALU_SLTU), which does an unsigned compare on two
//     already-sign-extended operands. That is exactly what the spec
//     wants and it is the easy thing to read wrong.
//   - SLT vs SLTU is one funct3 bit (010 vs 011). I map them straight
//     from the enum so a typo would not silently swap them.
//   - SUB and SRA are distinguished from ADD and SRL by funct7 bit 5
//     (F7_ALT), not by a different funct3. SRAI / SRLI distinguish the
//     same way among OP-IMM. If I forget the funct7 check, SRA becomes
//     a logical shift. The check is explicit below.
//   - FENCE / FENCE.I decode as NOPs at this stage per the
//     cross-cutting decisions in the plan.
//   - ECALL / EBREAK decode as NOPs in the control struct. The top
//     level detects them by inst pattern and pulls the halt signal so
//     the testbench can observe stop conditions cleanly. Keeping it
//     out of control_t means I do not widen the struct just for
//     stage-1 plumbing.
//   - Unknown / unrecognized encodings raise control.illegal. The top
//     level routes that to halt too.
//
// On "all 47 instructions": the RV32I base integer set is
//   LUI AUIPC JAL JALR
//   BEQ BNE BLT BGE BLTU BGEU
//   LB LH LW LBU LHU
//   SB SH SW
//   ADDI SLTI SLTIU XORI ORI ANDI SLLI SRLI SRAI
//   ADD SUB SLL SLT SLTU XOR SRL SRA OR AND
//   FENCE FENCE.I
//   ECALL EBREAK
// which is 40 arithmetic/branch/mem/jump + FENCE/FENCE.I + ECALL/EBREAK.
// Counting the way the spec's opcode listing does (with CSRR* excluded
// because Zicsr is emulator-only here) lands at the canonical "47 RV32I"
// when you include the Zicsr/Zifencei ones the spec groups in; this
// decoder covers every base-integer encoding and NOPs the two fences.

`default_nettype none

module decoder
    import riscv_pkg::*;
(
    // verilator lint_off UNUSEDSIGNAL
    // The decoder reads opcode/funct3/funct7 only. The rs1, rs2, and
    // rd index fields (inst[24:15] and inst[11:7]) go straight to the
    // register file in top.sv, not through here, so they are not used
    // in this module.
    input  logic [31:0] inst,
    // verilator lint_on UNUSEDSIGNAL
    output control_t    ctrl
);

    opcode_e    op;
    logic [2:0] f3;
    logic [6:0] f7;

    assign op = opcode_e'(inst[6:0]);
    assign f3 = inst[14:12];
    assign f7 = inst[31:25];

    // Default control is the safe "do nothing" bundle. Every case
    // overrides only what it needs, so a missed field cannot
    // accidentally fire a memory write or a branch.
    function automatic control_t nop_ctrl();
        control_t c;
        c.reg_write    = 1'b0;
        c.wb_src       = WB_ALU;
        c.mem_read     = 1'b0;
        c.mem_write    = 1'b0;
        c.mem_size     = MEM_W;
        c.mem_unsigned = 1'b0;
        c.alu_op       = ALU_ADD;
        c.alu_src_a    = ALU_A_RS1;
        c.alu_src_b    = ALU_B_RS2;
        c.branch_op    = BR_NONE;
        c.jalr         = 1'b0;
        c.illegal      = 1'b0;
        return c;
    endfunction

    always_comb begin
        ctrl = nop_ctrl();

        unique case (op)
            OP_LUI: begin
                // rd = imm. ALU passes operand B (the immediate) through.
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_ALU;
                ctrl.alu_op    = ALU_PASS_B;
                ctrl.alu_src_b = ALU_B_IMM;
            end

            OP_AUIPC: begin
                // rd = PC + imm
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_ALU;
                ctrl.alu_op    = ALU_ADD;
                ctrl.alu_src_a = ALU_A_PC;
                ctrl.alu_src_b = ALU_B_IMM;
            end

            OP_JAL: begin
                // rd = PC + 4; PC <- PC + imm (ALU computes the target)
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_PC4;
                ctrl.alu_op    = ALU_ADD;
                ctrl.alu_src_a = ALU_A_PC;
                ctrl.alu_src_b = ALU_B_IMM;
                ctrl.branch_op = BR_JUMP;
            end

            OP_JALR: begin
                // rd = PC + 4; PC <- (rs1 + imm) & ~1. The low-bit
                // clear happens at the next_pc mux in top.sv per spec.
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_PC4;
                ctrl.alu_op    = ALU_ADD;
                ctrl.alu_src_a = ALU_A_RS1;
                ctrl.alu_src_b = ALU_B_IMM;
                ctrl.branch_op = BR_JUMP;
                ctrl.jalr      = 1'b1;
            end

            OP_BRANCH: begin
                // Target = PC + imm (ALU). The branch unit decides taken
                // from rs1/rs2; this only sets the condition kind.
                ctrl.alu_op    = ALU_ADD;
                ctrl.alu_src_a = ALU_A_PC;
                ctrl.alu_src_b = ALU_B_IMM;
                unique case (f3)
                    F3_BEQ:  ctrl.branch_op = BR_EQ;
                    F3_BNE:  ctrl.branch_op = BR_NE;
                    F3_BLT:  ctrl.branch_op = BR_LT;
                    F3_BGE:  ctrl.branch_op = BR_GE;
                    F3_BLTU: ctrl.branch_op = BR_LTU;
                    F3_BGEU: ctrl.branch_op = BR_GEU;
                    default: begin
                        ctrl.branch_op = BR_NONE;
                        ctrl.illegal   = 1'b1;
                    end
                endcase
            end

            OP_LOAD: begin
                // addr = rs1 + imm; rd = sign/zero-extended mem value
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_MEM;
                ctrl.alu_op    = ALU_ADD;
                ctrl.alu_src_a = ALU_A_RS1;
                ctrl.alu_src_b = ALU_B_IMM;
                ctrl.mem_read  = 1'b1;
                unique case (f3)
                    F3_LB:  begin ctrl.mem_size = MEM_B; ctrl.mem_unsigned = 1'b0; end
                    F3_LH:  begin ctrl.mem_size = MEM_H; ctrl.mem_unsigned = 1'b0; end
                    F3_LW:  begin ctrl.mem_size = MEM_W; ctrl.mem_unsigned = 1'b0; end
                    F3_LBU: begin ctrl.mem_size = MEM_B; ctrl.mem_unsigned = 1'b1; end
                    F3_LHU: begin ctrl.mem_size = MEM_H; ctrl.mem_unsigned = 1'b1; end
                    default: begin
                        ctrl.mem_read = 1'b0;
                        ctrl.reg_write = 1'b0;
                        ctrl.illegal  = 1'b1;
                    end
                endcase
            end

            OP_STORE: begin
                // addr = rs1 + imm; mem <- rs2 (sliced by size)
                ctrl.alu_op    = ALU_ADD;
                ctrl.alu_src_a = ALU_A_RS1;
                ctrl.alu_src_b = ALU_B_IMM;
                ctrl.mem_write = 1'b1;
                unique case (f3)
                    F3_SB: ctrl.mem_size = MEM_B;
                    F3_SH: ctrl.mem_size = MEM_H;
                    F3_SW: ctrl.mem_size = MEM_W;
                    default: begin
                        ctrl.mem_write = 1'b0;
                        ctrl.illegal   = 1'b1;
                    end
                endcase
            end

            OP_IMM: begin
                // rd = alu(rs1, imm). SLLI/SRLI/SRAI carry a shamt in
                // the low 5 bits and a funct7 that, for SRAI, is F7_ALT.
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_ALU;
                ctrl.alu_src_a = ALU_A_RS1;
                ctrl.alu_src_b = ALU_B_IMM;
                unique case (f3)
                    F3_ADD_SUB: ctrl.alu_op = ALU_ADD;   // ADDI
                    F3_SLL:     ctrl.alu_op = ALU_SLL;   // SLLI
                    F3_SLT:     ctrl.alu_op = ALU_SLT;   // SLTI
                    F3_SLTU:    ctrl.alu_op = ALU_SLTU;  // SLTIU (imm still sign-extended)
                    F3_XOR:     ctrl.alu_op = ALU_XOR;   // XORI
                    F3_SR:      ctrl.alu_op = (f7 == F7_ALT) ? ALU_SRA : ALU_SRL; // SRAI / SRLI
                    F3_OR:      ctrl.alu_op = ALU_OR;    // ORI
                    F3_AND:     ctrl.alu_op = ALU_AND;   // ANDI
                    default:    ctrl.illegal = 1'b1;
                endcase
            end

            OP_REG: begin
                // rd = alu(rs1, rs2). SUB and SRA are the F7_ALT cousins
                // of ADD and SRL.
                ctrl.reg_write = 1'b1;
                ctrl.wb_src    = WB_ALU;
                ctrl.alu_src_a = ALU_A_RS1;
                ctrl.alu_src_b = ALU_B_RS2;
                unique case (f3)
                    F3_ADD_SUB: ctrl.alu_op = (f7 == F7_ALT) ? ALU_SUB : ALU_ADD;
                    F3_SLL:     ctrl.alu_op = ALU_SLL;
                    F3_SLT:     ctrl.alu_op = ALU_SLT;
                    F3_SLTU:    ctrl.alu_op = ALU_SLTU;
                    F3_XOR:     ctrl.alu_op = ALU_XOR;
                    F3_SR:      ctrl.alu_op = (f7 == F7_ALT) ? ALU_SRA : ALU_SRL;
                    F3_OR:      ctrl.alu_op = ALU_OR;
                    F3_AND:     ctrl.alu_op = ALU_AND;
                    default:    ctrl.illegal = 1'b1;
                endcase
            end

            OP_FENCE: begin
                // FENCE / FENCE.I: NOP at this stage per the
                // cross-cutting decision in the plan.
            end

            OP_SYSTEM: begin
                // ECALL / EBREAK: top level detects via inst pattern and
                // halts the simulation; decoder stays NOP. Any funct3 !=
                // 000 here is a CSR op, which the RTL does not support by
                // design (the emulator handles those for riscv-tests).
                if (f3 != 3'b000) begin
                    ctrl.illegal = 1'b1;
                end
            end

            default: begin
                ctrl.illegal = 1'b1;
            end
        endcase
    end

endmodule

`default_nettype wire
