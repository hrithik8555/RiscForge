// data_memory.sv
//
// Single-cycle data memory: combinational read, synchronous write.
// Byte / halfword / word access with sign- or zero-extension on
// loads. Two memory-mapped IO addresses are decoded ahead of the
// backing array:
//   - tohost  (default 0x80001000): a store here pulses tohost_we and
//     exposes the written word on tohost_data. The riscv-tests harness
//     convention is that a write of 1 means "all tests passed" and any
//     other value encodes a failing test number as (n << 1) | 1. The
//     top level / testbench watches tohost_we and stops the sim. Stage
//     1 runs hand-written programs (Path B) so this is our own halt
//     signal; the riscv-tests suite itself runs on the emulator.
//   - UART    (default 0xFFFF0000): a store here pulses uart_we with
//     the low byte on uart_data, which the testbench prints. Loads from
//     either MMIO address return zero.
//
// Design notes:
//   - The backing store is a word array (one 32-bit word per line for
//     $readmemh, matching the assembler's output and instr_memory).
//     Sub-word writes are read-modify-write on the addressed word.
//   - Loaded at sim start from +dmem_hex=<path> if present, else zero.
//     In a full run the testbench loads the SAME image into both
//     instr_memory and data_memory; data writes only touch this copy,
//     which is fine because stage-1 programs are not self-modifying.
//   - Misaligned access (halfword with addr[0]=1, word with addr[1:0]
//     != 0) raises `misaligned`. Per the cross-cutting decision the
//     top level turns that into a halt. MMIO addresses are word
//     aligned so they never trip it.
//
// Honest shortcut: this is a flat RAM with no latency. The plan raises
// memory latency to 4 cycles in stage 4 when the cache lands; I will
// reshape the read path then. For now a combinational read keeps the
// single-cycle datapath to one cycle per instruction.

`default_nettype none

module data_memory
    import riscv_pkg::*;
#(
    parameter int          DEPTH_WORDS = 4096,           // 16 KiB
    parameter logic [31:0] TOHOST_ADDR = 32'h8000_1000,
    parameter logic [31:0] UART_ADDR   = 32'hFFFF_0000
) (
    input  logic            clk,
    input  logic            rst,

    input  logic [31:0]     addr,
    input  logic [31:0]     write_data,
    input  logic            mem_read,
    input  logic            mem_write,
    input  mem_size_e       mem_size,
    input  logic            mem_unsigned,

    output logic [31:0]     read_data,
    output logic            misaligned,

    // MMIO observation ports for the testbench / top level
    output logic            tohost_we,
    output logic [31:0]     tohost_data,
    output logic            uart_we,
    output logic [7:0]      uart_data
);

    localparam int IDX_W = $clog2(DEPTH_WORDS);

    logic [31:0] mem [0:DEPTH_WORDS-1];

    // ---------- address decomposition
    logic [IDX_W-1:0] word_idx;
    logic [1:0]       byte_off;
    assign word_idx = addr[IDX_W+1:2];
    assign byte_off = addr[1:0];

    logic is_tohost, is_uart, is_mmio;
    assign is_tohost = (addr == TOHOST_ADDR);
    assign is_uart   = (addr == UART_ADDR);
    assign is_mmio   = is_tohost | is_uart;

    // ---------- misalignment check (only meaningful on an access)
    always_comb begin
        misaligned = 1'b0;
        if (mem_read || mem_write) begin
            unique case (mem_size)
                MEM_H:   misaligned = (byte_off[0] != 1'b0);
                MEM_W:   misaligned = (byte_off != 2'b00);
                default: misaligned = 1'b0; // byte access is always aligned
            endcase
            // MMIO accesses are defined word-aligned; do not flag them.
            if (is_mmio) begin
                misaligned = 1'b0;
            end
        end
    end

    // ---------- initialization
    string dmem_path;
    initial begin
        for (int i = 0; i < DEPTH_WORDS; i = i + 1) begin
            mem[i] = 32'h0;
        end
        if ($value$plusargs("dmem_hex=%s", dmem_path)) begin
            $readmemh(dmem_path, mem);
        end
    end

    // ---------- combinational read
    logic [31:0] word;
    logic [7:0]  sel_byte;
    logic [15:0] sel_half;
    assign word = mem[word_idx];

    always_comb begin
        // default byte/half selection by offset
        unique case (byte_off)
            2'b00: sel_byte = word[7:0];
            2'b01: sel_byte = word[15:8];
            2'b10: sel_byte = word[23:16];
            2'b11: sel_byte = word[31:24];
        endcase
        // halfword: offset bit 1 picks lower/upper half (bit 0 must be
        // zero or it is misaligned, handled above)
        sel_half = byte_off[1] ? word[31:16] : word[15:0];

        read_data = 32'h0;
        if (mem_read) begin
            if (is_mmio) begin
                // loads from MMIO return zero per the cross-cutting note
                read_data = 32'h0;
            end else begin
                unique case (mem_size)
                    MEM_B: read_data = mem_unsigned
                                       ? {24'h0, sel_byte}
                                       : {{24{sel_byte[7]}}, sel_byte};
                    MEM_H: read_data = mem_unsigned
                                       ? {16'h0, sel_half}
                                       : {{16{sel_half[15]}}, sel_half};
                    MEM_W: read_data = word;
                    default: read_data = 32'h0;
                endcase
            end
        end
    end

    // ---------- MMIO write strobes (combinational pulses, valid in the
    // cycle the store executes)
    always_comb begin
        tohost_we   = mem_write & is_tohost;
        tohost_data = write_data;
        uart_we     = mem_write & is_uart;
        uart_data   = write_data[7:0];
    end

    // ---------- synchronous write to the backing array
    // Sub-word stores are read-modify-write on the addressed word.
    // MMIO stores never touch the array. A misaligned store does not
    // commit (the top level halts on `misaligned` anyway, but dropping
    // the write keeps memory clean if a test ignores the trap).
    logic [31:0] next_word;
    always_comb begin
        next_word = word;
        unique case (mem_size)
            MEM_B: begin
                unique case (byte_off)
                    2'b00: next_word[7:0]   = write_data[7:0];
                    2'b01: next_word[15:8]  = write_data[7:0];
                    2'b10: next_word[23:16] = write_data[7:0];
                    2'b11: next_word[31:24] = write_data[7:0];
                endcase
            end
            MEM_H: begin
                if (byte_off[1]) next_word[31:16] = write_data[15:0];
                else             next_word[15:0]  = write_data[15:0];
            end
            MEM_W: next_word = write_data;
            default: next_word = word;
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst && mem_write && !is_mmio && !misaligned) begin
            mem[word_idx] <= next_word;
        end
    end

endmodule

`default_nettype wire
