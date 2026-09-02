import pefile
import capstone

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase
text_sec = [s for s in pe.sections if s.Name.startswith(b'.text')][0]
text_data = text_sec.get_data()
text_va = image_base + text_sec.VirtualAddress

cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
cs.detail = True

def get_code(va, size):
    offset = va - text_va
    return text_data[offset:offset+size]

def disasm_func(va, max_insns=70):
    code = get_code(va, max_insns * 15)
    print(f"\n=== Function at 0x{va:x} ===")
    count = 0
    for insn in cs.disasm(code, va):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")
        count += 1
        if count >= max_insns:
            break
        if insn.mnemonic in ['ret'] and count > 10:
            break

disasm_func(0x18001739c, 60)
disasm_func(0x1800176b8, 60)
disasm_func(0x1800176c8, 60)

