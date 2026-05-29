// instr_memory.sv
//
// Instruction memory for stage 1 single-cycle. Word-addressable
// combinational ROM, parameterized in 32-bit words. Loaded at sim
// start via $readmemh from a path passed in with a plusargs flag:
//   +imem_hex=<path>
// If no plusargs is set, memory is zero-initialized. An all-zero
// word decodes as illegal in the decoder, which is the right
// behavior for "PC ran off the end of code."
//
// Pre-empting the byte-ordering bug from the plan: my assembler
// emits one 32-bit hex word per line. $readmemh reads each line as
// one word. The internal representation is mem[word_index] = word,
// little-endian when sliced into bytes by data_memory or by an
// instruction fetch. The whole project never mixes hex files that
// were laid out byte-per-line with hex files laid out word-per-line.
//
// Honest note: this is a ROM. The pipeline stage where this becomes
// the cache backing store is stage 4; I will reshape this module
// then. For now I want a small combinational read so the single-cycle
// datapath can finish in one cycle.

`default_nettype none

module instr_memory #(
    parameter int DEPTH_WORDS = 1024   // 4 KiB at 32 b/word
) (
    // verilator lint_off UNUSEDSIGNAL
    // The top bits above the in-range index and the bottom 2 bits
    // are deliberately not used here. Out-of-range addresses become
    // the top level's misaligned-fetch / fetch-range trap.
    input  logic [31:0] addr,
    // verilator lint_on UNUSEDSIGNAL
    output logic [31:0] inst
);

    localparam int IDX_W = $clog2(DEPTH_WORDS);

    logic [31:0] mem [0:DEPTH_WORDS-1];

    // Initialize at sim start. Verilator handles $readmemh fine; the
    // path is whatever the testbench sets via plusargs. If nothing is
    // passed, the for-loop above keeps memory at zero.
    string imem_path;
    initial begin
        for (int i = 0; i < DEPTH_WORDS; i = i + 1) begin
            mem[i] = 32'h0;
        end
        if ($value$plusargs("imem_hex=%s", imem_path)) begin
            $readmemh(imem_path, mem);
        end
    end

    // Word index = byte address >> 2. The bottom two bits are
    // ignored here; misaligned-fetch trap belongs at the top level
    // where I can halt the simulation cleanly.
    logic [IDX_W-1:0] word_idx;
    assign word_idx = addr[IDX_W+1:2];
    assign inst = mem[word_idx];

endmodule

`default_nettype wire
