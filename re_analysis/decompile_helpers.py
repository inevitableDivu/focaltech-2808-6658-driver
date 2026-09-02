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

def disasm_func(start_va, count=25):
    code = get_code(start_va, count * 15)
    print(f"\n=== Function at 0x{start_va:x} ===")
    cur = 0
    for insn in cs.disasm(code, start_va):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")
        cur += 1
        if cur >= count or (insn.mnemonic == 'ret' and cur > 3):
            break

# 0x180002b9c (modify bitfield)
disasm_func(0x180002b9c, 25)
# 0x180002ae8 (set scan rate)
disasm_func(0x180002ae8, 25)
# 0x180002bd4
disasm_func(0x180002bd4, 25)
# 0x18000714c
disasm_func(0x18000714c, 25)

