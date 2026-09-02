import pefile
import capstone

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase
text_sec = [s for s in pe.sections if s.Name.startswith(b'.text')][0]
text_data = text_sec.get_data()
text_va = image_base + text_sec.VirtualAddress

cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

def get_code(va, size):
    offset = va - text_va
    return text_data[offset:offset+size]

# Let's disassemble fw9366_init_chip (around 0x180001800)
# and fw9366_cfg_init (around 0x180002770)
def disasm_func_full(start_va, max_bytes=2000):
    code = get_code(start_va, max_bytes)
    print(f"\n==========================================")
    print(f"=== Function at 0x{start_va:x} ===")
    print(f"==========================================")
    for insn in cs.disasm(code, start_va):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")
        if insn.mnemonic == 'ret':
            break

# Let's find exact function starts
# 0x180001875 has lea rdi, [rip + 0x293c4] -> fw9366_init_chip string
# 0x180002770 has lea rsi, [rip + 0x28849] -> fw9366_cfg_init string
disasm_func_full(0x180001860, 400)
disasm_func_full(0x180002750, 400)

