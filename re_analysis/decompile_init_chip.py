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

def disasm_range(va, size):
    code = get_code(va, size)
    print(f"\n=== Range 0x{va:x} - 0x{va+size:x} ===")
    for insn in cs.disasm(code, va):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")

# Find start of function preceding 0x180001875
disasm_range(0x180001650, 400)

