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

def disasm_func(start_va, count=35):
    code = get_code(start_va, count * 15)
    print(f"\n=== Function at 0x{start_va:x} ===")
    cur = 0
    for insn in cs.disasm(code, start_va):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")
        cur += 1
        if cur >= count or (insn.mnemonic == 'ret' and cur > 10):
            break

# 0x180003780
disasm_func(0x180003780, 35)

