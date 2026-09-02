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

# fw9366_init_chip starts at 0x180001868
code = get_code(0x180001868, 0x180002500 - 0x180001868)
print("=== fw9366_init_chip Assembly ===")
for insn in cs.disasm(code, 0x180001868):
    if insn.mnemonic in ['call', 'jmp']:
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")

