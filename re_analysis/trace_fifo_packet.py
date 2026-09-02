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

# Disassemble 0x18000a1b4 to 0x18000a250
code = get_code(0x18000a1b4, 150)
for insn in cs.disasm(code, 0x18000a1b4):
    print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")

